"""The shipped .env.example uses trailing '# comments'; copying it verbatim must not corrupt values."""
import importlib
import os

import app.config as config


def test_env_example_values_parse_without_inline_comments(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('APP_ENV=development              # development | production | test\nSECRET_KEY="abc#def"   # keeps the hash inside quotes\nQUOTED=\'x y\'\n', encoding="utf-8")
    for k in ("APP_ENV", "SECRET_KEY", "QUOTED"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(config, "BASE_DIR", tmp_path / "backend")
    (tmp_path / "backend").mkdir()
    config._load_dotenv()
    assert os.environ["APP_ENV"] == "development"
    assert os.environ["SECRET_KEY"] == "abc#def"
    assert os.environ["QUOTED"] == "x y"
    for k in ("APP_ENV", "SECRET_KEY", "QUOTED"):
        monkeypatch.delenv(k, raising=False)
    importlib.reload(config)
