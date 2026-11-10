"""App, router wiring, request logging, health (LLD C1.4)."""
from __future__ import annotations

import json
import logging
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app import admin, analytics, auth, config, db, llm, mentor, phone, report, roadmap


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {"ts": self.formatTime(record), "level": record.levelname, "msg": record.getMessage()}
        data.update(getattr(record, "extra_fields", {}))
        return json.dumps(data)


log = logging.getLogger("emon")
if not log.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False

TOKEN_PATH = re.compile(r"^/api/r/[^/]+")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    yield
    db.close()


app = FastAPI(title="AI Smart Student Mentor", lifespan=lifespan)

for module in (auth, analytics, mentor, roadmap, phone, report, admin):
    app.include_router(module.router)


@app.middleware("http")
async def no_store_and_log(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    path = TOKEN_PATH.sub("/api/r/:token", request.url.path)  # never log share tokens
    log.info("request", extra={"extra_fields": {
        "method": request.method, "path": path, "status": response.status_code,
        "latency_ms": round((time.perf_counter() - start) * 1000)}})
    return response


@app.get("/api/healthz")
def healthz():
    try:
        with db.pool.connection() as conn:
            conn.execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False
    return {"db": db_ok, "llm": dict(llm.STATUS), "providers": [p.name for p in config.PROVIDERS]}
