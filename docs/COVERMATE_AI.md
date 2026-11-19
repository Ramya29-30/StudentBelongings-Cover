# CoverMate AI

CoverMate AI is the generative chatbot. It is a language model (LLM), separate from the computer vision damage check described in `AI_VERIFICATION.md`. It explains insurance and the signed-in student's own policies and claims in simple language. It never decides a claim.

## How a message is handled

```
Student types a question
  -> React chat window (src/components/CoverMate.tsx)
  -> POST /api/ai/chat/stream   (session cookie + CSRF token)
  -> routers/chat.py            authenticate, rate limit, validate size
  -> ai/covermate.py            retrieve THIS student's policies, claims and the catalogue from the database
                                build the system prompt + <backend_data>, add the most recent messages only
  -> ai/chat_providers.py       call the configured LLM over HTTPS
  -> the LLM writes a new answer, streamed back as server-sent events
  -> the answer is saved to the conversation and shown in the window
```

Every new message is sent to the configured model. There is no list of stored answers, no keyword matching and no canned fallback text anywhere in the chat path. If the provider is not configured or cannot be reached, the student sees exactly: `CoverMate AI is temporarily unavailable. Please try again later.`

## Endpoints

| Method and path | Purpose |
|---|---|
| `POST /api/ai/chat` | One question, one JSON answer. Body: `message`, optional `conversation_id`, `policy_id`, `claim_id`, `retry` |
| `POST /api/ai/chat/stream` | Same, streamed as server-sent events: `meta`, `delta`, `done`, `error` |
| `GET /api/ai/chat/status` | Is the assistant configured? Administrators also see provider, model and problems. Never keys |
| `GET /api/ai/chat/conversations` | The signed-in user's recent conversations |
| `GET /api/ai/chat/conversations/{id}` | Messages of one conversation |
| `POST /api/ai/chat/conversations/{id}/clear` | Delete the messages, keep the conversation |
| `DELETE /api/ai/chat/conversations/{id}` | Delete the conversation |

## Provider configuration

Set these in `.env` (backend only). Plain HTTPS through `httpx`, no vendor SDK, so providers are interchangeable by changing `AI_PROVIDER`.

| `AI_PROVIDER` | Variables |
|---|---|
| `gemini` | `GEMINI_API_KEY`, `GEMINI_MODEL` |
| `openai` | `AI_API_KEY`, `AI_TEXT_MODEL` |
| `anthropic` | `AI_API_KEY`, `AI_TEXT_MODEL` |
| `openai_compatible` | `AI_API_KEY`, `AI_TEXT_MODEL`, `AI_BASE_URL` |
| `none` | Chat reports itself unavailable |

Take model names from your provider's current documentation. Free-tier availability and quotas change, so check yours; the app does not assume any.

Requires internet access from the machine running the backend, and a valid key.

## What the model is told

* **System prompt:** persona (simple everyday English, short steps, relatable examples, honest about not knowing), grounding rules, and prompt-injection rules.
* **`<backend_data>`:** read from the database by server code, scoped by the user id in the session. It contains the product catalogue (prices, limits, exclusions), that student's policies and that student's claims with the recorded status, reasons and amounts.
* **History:** only the newest messages, bounded by `CHAT_HISTORY_MESSAGES` and `CHAT_HISTORY_MAX_CHARS`, so context never grows without limit. Follow-ups ("so will I get all the money?") work because the previous turns and the focused policy or claim travel with the conversation id.

Never sent to the model: serial numbers or IMEIs, email addresses, full names, file names, images, passwords or tokens.

## Grounding and hallucination controls

* Official figures come only from `<backend_data>`. The prompt tells the model to copy them exactly and to say `This information is not specified in your current policy.` when something is missing.
* General education is kept separate from the student's actual terms ("In general..." versus "In your policy...").
* The model has no tool to look up arbitrary records, so it cannot widen its own access.
* After an answer completes, `check_amounts()` looks for rupee amounts that appear in neither the backend data nor the student's own messages. If it finds any, the UI shows a notice that they may be examples. This is a safety net, not a guarantee.
* Claim amounts and decisions are copied from the backend's own records. The model explains them and cannot change them.

## Security

* API keys are read from the backend environment, sent in request headers (never URLs) and scrubbed from logs and error messages.
* Every route needs a session. CSRF is enforced for cookie sessions.
* A conversation is always looked up by `(public id AND user id)`, so another user's conversation id returns 404.
* Limits: message length, messages per 10 minutes per user, concurrent provider calls, and output tokens.
* User text and stored text from claims are wrapped as untrusted data. Messages cannot change roles, scope or rules.
* Conversations older than `CHAT_RETENTION_DAYS` are deleted at startup.

## Tests

`backend/tests/test_covermate.py` uses mock HTTP transports (never a real provider) to verify that each new question reaches the model and its reply is returned unchanged, that missing keys and provider failures give the unavailable message without leaking the key, context limits, scoping and cross-user isolation, rate limits and retention. Frontend tests are in `frontend-react/src/test/landing_chat.test.tsx`.

## Limitations

* The provider adapters follow each vendor's public API documentation and are exercised against mock transports. They were **not run against a live endpoint** in the build environment, because no key or route was available. Run a few real questions after adding your key.
* LLM answers can still be wrong or awkward. The amount check catches only rupee figures.
* The assistant explains the recorded claim decision. It cannot approve, reject or recalculate anything.
