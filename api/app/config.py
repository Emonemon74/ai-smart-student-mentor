"""Plain module-level config from os.environ (LLD C1.1). No pydantic-settings, no dotenv:
scripts/dev.sh exports api/.env before starting the API; tests set env in conftest first."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str


def _provider(name: str) -> Provider | None:
    n = name.strip().upper()
    key = os.environ.get(f"{n}_API_KEY", "")
    if not key:  # empty key -> skipped
        return None
    return Provider(name.strip().lower(), os.environ.get(f"{n}_BASE_URL", ""), key, os.environ.get(f"{n}_MODEL", ""))


DATABASE_URL: str = os.environ.get("DATABASE_URL", "postgresql://emon:emon@localhost:5433/emon")
PUBLIC_BASE_URL: str = os.environ.get("PUBLIC_BASE_URL", "http://localhost:3000").rstrip("/")
PROVIDERS: list[Provider] = [p for p in (_provider(n) for n in os.environ.get("LLM_PROVIDERS", "").split(",") if n.strip()) if p]

_stt_base = _provider(os.environ.get("STT_PROVIDER", "")) if os.environ.get("STT_PROVIDER") else None
STT: Provider | None = (
    Provider(_stt_base.name, _stt_base.base_url, _stt_base.api_key, os.environ.get("STT_MODEL", "whisper-large-v3"))
    if _stt_base
    else None
)

ADMIN_PASSWORD: str = os.environ.get("ADMIN_PASSWORD", "")
if len(ADMIN_PASSWORD) < 12:
    raise RuntimeError("ADMIN_PASSWORD must be at least 12 characters")
