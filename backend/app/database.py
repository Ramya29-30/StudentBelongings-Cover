from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


if settings.DATABASE_URL.startswith("sqlite:///") and ":memory:" not in settings.DATABASE_URL:
    from pathlib import Path
    Path(settings.DATABASE_URL.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {},
                       hide_parameters=True)  # errors/logs never contain bound values (password hashes, claim text)


@event.listens_for(engine, "connect")
def _fk_pragma(dbapi_conn, _):  # enforce foreign keys in SQLite
    if settings.DATABASE_URL.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()  # never leave a half-applied transaction
        raise
    finally:
        db.close()
