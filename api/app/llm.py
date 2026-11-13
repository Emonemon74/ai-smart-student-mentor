"""C5: LLM gateway. The one place that talks to OpenAI-compatible providers, with fallback,
timeouts and metadata-only logging. Never logs message content (LLD C5)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Callable

import openai
from pydantic import BaseModel

from app import config

log = logging.getLogger("emon")
STATUS: dict = {"last_ok": None, "last_error": None}  # read by /api/healthz


class AIUnavailable(Exception):
    """All providers failed, or the model could not produce valid output."""


class STTUnavailable(Exception):
    """Transcription failed."""


_clients: dict[str, openai.OpenAI] = {}


def _client(p: config.Provider, key: str | None = None) -> openai.OpenAI:
    k = key or p.name
    if k not in _clients:
        # max_retries=0: fall through to the next provider immediately instead of retrying a rate-limited one
        _clients[k] = openai.OpenAI(base_url=p.base_url, api_key=p.api_key, timeout=20, max_retries=0)
    return _clients[k]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(level: int, msg: str, **fields) -> None:
    log.log(level, msg, extra={"extra_fields": fields})


def chat(messages: list[dict], *, max_tokens: int = 300, temperature: float = 0.4) -> str:
    for p in config.PROVIDERS:
        start = time.perf_counter()
        try:
            r = _client(p).chat.completions.create(model=p.model, messages=messages, max_tokens=max_tokens, temperature=temperature)
            if not r.choices:                      # F5: a provider that answers with no choices falls through to the next one
                raise ValueError("no choices")
            text = (r.choices[0].message.content or "").strip()
            if not text:
                raise ValueError("empty reply")
            usage = getattr(r, "usage", None)
            _log(logging.INFO, "llm_ok", provider=p.name, model=p.model, ms=round((time.perf_counter() - start) * 1000),
                 prompt_tokens=getattr(usage, "prompt_tokens", None), completion_tokens=getattr(usage, "completion_tokens", None))
            STATUS["last_ok"] = _now()
            return text
        except (openai.APIError, ValueError) as e:  # 429, 5xx, timeout, connection, bad config, empty reply
            config_bug = isinstance(e, openai.APIStatusError) and e.status_code in (401, 404)  # bad key or model id
            _log(logging.ERROR if config_bug else logging.WARNING, "llm_fail", provider=p.name, error=type(e).__name__)
            STATUS["last_error"] = f"{p.name}: {type(e).__name__}"
    raise AIUnavailable


def _extract_json(text: str) -> str:
    i, j = text.find("{"), text.rfind("}")
    if i == -1 or j <= i:
        raise ValueError("no JSON object in reply")
    return text[i : j + 1]


def chat_json(
    messages: list[dict],
    model_cls: type[BaseModel],
    *,
    validate: Callable[[BaseModel], None] | None = None,
    max_tokens: int = 1500,
) -> BaseModel:
    """No response_format (support differs between free providers): the prompt demands JSON only.
    One retry with the error message, then AIUnavailable."""
    msgs = list(messages)
    for attempt in range(2):
        text = chat(msgs, max_tokens=max_tokens, temperature=0.3)
        try:
            obj = model_cls.model_validate_json(_extract_json(text))
            if validate:
                validate(obj)
            return obj
        except ValueError as e:  # includes pydantic.ValidationError
            _log(logging.WARNING, "llm_invalid_output", attempt=attempt + 1, error=type(e).__name__)
            if attempt == 1:
                break
            msgs = msgs + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"That was invalid: {str(e)[:300]}. Return only the corrected JSON."},
            ]
    raise AIUnavailable


def transcribe(audio: bytes, filename: str, lang: str) -> str:
    # ponytail: single STT provider; add a second if Whisper limits bite
    if config.STT is None:
        raise STTUnavailable
    try:
        r = _client(config.STT, key="stt:" + config.STT.name).audio.transcriptions.create(
            model=config.STT.model, file=(filename, audio), language=lang
        )
        text = (r.text or "").strip()
        if not text:
            raise ValueError("empty transcript")
        STATUS["last_ok"] = _now()
        return text
    except Exception as e:  # any error -> the UI asks the student to type instead
        _log(logging.WARNING, "stt_fail", provider=config.STT.name, error=type(e).__name__)
        raise STTUnavailable from e
