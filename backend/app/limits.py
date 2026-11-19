"""Per-user abuse limits. They count rows that already exist (claims, uploads, AI suggestions, payments), so they need no extra table,
survive restarts and work across several worker processes. A reverse proxy should still apply a per-IP request limit (see docs/DEPLOYMENT.md)."""
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import now


def enforce(db: Session, owner_col, owner_id: int, time_col, limit: int, window_minutes: int, what: str, *extra) -> None:
    since = now() - timedelta(minutes=window_minutes)
    q = select(func.count()).select_from(owner_col.class_).where(owner_col == owner_id, time_col > since, *extra)
    if (db.scalar(q) or 0) >= limit:
        raise HTTPException(429, f"Too many {what} in a short time. Please wait a few minutes and try again.", headers={"Retry-After": str(window_minutes * 60)})
