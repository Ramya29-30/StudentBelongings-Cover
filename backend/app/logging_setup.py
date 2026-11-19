import contextvars
import json
import logging
import sys
from datetime import datetime, timezone

from .config import settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "level": record.levelname, "logger": record.name,
               "msg": record.getMessage(), "request_id": request_id_var.get()}
        for k in ("method", "path", "status", "duration_ms", "user"):
            if hasattr(record, k):
                out[k] = getattr(record, k)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out)


def setup_logging() -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter() if settings.LOG_JSON else logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(settings.LOG_LEVEL)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)  # request logging is done by our middleware (no query strings / bodies)
