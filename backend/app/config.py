"""Application configuration, read from environment variables (and an optional .env file)."""
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/


def _load_dotenv() -> None:
    for candidate in (BASE_DIR / ".env", BASE_DIR.parent / ".env"):
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                v = v.strip()
                if v[:1] in ('"', "'"):
                    end = v.find(v[0], 1)  # quoted value: keep everything inside the quotes (including '#'), ignore anything after
                    v = v[1:end] if end > 0 else v[1:]
                elif " #" in v:
                    v = v.split(" #", 1)[0].strip()  # unquoted value: drop a trailing inline comment (as .env.example uses)
                os.environ.setdefault(k.strip(), v)


_load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


_ENV = os.environ.get("APP_ENV", "development").strip().lower()  # development | test | production (anything else is refused at start-up)
VALID_ENVS = ("development", "test", "production")
_DEFAULT_SECRET = "dev-only-secret-change-me"


class Settings:
    APP_ENV = _ENV
    IS_PRODUCTION = _ENV == "production"
    DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{(BASE_DIR / 'data' / 'sbc.db').as_posix()}")
    UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", str(BASE_DIR / "data" / "uploads")))
    SECRET_KEY = os.environ.get("SECRET_KEY", _DEFAULT_SECRET)
    # --- sessions / auth
    SESSION_TTL_MINUTES = int(os.environ.get("SESSION_TTL_MINUTES", "480"))  # absolute lifetime
    SESSION_IDLE_MINUTES = int(os.environ.get("SESSION_IDLE_MINUTES", "60"))  # inactivity timeout
    COOKIE_NAME = os.environ.get("COOKIE_NAME", "sbc_session")
    COOKIE_SECURE = _bool("COOKIE_SECURE", _ENV == "production")
    LOGIN_MAX_FAILURES = int(os.environ.get("LOGIN_MAX_FAILURES", "5"))
    LOGIN_IP_MAX_FAILURES = int(os.environ.get("LOGIN_IP_MAX_FAILURES", "30"))
    LOGIN_WINDOW_MINUTES = int(os.environ.get("LOGIN_WINDOW_MINUTES", "15"))
    MIN_PASSWORD_LENGTH = int(os.environ.get("MIN_PASSWORD_LENGTH", "12" if _ENV == "production" else "8"))
    SEED_DEMO_DATA = _bool("SEED_DEMO_DATA", _ENV != "production")  # demo users/claims: never on by default in production
    BOOTSTRAP_ADMIN_USERNAME = os.environ.get("BOOTSTRAP_ADMIN_USERNAME", "")
    BOOTSTRAP_ADMIN_PASSWORD = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
    LOG_JSON = _bool("LOG_JSON", _ENV == "production")
    TRUST_PROXY = _bool("TRUST_PROXY", False)  # honour X-Forwarded-For (only behind a trusted reverse proxy)
    MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "8"))
    MAX_JSON_BODY_KB = int(os.environ.get("MAX_JSON_BODY_KB", "256"))  # every non-upload request body
    TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "1"))  # number of trusted reverse proxies appending to X-Forwarded-For
    # --- browser origin policy (default: same-origin only, no CORS headers at all)
    CORS_ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    ALLOWED_HOSTS = [h.strip().lower() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]  # e.g. cover.example.org (custom domain)
    # --- abuse limits (database-backed, per user)
    AI_CALLS_PER_10_MIN_STUDENT = int(os.environ.get("AI_CALLS_PER_10_MIN_STUDENT", "10"))
    AI_CALLS_PER_10_MIN_STAFF = int(os.environ.get("AI_CALLS_PER_10_MIN_STAFF", "30"))
    AI_MAX_CONCURRENCY = int(os.environ.get("AI_MAX_CONCURRENCY", "4"))
    CLAIMS_PER_HOUR = int(os.environ.get("CLAIMS_PER_HOUR", "10"))
    UPLOADS_PER_HOUR = int(os.environ.get("UPLOADS_PER_HOUR", "60"))
    PAYMENT_REQUESTS_PER_HOUR = int(os.environ.get("PAYMENT_REQUESTS_PER_HOUR", "30"))
    ASSETS_PER_HOUR = int(os.environ.get("ASSETS_PER_HOUR", "30"))
    # --- legal pages: facts only the operator can supply (never invented by the software)
    LEGAL_OPERATOR_NAME = os.environ.get("LEGAL_OPERATOR_NAME", "").strip()
    LEGAL_CONTACT_EMAIL = os.environ.get("LEGAL_CONTACT_EMAIL", "").strip()
    LEGAL_POSTAL_ADDRESS = os.environ.get("LEGAL_POSTAL_ADDRESS", "").strip()
    LEGAL_GOVERNING_LAW = os.environ.get("LEGAL_GOVERNING_LAW", "").strip()
    LEGAL_REVIEWED_BY_COUNSEL = _bool("LEGAL_REVIEWED_BY_COUNSEL", False)  # set true ONLY after a lawyer has reviewed the pages
    # --- CoverMate AI chat (generative LLM; see docs/COVERMATE_AI.md). Keys live only in the backend environment.
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip()
    GEMINI_BASE_URL = os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/")
    CHAT_TIMEOUT_SECONDS = float(os.environ.get("CHAT_TIMEOUT_SECONDS", "60"))
    CHAT_MAX_OUTPUT_TOKENS = int(os.environ.get("CHAT_MAX_OUTPUT_TOKENS", "900"))
    CHAT_MAX_CONCURRENCY = int(os.environ.get("CHAT_MAX_CONCURRENCY", "4"))
    CHAT_MAX_MESSAGE_CHARS = int(os.environ.get("CHAT_MAX_MESSAGE_CHARS", "1500"))
    CHAT_HISTORY_MESSAGES = int(os.environ.get("CHAT_HISTORY_MESSAGES", "12"))       # newest messages sent back to the model
    CHAT_HISTORY_MAX_CHARS = int(os.environ.get("CHAT_HISTORY_MAX_CHARS", "6000"))   # character budget for that history
    CHAT_MESSAGES_PER_10_MIN = int(os.environ.get("CHAT_MESSAGES_PER_10_MIN", "20"))
    CHAT_RETENTION_DAYS = int(os.environ.get("CHAT_RETENTION_DAYS", "90"))           # stored conversations older than this are deleted at startup
    # --- AI provider. AI_PROVIDER: none | gemini | anthropic | openai | openai_compatible
    AI_PROVIDER = os.environ.get("AI_PROVIDER", "none").strip().lower()
    AI_API_KEY = os.environ.get("AI_API_KEY", "")
    AI_BASE_URL = os.environ.get("AI_BASE_URL", "")
    AI_TEXT_MODEL = os.environ.get("AI_TEXT_MODEL", "")
    AI_VISION_MODEL = os.environ.get("AI_VISION_MODEL", "")
    AI_TIMEOUT_SECONDS = float(os.environ.get("AI_TIMEOUT_SECONDS", "60"))
    AI_JSON_MODE = os.environ.get("AI_JSON_MODE", "").strip().lower()  # json_schema | json_object | none (openai-style providers)
    AI_MAX_RETRIES = int(os.environ.get("AI_MAX_RETRIES", "2"))
    AI_MAX_IMAGE_MB = float(os.environ.get("AI_MAX_IMAGE_MB", "5"))
    # --- v3 claim-image verification (see docs/AI_VERIFICATION.md)
    AI_VERIFY_MODE = os.environ.get("AI_VERIFY_MODE", "auto").strip().lower()  # auto | dev_simulation (forbidden in production)
    MODEL_DIR = Path(os.environ.get("MODEL_DIR", str(BASE_DIR / "models")))
    ASSET_MODEL_FILE = os.environ.get("ASSET_MODEL_FILE", "yolo11n.onnx")      # COCO object detector (asset identification)
    DAMAGE_MODEL_FILE = os.environ.get("DAMAGE_MODEL_FILE", "damage_model.onnx")  # user-trained damage detector (not shipped)
    DETECTION_MIN_CONFIDENCE = float(os.environ.get("DETECTION_MIN_CONFIDENCE", "0.35"))
    BLUR_MIN_LAPLACIAN_VAR = float(os.environ.get("BLUR_MIN_LAPLACIAN_VAR", "60"))
    CLAIM_IMAGES_MAX = int(os.environ.get("CLAIM_IMAGES_MAX", "5"))
    ESTIMATE_TOLERANCE = float(os.environ.get("ESTIMATE_TOLERANCE", "1.5"))  # student estimate above reference cost x this goes to exceptional review
    MAX_VERIFICATION_RUNS = int(os.environ.get("MAX_VERIFICATION_RUNS", "3"))
    # --- v4 registration evidence, registered-device matching, authenticity checks (see docs/EVIDENCE_AND_FRAUD_CHECKS.md)
    EVIDENCE_PER_ASSET_MAX = int(os.environ.get("EVIDENCE_PER_ASSET_MAX", "10"))          # all files of one registration, including front, back and invoice
    # Device matching thresholds are HEURISTIC and UNCALIBRATED until you measure them on labelled pairs (ai_training/evaluate_device_matching.py).
    DEVICE_MATCH_STRONG = float(os.environ.get("DEVICE_MATCH_STRONG", "0.55"))
    DEVICE_MATCH_PARTIAL = float(os.environ.get("DEVICE_MATCH_PARTIAL", "0.25"))
    DEVICE_MATCH_MIN_KEYPOINTS = int(os.environ.get("DEVICE_MATCH_MIN_KEYPOINTS", "40"))  # fewer keypoints in either image = "not enough detail to compare"
    DUP_DHASH_MAX_DISTANCE = int(os.environ.get("DUP_DHASH_MAX_DISTANCE", "5"))
    DUP_PHASH_MAX_DISTANCE = int(os.environ.get("DUP_PHASH_MAX_DISTANCE", "8"))
    # AUTO_APPROVAL: off (default) = every claim that passes the policy rules is held for a staff member's approval before any (simulated) payout;
    # verified_only = the rule engine may approve without a human, but ONLY when a trained damage model is installed, device matching succeeded and no risk indicator was raised.
    AUTO_APPROVAL = os.environ.get("AUTO_APPROVAL", "off").strip().lower()


