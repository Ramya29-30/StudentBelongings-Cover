"""CoverMate AI endpoints.

POST   /api/ai/chat                               one request, one JSON answer
POST   /api/ai/chat/stream                        same, streamed as server-sent events (delta ... done)
GET    /api/ai/chat/status                        is the assistant configured? (no secrets)
GET    /api/ai/chat/conversations                 the signed-in user's conversations
GET    /api/ai/chat/conversations/{id}            messages of one conversation
POST   /api/ai/chat/conversations/{id}/clear      delete the messages, keep the conversation
DELETE /api/ai/chat/conversations/{id}            delete the conversation

Every route requires a session (CSRF is enforced for browser cookies by current_user). Every conversation is looked up by (public_id AND user_id),
so another user's id is indistinguishable from a missing one (404). The model is only ever called with text this module assembled.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..ai import covermate as cm
from ..ai.chat_providers import ChatProvider, ChatUnavailable, chat_status, get_provider, scrub
from ..config import settings
from ..database import SessionLocal, get_db
from ..limits import enforce
from ..models import ChatConversation, ChatMessage, User, now
from ..security import current_user

log = logging.getLogger("sbc.covermate")
router = APIRouter(prefix="/api/ai/chat", tags=["covermate-ai"])
UNAVAILABLE = "CoverMate AI is temporarily unavailable. Please try again later."
_SLOTS = threading.BoundedSemaphore(max(1, settings.CHAT_MAX_CONCURRENCY))
_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")


@contextmanager
def _slot() -> Iterator[None]:
    if not _SLOTS.acquire(timeout=3):
        raise HTTPException(503, "CoverMate AI is busy. Please try again in a moment.", headers={"Retry-After": "10"})
    try:
        yield
    finally:
        _SLOTS.release()


class ChatIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = Field(default=None, max_length=36)
    policy_id: int | None = Field(default=None, ge=1)   # optional hint from the UI ("explain this policy"); ownership is verified server-side
    claim_id: int | None = Field(default=None, ge=1)
    retry: bool = False                                # replace the last exchange (the same question again) instead of adding a new one

    @field_validator("message")
    @classmethod
    def _m(cls, v: str) -> str:
        v = v.replace("\x00", "").strip()
        if not v:
            raise ValueError("message must not be empty")
        if len(v) > settings.CHAT_MAX_MESSAGE_CHARS:
            raise ValueError(f"message is too long (limit {settings.CHAT_MAX_MESSAGE_CHARS} characters)")
        return v

    @field_validator("conversation_id")
    @classmethod
    def _c(cls, v: str | None) -> str | None:
        if v is not None and not _UUID.match(v):
            raise ValueError("conversation_id is not valid")
        return v


@dataclass
class Prepared:
    conv_public_id: str
    conv_id: int
    user_id: int
    system: str
    turns: list
    backend_data: str
    user_texts: list[str]
    meta: dict
    provider: ChatProvider


def _out(m: ChatMessage) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat(), "notice": (m.meta or {}).get("notice")}


def _get_conv(db: Session, user: User, public_id: str) -> ChatConversation:
    c = db.scalar(select(ChatConversation).where(ChatConversation.public_id == public_id, ChatConversation.user_id == user.id)) if _UUID.match(public_id) else None
    if c is None:
        raise HTTPException(404, "Conversation not found")
    return c


def _prepare(db: Session, user: User, body: ChatIn) -> Prepared:
    try:
        provider = get_provider()
    except ChatUnavailable as e:
        log.warning("covermate unavailable: %s", scrub(e.reason))
        raise HTTPException(503, UNAVAILABLE, headers={"Retry-After": "60"})
    enforce(db, ChatMessage.user_id, user.id, ChatMessage.created_at, settings.CHAT_MESSAGES_PER_10_MIN, 10, "chat messages", ChatMessage.role == "user")
    if body.conversation_id:
        conv = _get_conv(db, user, body.conversation_id)
    else:
        conv = ChatConversation(public_id=str(uuid.uuid4()), user_id=user.id, title=re.sub(r"\s+", " ", body.message)[:60])
        db.add(conv); db.flush()
    if body.retry and conv.messages:
        if conv.messages[-1].role == "assistant":
            db.delete(conv.messages[-1])
        db.flush(); db.refresh(conv)
        if conv.messages and conv.messages[-1].role == "user":
            db.delete(conv.messages[-1])
        db.flush(); db.refresh(conv)
    db.add(ChatMessage(conversation_id=conv.id, user_id=user.id, role="user", content=body.message)); db.flush(); db.refresh(conv)
    backend_data, meta = cm.build_context(db, user, conv, body.message, body.policy_id, body.claim_id)
    conv.updated_at = now()
    turns = cm.history_turns(list(conv.messages))
    user_texts = [m.content for m in conv.messages if m.role == "user"][-6:]
    p = Prepared(conv.public_id, conv.id, user.id, cm.system_prompt(backend_data), turns, backend_data, user_texts, meta, provider)
    db.commit()
    return p


def _notice_for(p: Prepared, answer: str) -> tuple[str | None, list[str]]:
    odd = cm.check_amounts(answer, p.backend_data, p.user_texts) if p.meta.get("scope") == "student_records" else []
    return (cm.UNGROUNDED_NOTICE if odd else None), odd


def _save_answer(p: Prepared, answer: str, ms: int) -> ChatMessage:
    notice, odd = _notice_for(p, answer)
    with SessionLocal() as db:
        m = ChatMessage(conversation_id=p.conv_id, user_id=p.user_id, role="assistant", content=answer, provider=p.provider.name, model=p.provider.model,
                        meta={"scope": p.meta.get("scope"), "policies": p.meta.get("policies"), "claims": p.meta.get("claims"), "focus_policy": p.meta.get("focus_policy"),
                              "focus_claim": p.meta.get("focus_claim"), "notice": notice, "ungrounded_amount_count": len(odd), "latency_ms": ms})
        db.add(m)
        conv = db.get(ChatConversation, p.conv_id)
        if conv:
            conv.updated_at = now()
        db.commit(); db.refresh(m)
        log.info("covermate answered", extra={"provider": p.provider.name, "latency_ms": ms, "scope": p.meta.get("scope"), "ungrounded_amounts": len(odd)})
        return _out(m)


def _focus(db: Session, p: Prepared) -> dict:
    c = db.get(ChatConversation, p.conv_id)
    return {"policy_number": p.meta.get("focus_policy"), "claim_number": p.meta.get("focus_claim"), "policy_id": c.focus_policy_id if c else None, "claim_id": c.focus_claim_id if c else None}


# ------------------------------------------------------------------ routes
@router.get("/status")
def status(user: User = Depends(current_user)):
    st = chat_status()
    out = {"available": st["available"], "unavailable_message": None if st["available"] else UNAVAILABLE}
    if user.role == "admin":  # configuration details only for administrators, never keys
        out |= {"provider": st["provider"], "model": st["model"], "problems": st["problems"]}
    return out


@router.post("")
def chat(body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _prepare(db, user, body)
    start = time.perf_counter()
    try:
        with _slot():
            answer = p.provider.complete(p.system, p.turns)
    except ChatUnavailable as e:
        log.warning("covermate provider failure (%s): %s", e.code, scrub(e.reason))
        raise HTTPException(503, UNAVAILABLE, headers={"Retry-After": "30"})
    msg = _save_answer(p, answer, int((time.perf_counter() - start) * 1000))
    return {"conversation_id": p.conv_public_id, "message": msg, "focus": _focus(db, p)}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/stream")
def chat_stream(body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = _prepare(db, user, body)
    focus = _focus(db, p)

    def events() -> Iterator[str]:
        yield _sse("meta", {"conversation_id": p.conv_public_id, "focus": focus})
        start, parts = time.perf_counter(), []
        try:
            with _slot():
                for piece in p.provider.stream(p.system, p.turns):
                    parts.append(piece)
                    yield _sse("delta", {"text": piece})
        except HTTPException:
            yield _sse("error", {"message": "CoverMate AI is busy. Please try again in a moment."})
            return
        except ChatUnavailable as e:
            log.warning("covermate provider failure (%s): %s", e.code, scrub(e.reason))
            yield _sse("error", {"message": UNAVAILABLE})
            return
        answer = "".join(parts).strip()
        if not answer:
            log.warning("covermate empty streamed answer")
            yield _sse("error", {"message": UNAVAILABLE})
            return
        yield _sse("done", {"message": _save_answer(p, answer, int((time.perf_counter() - start) * 1000))})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.get("/conversations")
def conversations(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ChatConversation).where(ChatConversation.user_id == user.id).order_by(ChatConversation.updated_at.desc()).limit(30))
    return [{"id": c.public_id, "title": c.title, "updated_at": c.updated_at.isoformat(), "message_count": len(c.messages)} for c in rows]


@router.get("/conversations/{cid}")
def conversation(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get_conv(db, user, cid)
    return {"id": c.public_id, "title": c.title, "messages": [_out(m) for m in c.messages]}


@router.post("/conversations/{cid}/clear")
def clear(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get_conv(db, user, cid)
    db.execute(delete(ChatMessage).where(ChatMessage.conversation_id == c.id))
    c.focus_policy_id = c.focus_claim_id = None
    db.commit()
    return {"id": c.public_id, "cleared": True}


@router.delete("/conversations/{cid}", status_code=204)
def delete_conversation(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _get_conv(db, user, cid)
    db.delete(c)
    db.commit()
