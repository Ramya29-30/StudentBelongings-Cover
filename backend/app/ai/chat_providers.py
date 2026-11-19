"""LLM provider layer for CoverMate AI.

One small interface, four adapters. The chatbot (covermate.py / routers/chat.py) only talks to `get_provider()`, so changing AI_PROVIDER in
.env switches the model vendor without touching any chatbot code.

    gemini             Google Gemini API (generateContent / streamGenerateContent). GEMINI_API_KEY, GEMINI_MODEL
    openai             OpenAI Chat Completions.                                      AI_API_KEY, AI_TEXT_MODEL
    anthropic          Anthropic Messages API.                                       AI_API_KEY, AI_TEXT_MODEL
    openai_compatible  Any server speaking Chat Completions (AI_BASE_URL).            AI_API_KEY, AI_TEXT_MODEL

Plain HTTPS through httpx (no vendor SDK). Keys are read from the backend environment only and are sent in headers, never in URLs, so they cannot
end up in access logs. Error messages that leave this module are scrubbed of the key. Nothing here ever returns canned answer text: if the
provider cannot be reached the caller gets ChatUnavailable and must say so.

NOT verified against live endpoints in the build environment (no keys, no route to Google/OpenAI). The request and response shapes follow each
vendor's public API documentation and are exercised against mock transports in tests/test_covermate.py. See docs/COVERMATE_AI.md.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Iterator, Protocol

import httpx

from ..config import settings

log = logging.getLogger("sbc.covermate")
OPENAI_URL = "https://api.openai.com/v1"
ANTHROPIC_URL = "https://api.anthropic.com"
_TRANSPORT: httpx.BaseTransport | None = None  # patched in tests (httpx.MockTransport); None = real network
_sleep = time.sleep  # patched in tests


class ChatUnavailable(Exception):
    """The provider is not configured, unreachable, refused the request, or returned nothing usable. `reason` is for logs and the admin status only."""

    def __init__(self, reason: str, code: str = "provider_error"):
        super().__init__(reason)
        self.reason, self.code = reason, code


@dataclass
class Turn:
    role: str  # "user" | "assistant"
    text: str


class ChatProvider(Protocol):
    name: str
    model: str

    def complete(self, system: str, turns: list[Turn]) -> str: ...
    def stream(self, system: str, turns: list[Turn]) -> Iterator[str]: ...


# ------------------------------------------------------------------ helpers
def _secrets() -> list[str]:
    return [k for k in (settings.GEMINI_API_KEY, settings.AI_API_KEY) if k and len(k) >= 6]


def scrub(text: str) -> str:
    for k in _secrets():
        text = text.replace(k, "[redacted]")
    return text


def _client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(settings.CHAT_TIMEOUT_SECONDS, connect=10.0), transport=_TRANSPORT, follow_redirects=False)


def _explain(resp: httpx.Response) -> ChatUnavailable:
    try:
        resp.read()
        detail = (resp.json().get("error") or {})
        msg = detail.get("message") if isinstance(detail, dict) else str(detail)
    except Exception:
        msg = ""
    code = "auth" if resp.status_code in (401, 403) else "rate_limited" if resp.status_code == 429 else "provider_error"
    return ChatUnavailable(scrub(f"HTTP {resp.status_code}: {(msg or 'no detail')[:200]}"), code)


def _retryable(status: int) -> bool:
    return status in (408, 429, 500, 502, 503, 504)


def _send(method: str, url: str, headers: dict, body: dict, stream: bool) -> Iterator[httpx.Response]:
    """Yield the open response; retries only happen BEFORE any body is consumed (connection errors, 429, 5xx)."""
    attempts = max(1, settings.AI_MAX_RETRIES + 1)
    last: ChatUnavailable | None = None
    for i in range(attempts):
        try:
            with _client() as c:
                with c.stream(method, url, headers=headers, json=body) as r:
                    if r.status_code == 200:
                        yield r
                        return
                    last = _explain(r)
                    if not _retryable(r.status_code):
                        raise last
                    retry_after = r.headers.get("retry-after", "")
                    delay = min(float(retry_after), 5.0) if retry_after.replace(".", "", 1).isdigit() else 0.6 * (2 ** i)
        except httpx.TimeoutException:
            last, delay = ChatUnavailable("timeout", "timeout"), 0.6 * (2 ** i)
        except httpx.TransportError as e:
            last, delay = ChatUnavailable(scrub(f"network error: {type(e).__name__}"), "network"), 0.6 * (2 ** i)
        if i < attempts - 1:
            _sleep(delay)
    raise last or ChatUnavailable("no response")


def _sse_json(resp: httpx.Response) -> Iterator[dict | str]:
    """Server-sent events: yield the parsed JSON of each `data:` line (or the raw string for non-JSON such as [DONE])."""
    for line in resp.iter_lines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if not raw:
            continue
        try:
            yield json.loads(raw)
        except ValueError:
            yield raw


def _json(resp: httpx.Response) -> dict:
    """Parse a provider's JSON body. A proxy error page, an SSE body on the wrong endpoint or any other non-JSON reply becomes ChatUnavailable
    (the controlled "temporarily unavailable" path), never an unhandled 500."""
    try:
        data = resp.json()
    except ValueError:
        raise ChatUnavailable("the provider returned a response that is not JSON", "bad_response") from None
    if not isinstance(data, dict):
        raise ChatUnavailable("the provider returned an unexpected response shape", "bad_response")
    return data


def _collect(it: Iterator[str]) -> str:
    text = "".join(it).strip()
    if not text:
        raise ChatUnavailable("the model returned an empty answer", "empty")
    return text


# ------------------------------------------------------------------ Gemini
class GeminiProvider:
    name = "gemini"

    def __init__(self) -> None:
        self.model = settings.GEMINI_MODEL

    def _body(self, system: str, turns: list[Turn]) -> dict:
        return {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user" if t.role == "user" else "model", "parts": [{"text": t.text}]} for t in turns],
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": settings.CHAT_MAX_OUTPUT_TOKENS}}

    def _headers(self) -> dict:
        return {"x-goog-api-key": settings.GEMINI_API_KEY, "content-type": "application/json"}

    def _text(self, obj: dict) -> str:
        fb = obj.get("promptFeedback") or {}
        if fb.get("blockReason"):
            raise ChatUnavailable(f"prompt blocked by the provider ({fb['blockReason']})", "blocked")
        out = []
        for cand in obj.get("candidates") or []:
            for part in (cand.get("content") or {}).get("parts") or []:
                if isinstance(part.get("text"), str) and not part.get("thought"):
                    out.append(part["text"])
        return "".join(out)

    def stream(self, system: str, turns: list[Turn]) -> Iterator[str]:
        url = f"{settings.GEMINI_BASE_URL}/v1beta/models/{self.model}:streamGenerateContent?alt=sse"
        for r in _send("POST", url, self._headers(), self._body(system, turns), True):
            for ev in _sse_json(r):
                if isinstance(ev, dict):
                    t = self._text(ev)
                    if t:
                        yield t

    def complete(self, system: str, turns: list[Turn]) -> str:
        url = f"{settings.GEMINI_BASE_URL}/v1beta/models/{self.model}:generateContent"
        for r in _send("POST", url, self._headers(), self._body(system, turns), False):
            r.read()
            return _collect(iter([self._text(_json(r))]))
        raise ChatUnavailable("no response")


# ------------------------------------------------------------------ OpenAI and compatible servers
class OpenAIProvider:
    def __init__(self, compatible: bool = False) -> None:
        self.name = "openai_compatible" if compatible else "openai"
        self.model = settings.AI_TEXT_MODEL
        self.base = (settings.AI_BASE_URL.rstrip("/") if compatible else OPENAI_URL)
        self.compatible = compatible

    def _body(self, system: str, turns: list[Turn], stream: bool) -> dict:
        msgs = [{"role": "system", "content": system}] + [{"role": t.role, "content": t.text} for t in turns]
        body = {"model": self.model, "messages": msgs, "temperature": 0.4, "stream": stream}
        body["max_tokens" if self.compatible else "max_completion_tokens"] = settings.CHAT_MAX_OUTPUT_TOKENS
        return body

    def _headers(self) -> dict:
        return {"authorization": f"Bearer {settings.AI_API_KEY}", "content-type": "application/json"}

    def stream(self, system: str, turns: list[Turn]) -> Iterator[str]:
        for r in _send("POST", f"{self.base}/chat/completions", self._headers(), self._body(system, turns, True), True):
            for ev in _sse_json(r):
                if isinstance(ev, dict):
                    for ch in ev.get("choices") or []:
                        t = (ch.get("delta") or {}).get("content")
                        if isinstance(t, str) and t:
                            yield t

    def complete(self, system: str, turns: list[Turn]) -> str:
        for r in _send("POST", f"{self.base}/chat/completions", self._headers(), self._body(system, turns, False), False):
            r.read()
            ch = (_json(r).get("choices") or [{}])[0]
            return _collect(iter([(ch.get("message") or {}).get("content") or ""]))
        raise ChatUnavailable("no response")


# ------------------------------------------------------------------ Anthropic
class AnthropicProvider:
    name = "anthropic"

    def __init__(self) -> None:
        self.model = settings.AI_TEXT_MODEL

    def _body(self, system: str, turns: list[Turn], stream: bool) -> dict:
        return {"model": self.model, "max_tokens": settings.CHAT_MAX_OUTPUT_TOKENS, "system": system, "stream": stream, "temperature": 0.4,
                "messages": [{"role": t.role, "content": t.text} for t in turns]}

    def _headers(self) -> dict:
        return {"x-api-key": settings.AI_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}

    def stream(self, system: str, turns: list[Turn]) -> Iterator[str]:
        for r in _send("POST", f"{ANTHROPIC_URL}/v1/messages", self._headers(), self._body(system, turns, True), True):
            for ev in _sse_json(r):
                if isinstance(ev, dict):
                    if ev.get("type") == "content_block_delta" and (ev.get("delta") or {}).get("type") == "text_delta":
                        yield ev["delta"].get("text", "")
                    elif ev.get("type") == "error":
                        raise ChatUnavailable(scrub(str((ev.get("error") or {}).get("message", "stream error"))[:200]))

    def complete(self, system: str, turns: list[Turn]) -> str:
        for r in _send("POST", f"{ANTHROPIC_URL}/v1/messages", self._headers(), self._body(system, turns, False), False):
            r.read()
            return _collect(iter(b.get("text", "") for b in _json(r).get("content") or [] if b.get("type") == "text"))
        raise ChatUnavailable("no response")


# ------------------------------------------------------------------ selection
def chat_status() -> dict:
    """Configuration state for the UI and administrators. Never contains a key."""
    p = settings.AI_PROVIDER
    problems = []
    if p == "none":
        problems.append("AI_PROVIDER is not set")
    elif p == "gemini":
        if not settings.GEMINI_API_KEY:
            problems.append("GEMINI_API_KEY is missing")
        if not settings.GEMINI_MODEL:
            problems.append("GEMINI_MODEL is missing")
    elif p in ("openai", "anthropic", "openai_compatible"):
        if not settings.AI_API_KEY:
            problems.append("AI_API_KEY is missing")
        if not settings.AI_TEXT_MODEL:
            problems.append("AI_TEXT_MODEL is missing")
        if p == "openai_compatible" and not settings.AI_BASE_URL:
            problems.append("AI_BASE_URL is missing")
    else:
        problems.append("AI_PROVIDER is not recognised")
    model = settings.GEMINI_MODEL if p == "gemini" else settings.AI_TEXT_MODEL
    return {"available": not problems, "provider": p, "model": model or None, "problems": problems}


def get_provider() -> ChatProvider:
    st = chat_status()
    if not st["available"]:
        raise ChatUnavailable("; ".join(st["problems"]), "not_configured")
    p = settings.AI_PROVIDER
    if p == "gemini":
        return GeminiProvider()
    if p == "anthropic":
        return AnthropicProvider()
    return OpenAIProvider(compatible=(p == "openai_compatible"))