settings = Settings()


_ORIGIN_RE = re.compile(r"^https?://[A-Za-z0-9.-]+(:\d{1,5})?$")


def validate_production_settings() -> None:
    """Fail fast on unsafe configuration. Runs in every environment; the production-only checks follow the common ones."""
    common = []
    if settings.AI_VERIFY_MODE not in ("auto", "dev_simulation"):
        common.append(f"AI_VERIFY_MODE must be auto or dev_simulation (got {settings.AI_VERIFY_MODE!r})")
    if settings.AUTO_APPROVAL not in ("off", "verified_only"):
        common.append(f"AUTO_APPROVAL must be off or verified_only (got {settings.AUTO_APPROVAL!r})")
    if not (0 < settings.DEVICE_MATCH_PARTIAL < settings.DEVICE_MATCH_STRONG <= 1):
        common.append("DEVICE_MATCH_PARTIAL must be above 0 and below DEVICE_MATCH_STRONG, which must not exceed 1")
    if settings.EVIDENCE_PER_ASSET_MAX < 3:
        common.append("EVIDENCE_PER_ASSET_MAX must be at least 3 (front photo, back photo, invoice)")
    if settings.AI_PROVIDER not in ("none", "gemini", "anthropic", "openai", "openai_compatible"):
        common.append(f"AI_PROVIDER must be none, gemini, anthropic, openai or openai_compatible (got {settings.AI_PROVIDER!r})")
    if settings.APP_ENV not in VALID_ENVS:
        common.append(f"APP_ENV must be one of {VALID_ENVS} (got {settings.APP_ENV!r}); an unknown value would silently behave like development")
    for o in settings.CORS_ALLOWED_ORIGINS:
        if not _ORIGIN_RE.match(o):
            common.append(f"CORS_ALLOWED_ORIGINS entry {o!r} is not an explicit origin such as https://app.example.org (wildcards, 'null' and paths are refused because cookies are used)")
        elif settings.IS_PRODUCTION and not o.startswith("https://"):
            common.append(f"CORS_ALLOWED_ORIGINS entry {o!r} must use https in production")
    for h in settings.ALLOWED_HOSTS:
        if "*" in h or "/" in h:
            common.append(f"ALLOWED_HOSTS entry {h!r} must be a plain host name")
    if settings.TRUSTED_PROXY_HOPS < 1:
        common.append("TRUSTED_PROXY_HOPS must be at least 1")
    if common:
        raise RuntimeError("Unsafe configuration: " + "; ".join(common))
    if not settings.IS_PRODUCTION:
        return
    problems = []
    if settings.SECRET_KEY == _DEFAULT_SECRET or settings.SECRET_KEY.startswith("change-me") or len(settings.SECRET_KEY) < 32:
        problems.append("SECRET_KEY must be set to a random value of at least 32 characters")
    if not settings.COOKIE_SECURE:
        problems.append("COOKIE_SECURE must be true in production (serve over HTTPS)")
    if settings.SEED_DEMO_DATA:
        problems.append("SEED_DEMO_DATA must be false in production")
    if settings.AI_VERIFY_MODE == "dev_simulation":
        problems.append("AI_VERIFY_MODE=dev_simulation must not be used in production (it does not analyse images)")
    if problems:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))
