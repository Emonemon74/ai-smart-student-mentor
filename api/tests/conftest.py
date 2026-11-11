"""Test harness (LLD C1.6). The LLM is never called in tests: monkeypatch app.llm.chat / chat_json / transcribe."""
import os
from pathlib import Path

import psycopg

# Env must be set BEFORE importing the app.
ADMIN = "postgresql://emon:emon@localhost:5433/postgres"
os.environ["DATABASE_URL"] = "postgresql://emon:emon@localhost:5433/emon_test"
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
os.environ["LLM_PROVIDERS"] = ""

with psycopg.connect(ADMIN, autocommit=True) as _c:
    if not _c.execute("SELECT 1 FROM pg_database WHERE datname='emon_test'").fetchone():
        _c.execute("CREATE DATABASE emon_test")

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
        conn.execute("TRUNCATE sessions, roadmaps, tasks, share_tokens, requests, feedback, audit_log RESTART IDENTITY CASCADE")
        conn.execute("UPDATE students SET failed_attempts=0, locked_until=NULL")
        conn.execute("DELETE FROM assessments WHERE batch='review'")
        conn.execute("DELETE FROM attendance WHERE batch='review'")
        conn.execute("DELETE FROM imports WHERE batch='review'")
        conn.commit()
    client.cookies.clear()
    yield


def login(client, roll_no="CS23001", pin="1234"):
    """Log in and give consent."""
    r = client.post("/api/auth/login", json={"roll_no": roll_no, "pin": pin})
    assert r.status_code == 200, r.text
    assert client.post("/api/consent", json={"notice_version": "v1"}).status_code == 204
    return r
