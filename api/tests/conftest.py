"""Test harness (LLD C1.6). The LLM is never called in tests: monkeypatch app.llm.chat / chat_json / transcribe."""
import os
from pathlib import Path

import psycopg

# Env must be set BEFORE importing the app.
ADMIN = "postgresql://emon:emon@localhost:5433/postgres"
os.environ["DATABASE_URL"] = "postgresql://emon:emon@localhost:5433/emon_test"
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
os.environ["LLM_PROVIDERS"] = ""

os.environ.setdefault("COUNSELLOR_PASSWORD", "test-counsellor-password")
with psycopg.connect(ADMIN, autocommit=True) as _c:
    if not _c.execute("SELECT 1 FROM pg_database WHERE datname='emon_test'").fetchone():
        _c.execute("CREATE DATABASE emon_test")
with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as _c:     # the test DB always starts from the current schema
    _c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402

SEED = Path(__file__).resolve().parent.parent / "seed"


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        if (SEED / "students.csv").exists():  # baseline imported once: PIN hashing is deliberately slow
            from app import connector
            with db.pool.connection() as conn:
                connector.import_csv(conn, SEED, "baseline", shift_days=connector.seed_shift_days())
        yield c


@pytest.fixture(autouse=True)
def _reset(client):
    with db.pool.connection() as conn:
        conn.execute("TRUNCATE sessions, roadmaps, tasks, share_tokens, requests, feedback, audit_log, diagnostics, reviews RESTART IDENTITY CASCADE")
        conn.execute("UPDATE students SET failed_attempts=0, locked_until=NULL")
        conn.execute("DELETE FROM assessments WHERE batch='review'")
        conn.execute("DELETE FROM attendance WHERE batch='review'")
        conn.execute("DELETE FROM backlogs WHERE batch='review'")
        conn.execute("DELETE FROM imports WHERE batch='review'")
        conn.commit()
    client.cookies.clear()
    yield


def login(client, roll_no="CS23001", pin="1234", scope="personal"):
    """Log in and give consent (scope: personal records or general guidance)."""
    r = client.post("/api/auth/login", json={"roll_no": roll_no, "pin": pin})
    assert r.status_code == 200, r.text
    assert client.post("/api/consent", json={"notice_version": "v2", "scope": scope}).status_code == 204
    return r


def take_check(client, subject, topic, correct=5, purpose="level", roadmap_id=None):
    """Start and submit a concept check, answering `correct` questions correctly (in tier order), using the DB keys."""
    body = {"subject_code": subject, "topic": topic, "purpose": purpose}
    if roadmap_id:
        body["roadmap_id"] = roadmap_id
    r = client.post("/api/diagnostics", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    with db.pool.connection() as conn:
        keys = {x["id"]: x["answer"] for x in conn.execute("SELECT id, answer FROM questions WHERE id = ANY(%s)", ([q["id"] for q in d["questions"]],)).fetchall()}
    answers = [keys[q["id"]] if i < correct else (keys[q["id"]] + 1) % 4 for i, q in enumerate(d["questions"])]
    res = client.post(f"/api/diagnostics/{d['id']}/submit", json={"answers": answers})
    assert res.status_code == 200, res.text
    return res.json()
