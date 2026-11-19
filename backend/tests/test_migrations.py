"""Alembic migration tests: clean database, upgrade of data at an older revision, and upgrade of a REAL v1.0 prototype database
(tests/fixtures/v1_prototype.db was produced by the original v1.0 code, i.e. create_all with PBKDF2 passwords)."""
import shutil
import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, event, inspect, text

import app.database as database
import app.migrate as migrate
from app.config import settings
from app.database import Base

FIXTURE = Path(__file__).parent / "fixtures" / "v1_prototype.db"
FIXTURE_V3 = Path(__file__).parent / "fixtures" / "v3_populated_0005.db"  # produced by the pre-evidence (revision 0005) code with the demo seed: 8 users, 15 assets, 13 policies, 5 claims


@pytest.fixture()
def dbfile(tmp_path, monkeypatch):
    path = tmp_path / "m.db"
    eng = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(database, "engine", eng)
    monkeypatch.setattr(migrate, "engine", eng)
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{path.as_posix()}")
    yield path, eng
    eng.dispose()


def rows(eng, sql):
    with eng.connect() as c:
        return c.execute(text(sql)).fetchall()


def test_clean_database_upgrade_creates_full_schema_matching_models(dbfile):
    path, eng = dbfile
    migrate.upgrade_to_head()
    tables = set(inspect(eng).get_table_names())
    assert {"users", "policies", "policy_versions", "claims", "auth_sessions", "login_attempts", "claim_reserves", "payments", "reserve_history",
            "payment_events", "system_settings", "alembic_version"} <= tables
    with eng.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c), Base.metadata)
    assert diff == [], f"models and migrations have drifted: {diff}"
    assert rows(eng, "select version_num from alembic_version") == [("0006",)]


def test_upgrade_is_idempotent(dbfile):
    migrate.upgrade_to_head(); migrate.upgrade_to_head()
    assert rows(dbfile[1], "select version_num from alembic_version") == [("0006",)]


def test_upgrade_preserves_data_written_at_baseline_revision(dbfile):
    path, eng = dbfile
    command.upgrade(migrate._config(), "0001")
    with eng.begin() as c:
        c.execute(text("insert into users (id, username, password_hash, full_name, role, created_at) values (1,'s1','x$y','S One','student','2026-01-01')"))
        c.execute(text("insert into users (id, username, password_hash, full_name, role, created_at) values (2,'adm','x$y','Adm','admin','2026-01-01')"))
        c.execute(text("insert into coverage_plans (id,name,description,covered_perils,overall_limit,per_item_limits,cap_at_declared_value,deductible_type,deductible_value,calc_order,"
                       "depreciation,waiting_period_days,required_documents,duplicate_window_days,repair_replace_threshold_pct,disabled_rules,wording,created_at,updated_at) "
                       "values (1,'P','','[\"Theft\"]',1000,'{}',1,'fixed',0,'LIMIT_THEN_DEDUCTIBLE','{}',0,'{}',0,70,'[]','','2026-01-01','2026-01-01')"))
        c.execute(text("insert into policies (id,policy_number,student_id,plan_id,status,start_date,end_date,cancellation_reason,created_at) values (1,'SBC-1',1,1,'Active','2026-01-01','2026-12-31','','2026-01-01')"))
        c.execute(text("insert into policy_versions (policy_id,version,effective_from,reason,snapshot,created_at) values (1,1,'2026-01-01','v1','{\"a\": 1}','2026-01-01'),(1,2,'2026-03-01','v2','{\"a\": 2}','2026-03-01')"))
        c.execute(text("insert into ai_suggestions (id,kind,is_ai,provider,model,status_note,content,accepted,created_at) values (1,'explanation',0,'demo-fallback','','n','{}',0,'2026-01-01')"))
    migrate.upgrade_to_head()
    assert rows(eng, "select version,effective_from from policy_versions order by version") == [(1, "2026-01-01"), (2, "2026-03-01")]
    assert rows(eng, "select username, is_active from users order by id") == [("s1", 1), ("adm", 1)]  # new column gets a safe default
    assert rows(eng, "select validation_status, meta from ai_suggestions") == [("n/a", "{}")]  # new NOT NULL columns backfilled on existing rows


