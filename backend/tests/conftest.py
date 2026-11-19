import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="sbc_tests_"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(_TMP / "uploads")
os.environ["APP_ENV"] = "test"
os.environ["AI_PROVIDER"] = "none"  # tests must never call a real AI provider
# A developer's local .env must not change test behaviour: blank every AI/verification setting that the tests do not set themselves.
for _k in ("AI_JSON_MODE", "AI_BASE_URL", "AI_TEXT_MODEL", "AI_VISION_MODEL", "AI_API_KEY", "GEMINI_API_KEY", "GEMINI_MODEL"):
    os.environ[_k] = ""
os.environ["AI_VERIFY_MODE"] = "auto"
os.environ["AUTO_APPROVAL"] = "off"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    from sqlalchemy import text
    Base.metadata.drop_all(engine)
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS alembic_version"))
    with TestClient(app) as c:  # lifespan re-creates tables and seeds demo data
        yield c


def login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password}, headers={"X-Return-Token": "1"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture()
def student(client):
    return login(client, "aarav", "student123")


@pytest.fixture()
def student2(client):
    return login(client, "meera", "student123")


@pytest.fixture()
def admin(client):
    return login(client, "admin", "admin123")


@pytest.fixture()
def assessor(client):
    return login(client, "assessor", "assessor123")
