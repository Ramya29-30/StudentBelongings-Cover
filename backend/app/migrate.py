"""Programmatic Alembic upgrade used at start-up and by the CLI."""
import logging
import shutil
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from .config import BASE_DIR, settings
from .database import engine

log = logging.getLogger("sbc.migrate")
BASELINE = "0001"


def _config() -> Config:
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    return cfg


def _sqlite_path() -> Path | None:
    if settings.DATABASE_URL.startswith("sqlite:///") and ":memory:" not in settings.DATABASE_URL:
        return Path(settings.DATABASE_URL.replace("sqlite:///", "", 1))
    return None


def upgrade_to_head() -> None:
    cfg = _config()
    head = ScriptDirectory.from_config(cfg).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    tables = set(inspect(engine).get_table_names())
    if current is None and "users" in tables:
        # Database created by the v1.0 prototype (create_all, no alembic_version): its schema equals the baseline revision.
        log.info("legacy v1 database detected - stamping baseline %s", BASELINE)
        command.stamp(cfg, BASELINE)
        current = BASELINE
    db_file = _sqlite_path()
    if current != head and current is not None and db_file and db_file.exists():
        backup_dir = db_file.parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        dest = backup_dir / f"{db_file.stem}-pre-migration-{datetime.now():%Y%m%d-%H%M%S}.db"
        shutil.copy2(db_file, dest)
        log.info("database backed up before migration: %s", dest)
    command.upgrade(cfg, "head")
