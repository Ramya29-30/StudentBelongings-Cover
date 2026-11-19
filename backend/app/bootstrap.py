"""First-run provisioning: demo data (development only) or a bootstrap administrator from the environment."""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import seed
from .config import settings
from .models import SchemaVersion, User, now
from .security import check_password_policy, hash_password

log = logging.getLogger("sbc.bootstrap")


def run(db: Session) -> None:
    if db.scalar(select(User.id).limit(1)):
        return
    if settings.SEED_DEMO_DATA:
        log.warning("seeding DEMO data with well-known passwords (SEED_DEMO_DATA=true) - never do this in production")
        seed.run(db)
        return
    u, p = settings.BOOTSTRAP_ADMIN_USERNAME.strip().lower(), settings.BOOTSTRAP_ADMIN_PASSWORD
    if u and p:
        check_password_policy(p, u)
        db.add(SchemaVersion(version=1))
        db.add(User(username=u, full_name="Bootstrap Administrator", role="admin", password_hash=hash_password(p), password_changed_at=now()))
        db.commit()
        log.info("bootstrap administrator '%s' created - change the password after first login and remove BOOTSTRAP_ADMIN_* from the environment", u)
    else:
        log.warning("no users exist. Set BOOTSTRAP_ADMIN_USERNAME/PASSWORD or run: python -m app.cli create-user --role admin")
