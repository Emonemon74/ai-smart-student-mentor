"""DB pool, schema, audit helper, retention cleanup (LLD C1.3)."""
from __future__ import annotations

import hashlib
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app import config

pool = ConnectionPool(config.DATABASE_URL, kwargs={"row_factory": dict_row}, open=False)
SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"


def init() -> None:
    """Lifespan: open pool, apply schema (idempotent), run retention cleanup."""
    pool.open(wait=True, timeout=15)
    with pool.connection() as conn:
        conn.execute(SCHEMA.read_text())
        cleanup(conn)
        conn.commit()


def close() -> None:
    pool.close()


def get_conn():
    """FastAPI dependency. Rolls back on exception; write endpoints commit explicitly."""
    with pool.connection() as conn:
        yield conn


def audit(conn, actor: str, action: str, target: str | None = None) -> None:
    conn.execute("INSERT INTO audit_log (actor, action, target) VALUES (%s, %s, %s)", (actor, action, target))


def h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def cleanup(conn) -> None:
    """Retention (run at startup and on every login): expired sessions/tokens, audit > 180 days."""
    conn.execute("DELETE FROM sessions WHERE expires_at < now()")
    conn.execute("DELETE FROM share_tokens WHERE expires_at < now()")
    conn.execute("DELETE FROM audit_log WHERE at < now() - interval '180 days'")
