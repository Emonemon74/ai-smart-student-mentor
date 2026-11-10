def test_healthz(client):
    r = client.get("/api/healthz")
    assert r.status_code == 200 and r.json()["db"] is True
    assert r.headers["cache-control"] == "no-store"


def test_schema_applies_twice(client):
    from app import db
    with db.pool.connection() as conn:
        conn.execute(db.SCHEMA.read_text())  # idempotent
        conn.commit()


def test_openapi_served(client):
    assert client.get("/openapi.json").status_code == 200