def test_real_v1_prototype_database_is_stamped_upgraded_and_keeps_all_data(dbfile, tmp_path):
    path, eng = dbfile
    shutil.copy(FIXTURE, path)
    before = sqlite3.connect(FIXTURE)
    counts = {t: before.execute(f"select count(*) from {t}").fetchone()[0] for t in
              ("users", "assets", "policies", "policy_versions", "claims", "claim_items", "claim_status_history", "rule_results", "calculation_lines", "audit_records")}
    pv = before.execute("select policy_id,version,effective_from,snapshot from policy_versions order by id").fetchall()
    hist = before.execute("select claim_id,from_status,to_status from claim_status_history order by id").fetchall()
    claims = before.execute("select claim_number,status,estimated_payable,policy_version_used from claims order by id").fetchall()
    assert "alembic_version" not in {r[0] for r in before.execute("select name from sqlite_master")}
    migrate.upgrade_to_head()
    after = sqlite3.connect(path)
    for t, n in counts.items():
        assert after.execute(f"select count(*) from {t}").fetchone()[0] == n, t
    assert after.execute("select policy_id,version,effective_from,snapshot from policy_versions order by id").fetchall() == pv  # versioning intact
    assert after.execute("select claim_id,from_status,to_status from claim_status_history order by id").fetchall() == hist  # claim history intact
    assert after.execute("select claim_number,status,estimated_payable,policy_version_used from claims order by id").fetchall() == claims
    assert after.execute("select version_num from alembic_version").fetchone()[0] == "0006"
    assert len(list((path.parent / "backups").glob("*pre-migration*.db"))) == 1  # automatic safety copy before altering a populated DB
    assert max(r[0] for r in after.execute("select version from policy_versions where policy_id=1")) == 3  # the re-issue made in v1 survived


