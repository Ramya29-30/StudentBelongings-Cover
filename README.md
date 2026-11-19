# StudentBelongings Cover

AI-assisted insurance for students' personal belongings: laptops, smartphones, tablets, earbuds, bicycles and smartwatches. An **academic prototype**: policies, payments and settlements are **simulated**, prices are sample values, it is not a licensed insurance product, and it is not Guidewire software.

Students register assets with front/back photographs and optional purchase evidence. An administrator must approve registration evidence before a policy can be purchased. Students can then file damage claims with photos. The system checks the evidence, explains what it can and cannot verify, applies the policy rules, and sends claims to a person before any payout by default. Administrators manage categories and prices, review registration evidence and exceptional claims, and see AI analytics and a financial performance dashboard.

**Read this about the AI**: image quality, duplicate and metadata checks and asset identification are real. The bundled model recognises only laptops, phones and bicycles and **cannot see damage**. Damage detection needs a model you train (instructions and scripts included) or a vision provider you configure. Without one, claims go to a person instead of being guessed at. `AI_VERIFY_MODE=dev_simulation` (the demo default) assumes the damage from the claim form so the workflow can be shown, and labels every report as simulated. Details: [docs/AI_VERIFICATION.md](docs/AI_VERIFICATION.md).

**CoverMate AI** is a second, separate system: a real generative chatbot (Google Gemini by default; OpenAI, Anthropic or any OpenAI-compatible server by changing one setting). Every message is answered by the model, never from a script. The backend reads the signed-in student's own policies and claims from the database and gives them to the model as official facts, so it explains real terms instead of inventing them. It never decides a claim. **It needs your own provider API key and internet access.** Without a key the chat says it is temporarily unavailable. Setup: [docs/COVERMATE_AI.md](docs/COVERMATE_AI.md).

**Decisions**: AI only produces an evidence report. A separate backend rule engine decides, rejects with the rule that caused it, and sends uncertain or risky claims to staff (never straight to rejection). The older manual assessor workflow, where a human always decides, is preserved.

## Features
* Public landing page (live prices from the database), redesigned sign-in, dashboards and admin screens
* CoverMate AI chat window (streaming, follow-up memory, policy explanation, history, retry, copy)
* Registration, login, roles (student, assessor, administrator), server-side ownership checks
* Eligibility check against administrator-editable minimum values; premiums, coverage, deductibles and exclusions stored in the database
* Premium and claim calculation engine with a visible breakdown; frozen policy terms
* Simulated purchase and monthly premium payments
* Multi-photo asset registration, administrator evidence approval, secure evidence uploads, claim wizard, AI verification report (quality, asset, damage, description, duplicates, authenticity and risk indicators), ten-rule policy engine, human-confirmed simulated settlement
* Admin: overview, categories and plans, policies, claims, review queue, AI analytics, financial performance with charts and a scenario calculator
* Audit log, rate limits, upload hardening, CSRF, Argon2 passwords

## Technology
Python 3.12, FastAPI, SQLAlchemy, Alembic, SQLite (PostgreSQL path documented), Pydantic, onnxruntime, OpenCV (headless), Pillow, NumPy. React 18, TypeScript, Vite, Recharts, Lucide icons, vitest. Playwright for browser tests.

## Run on Windows (no Node.js needed)
1. Install Python 3.12 (python.org, tick "Add to PATH").
2. Unzip, double-click **`start.bat`** (needs internet the first time to install packages).
3. Open http://localhost:8000. Stop with `stop.bat`.

Demo logins (fictional, development only): student `riya` / `student123` (also `karan`, `sana`, `dev`), administrator `admin` / `admin123`, assessor `assessor` / `assessor123`. Or register your own student.
Linux/macOS: `./start.sh`. The package includes the built UI in `frontend/dist`; Node.js 20+ is only needed to rebuild it (`build-frontend.bat`) or run the frontend tests.

**Turn on CoverMate AI**: open `.env` (created by `start.bat`), set `AI_PROVIDER=gemini`, `GEMINI_API_KEY=<your key>` and `GEMINI_MODEL=<a model name from Google's documentation>`, then restart. Never put the key anywhere except `.env`.

**Model setup**: nothing to download. `backend/models/yolo11n.onnx` (Ultralytics YOLO11n, AGPL-3.0) is included. A damage model is optional and separate: see [ai_training/README.md](ai_training/README.md).

## Configuration
Copy `.env.example` to `.env` (`start.bat` does it for you). Production needs real values and the server refuses unsafe ones, including `AI_VERIFY_MODE=dev_simulation`. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Documentation
[PROJECT_WORKFLOW](docs/PROJECT_WORKFLOW.md) | [INSURANCE_MODEL](docs/INSURANCE_MODEL.md) | [AI_VERIFICATION](docs/AI_VERIFICATION.md) | [COVERMATE_AI](docs/COVERMATE_AI.md) | [DATABASE_SCHEMA](docs/DATABASE_SCHEMA.md) | [API_DOCUMENTATION](docs/API_DOCUMENTATION.md) | [SECURITY](docs/SECURITY.md) | [TESTING](docs/TESTING.md) | [DEMO_GUIDE](docs/DEMO_GUIDE.md) | [KNOWN_LIMITATIONS](docs/KNOWN_LIMITATIONS.md)
Earlier v2 documents (rules catalogue, Guidewire concept mapping, security audit, custom domain) remain in `docs/`.

## Layout
| Path | Contents |
|---|---|
| `backend/app` | FastAPI app: `engine/` (pricing, claim calculation, decision rules, legacy rules), `ai/` (vision, verification, provider layer), `routers/`, `v3.py` (self-service logic), migrations in `backend/alembic` |
| `backend/models` | ONNX model files |
| `ai_training/` | Dataset layout, training and evaluation scripts for a damage model |
| `frontend-react/` | React + TypeScript source; `frontend/dist` is the built UI |
| `e2e/` | Playwright specs for the v4 evidence-review and human-confirmation journey; legacy v2 specs in `tests-legacy-v2/` |

Current status and limitations: see [PROJECT_HANDOVER.md](PROJECT_HANDOVER.md), [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md), and [docs/TESTING.md](docs/TESTING.md). The bundled `yolo11n.onnx` identifies a limited set of object categories; it is not a trained damage detector. No damage-model metrics are available until a properly licensed, labelled dataset is trained and evaluated.
