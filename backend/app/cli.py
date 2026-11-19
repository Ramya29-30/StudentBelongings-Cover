"""Operations CLI:  python -m app.cli <command>
  migrate                      apply database migrations
  create-user --username U --role admin|assessor|student [--full-name N]   (password prompted, never echoed)
  ai-check                     send one tiny request to the configured AI provider and print the real result
  backup [--dest DIR]          consistent SQLite backup (uses SQLite's online backup API)
"""
import argparse
import getpass
import sqlite3
from datetime import datetime
from pathlib import Path

from .config import settings


def main() -> None:
    ap = argparse.ArgumentParser(prog="app.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    cu = sub.add_parser("create-user")
    cu.add_argument("--username", required=True)
    cu.add_argument("--role", required=True, choices=["admin", "assessor", "student"])
    cu.add_argument("--full-name", default="")
    sub.add_parser("ai-check")
    bk = sub.add_parser("backup")
    bk.add_argument("--dest", default="")
    a = ap.parse_args()
    if a.cmd == "migrate":
        from .migrate import upgrade_to_head
        upgrade_to_head()
        print("migrations applied")
    elif a.cmd == "create-user":
        from .database import SessionLocal
        from .migrate import upgrade_to_head
        from .models import Student, User, now
        from .security import check_password_policy, hash_password
        from fastapi import HTTPException
        upgrade_to_head()
        pw = getpass.getpass("Password: ")
        if pw != getpass.getpass("Repeat password: "):
            raise SystemExit("passwords differ")
        try:
            check_password_policy(pw, a.username)
        except HTTPException as e:
            raise SystemExit(e.detail)
        with SessionLocal() as db:
            u = User(username=a.username.lower(), full_name=a.full_name or a.username, role=a.role, password_hash=hash_password(pw), password_changed_at=now())
            db.add(u); db.flush()
            if a.role == "student":
                db.add(Student(user_id=u.id))
            db.commit()
        print("user created")
    elif a.cmd == "ai-check":
        from .ai import service
        print(service.status()["message"])
        print(service.check_connection())
    elif a.cmd == "backup":
        if not settings.DATABASE_URL.startswith("sqlite:///"):
            raise SystemExit("backup command supports SQLite only; use pg_dump or your DB tooling for other databases")
        src = Path(settings.DATABASE_URL.replace("sqlite:///", "", 1))
        dest = Path(a.dest) if a.dest else src.parent / "backups"
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / f"{src.stem}-{datetime.now():%Y%m%d-%H%M%S}.db"
        s, d = sqlite3.connect(src), sqlite3.connect(out)
        with d:
            s.backup(d)
        s.close(); d.close()
        for path, mode in ((dest, 0o700), (out, 0o600)):  # backups hold personal data: owner-only (POSIX)
            try:
                path.chmod(mode)
            except OSError:
                pass
        print(f"database backup written to {out}\nalso copy the uploads folder: {settings.UPLOAD_DIR}")


if __name__ == "__main__":
    main()