def test_legacy_pbkdf2_passwords_still_work_and_upgrade_to_argon2(dbfile, monkeypatch, tmp_path):
    path, eng = dbfile
    shutil.copy(FIXTURE, path)
    migrate.upgrade_to_head()
    from sqlalchemy.orm import sessionmaker
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=eng, autoflush=False, expire_on_commit=False))
    import app.main as main
    monkeypatch.setattr(main, "SessionLocal", database.SessionLocal)
    from app.database import get_db
    def _db():
        s = database.SessionLocal()
        try:
            yield s
        finally:
            s.close()
    app.dependency_overrides[get_db] = _db
    try:
        assert not rows(eng, "select password_hash from users where username='aarav'")[0][0].startswith("$argon2")  # v1 hash is PBKDF2
        c = TestClient(app)
        assert c.post("/api/auth/login", json={"username": "aarav", "password": "student123"}).status_code == 200
        assert rows(eng, "select password_hash from users where username='aarav'")[0][0].startswith("$argon2id$")
        assert c.post("/api/auth/login", json={"username": "aarav", "password": "student123"}).status_code == 200  # still works afterwards
        # original v1 claim still evaluates to the original amount
        a = TestClient(app)
        a.post("/api/auth/login", json={"username": "assessor", "password": "assessor123"})
        csrf = a.get("/api/auth/me").json()["csrf_token"]
        r = a.post("/api/claims/1/evaluate", headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200 and r.json()["estimated_payable"] == 3500.0
    finally:
        app.dependency_overrides.clear()


def test_downgrade_and_reupgrade(dbfile):
    migrate.upgrade_to_head()
    cfg = migrate._config()
    command.downgrade(cfg, "0001")
    assert "payments" not in inspect(dbfile[1]).get_table_names()
    command.upgrade(cfg, "head")
    assert "payments" in inspect(dbfile[1]).get_table_names()


@pytest.fixture()
def fk_dbfile(tmp_path, monkeypatch):
    """Like dbfile, but with PRAGMA foreign_keys=ON on every connection, exactly as the application's own engine has it. Without this the test engine would not
    reproduce the failure a rebuilt `assets` or `claims` table causes on any database that already holds referencing rows."""
    path = tmp_path / "m.db"
    eng = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _fk(dbapi_conn, _rec):
        cur = dbapi_conn.cursor(); cur.execute("PRAGMA foreign_keys=ON"); cur.close()
    monkeypatch.setattr(database, "engine", eng)
    monkeypatch.setattr(migrate, "engine", eng)
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{path.as_posix()}")
    yield path, eng
    eng.dispose()


def test_upgrade_of_a_populated_v3_database_keeps_every_row_and_applies_the_evidence_backfill(fk_dbfile):
    path, eng = fk_dbfile
    shutil.copy(FIXTURE_V3, path)
    with eng.begin() as c:  # make one self-service asset uninsured so both backfill branches are exercised
        c.execute(text("update policies set status='Cancelled' where id = (select max(p.id) from policies p join policy_assets pa on pa.policy_id = p.id join assets a on a.id = pa.asset_id "
                       "where p.status='Active' and a.category_id is not null)"))
    tables = ("users", "assets", "policies", "policy_assets", "claims", "ai_verification_reports")
    before = {t: rows(eng, f"select count(*) from {t}")[0][0] for t in tables}
    insured = {r[0] for r in rows(eng, "select pa.asset_id from policy_assets pa join policies p on p.id = pa.policy_id where p.status='Active' and p.category_id is not null")}
    selfservice = {r[0] for r in rows(eng, "select id from assets where category_id is not null")}
    assert before["claims"] == 5 and before["ai_verification_reports"] == 1 and len(selfservice) >= 3 and (selfservice - insured)
    assert rows(eng, "select version_num from alembic_version") == [("0005",)]

    migrate.upgrade_to_head()  # must not fail on rows that reference assets and claims

    assert rows(eng, "select version_num from alembic_version") == [("0006",)]
    assert {t: rows(eng, f"select count(*) from {t}")[0][0] for t in tables} == before  # nothing lost
    status = dict(rows(eng, "select id, evidence_status from assets where category_id is not null"))
    assert {i for i, st in status.items() if st == "Approved"} == insured and {i for i, st in status.items() if st == "Pending review"} == selfservice - insured
    assert all("Grandfathered" in n for (n,) in rows(eng, "select evidence_review_note from assets where evidence_status='Approved' and category_id is not null"))
    ev = rows(eng, "select asset_id, kind, review_status, sha256 from asset_evidence order by id")
    assert {a for a, *_ in ev} <= selfservice and all(sha == "" for *_, sha in ev)  # fingerprints are filled in lazily
    expect_fronts = {r[0] for r in rows(eng, "select id from assets where category_id is not null and photo_file != ''")}
    assert {a for a, k, *_ in ev if k == "front_photo"} == expect_fronts
    assert all(rs == ("Accepted" if status[a] == "Approved" else "Pending") for a, _k, rs, _sha in ev)
    assert rows(eng, "select count(*) from assets where category_id is null and id in (select asset_id from asset_evidence)")[0][0] == 0  # legacy v2 assets are not touched
    assert rows(eng, "select distinct ai_workflow_outcome from claims") == [("",)] and rows(eng, "select device_match, authenticity, workflow_outcome from ai_verification_reports") == [("{}", "{}", "")]
    assert rows(eng, "pragma integrity_check") == [("ok",)] and rows(eng, "pragma foreign_key_check") == []
    with eng.connect() as c:
        assert compare_metadata(MigrationContext.configure(c), Base.metadata) == []
    assert list((path.parent / "backups").glob("m-pre-migration-*.db"))  # the automatic backup taken before upgrading


def test_a_populated_database_still_works_through_the_application_after_upgrade(fk_dbfile, monkeypatch):
    """The grandfathered, fingerprint-less evidence rows must not break registration, the review queue, claims or the analytics."""
    path, eng = fk_dbfile
    shutil.copy(FIXTURE_V3, path)
    migrate.upgrade_to_head()
    from app import evidence as EV
    from app.models import Asset, AssetEvidence
    from sqlalchemy.orm import Session
    from tests.helpers_v3 import make_img
    with Session(eng) as db:
        settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        stored = [e.stored_name for e in db.query(AssetEvidence)]
        assert stored and all(not e.sha256 for e in db.query(AssetEvidence))
        for i, name in enumerate(stored[:-1]):  # one file is deliberately missing from disk
            (settings.UPLOAD_DIR / name).write_bytes(make_img(2000 + i))
        for a in db.query(Asset).filter(Asset.category_id.isnot(None)):
            items = EV.rows(db, a.id)
            EV.ensure_fingerprints(db, items)  # must process EVERY row of the asset, not stop after the first that changes
            assert EV.summary(db, a, items, staff=True)["status"] in EV.STATUSES and EV.missing_required(items) == ["Back photograph"]
        done = db.query(AssetEvidence).all()
        assert sum(1 for e in done if len(e.sha256) == 64 and e.phash and e.width == 640) == len(stored) - 1
        assert [e.sha256 for e in done if e.stored_name == stored[-1]] == [""]  # a missing file stays unfingerprinted instead of raising
        corp = EV.corpus(db)
        assert all(len(c["sha256"]) == 64 for c in corp) and len(corp) >= 1
