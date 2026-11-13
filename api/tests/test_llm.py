"""LLM gateway tests with fake clients: no network."""
from types import SimpleNamespace

import httpx
import openai
import pytest
from pydantic import BaseModel

from app import config, llm


def reply(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))


class Fake:
    """A fake OpenAI client: each call pops the next scripted outcome (a string or an exception)."""
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return reply(o)


def rate_limit():
    req = httpx.Request("POST", "http://x")
    return openai.RateLimitError("slow down", response=httpx.Response(429, request=req), body=None)


@pytest.fixture
def two(monkeypatch):
    a, b = Fake(), Fake()
    monkeypatch.setattr(config, "PROVIDERS", [config.Provider("one", "u", "k", "m1"), config.Provider("two", "u", "k", "m2")])
    monkeypatch.setattr(llm, "_clients", {"one": a, "two": b})
    return a, b


def test_falls_back_when_first_provider_is_rate_limited(two):
    a, b = two
    a.outcomes, b.outcomes = [rate_limit()], ["hello"]
    assert llm.chat([{"role": "user", "content": "hi"}]) == "hello"
    assert len(a.calls) == 1 and len(b.calls) == 1
    assert "one: RateLimitError" in llm.STATUS["last_error"]


def test_empty_reply_falls_through(two):
    a, b = two
    a.outcomes, b.outcomes = ["   "], ["ok"]
    assert llm.chat([]) == "ok"


def test_all_fail_raises(two):
    a, b = two
    a.outcomes, b.outcomes = [rate_limit()], [rate_limit()]
    with pytest.raises(llm.AIUnavailable):
        llm.chat([])


class Plan(BaseModel):
    n: int


def test_chat_json_parses_json_wrapped_in_prose(two):
    a, _ = two
    a.outcomes = ['Sure! Here you go: {"n": 3} Hope that helps.']
    assert llm.chat_json([], Plan).n == 3


def test_chat_json_retries_once_with_the_error(two):
    a, _ = two
    a.outcomes = ['{"n": "x"}', '{"n": 4}']
    assert llm.chat_json([{"role": "user", "content": "go"}], Plan).n == 4
    retry = a.calls[1]["messages"]
    assert retry[-2]["role"] == "assistant" and "That was invalid" in retry[-1]["content"]


def test_chat_json_runs_the_validator_and_gives_up_after_two(two):
    a, _ = two
    a.outcomes = ['{"n": 1}', '{"n": 1}']

    def must_be_two(o):
        if o.n != 2:
            raise ValueError("n must be 2")

    with pytest.raises(llm.AIUnavailable):
        llm.chat_json([], Plan, validate=must_be_two)
    assert len(a.calls) == 2


def test_transcribe_failure_maps_to_stt_unavailable(monkeypatch):
    monkeypatch.setattr(config, "STT", None)
    with pytest.raises(llm.STTUnavailable):
        llm.transcribe(b"x", "a.webm", "en")
    prov = config.Provider("g", "u", "k", "whisper")
    monkeypatch.setattr(config, "STT", prov)
    bad = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=lambda **kw: (_ for _ in ()).throw(rate_limit()))))
    monkeypatch.setattr(llm, "_clients", {"stt:g": bad})
    with pytest.raises(llm.STTUnavailable):
        llm.transcribe(b"x", "a.webm", "en")
    ok = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=lambda **kw: SimpleNamespace(text=" hi "))))
    monkeypatch.setattr(llm, "_clients", {"stt:g": ok})
    assert llm.transcribe(b"x", "a.webm", "hi") == "hi"


# ---- F5: an empty `choices` list falls through to the next provider (LLD_next C5) ----------------------------
def test_empty_choices_falls_through_to_the_next_provider(two):
    a, b = two
    a._create = lambda **kw: SimpleNamespace(choices=[], usage=None)
    a.chat = SimpleNamespace(completions=SimpleNamespace(create=a._create))
    b.outcomes = ["from two"]
    assert llm.chat([{"role": "user", "content": "hi"}]) == "from two"
    assert len(b.calls) == 1
