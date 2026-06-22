"""
Tests for graceful provider fallback (Phase 1).

All offline: the LLM factory is monkeypatched with fake chat models, so we
exercise the build-time and runtime fallback logic without any network or keys.
"""

from types import SimpleNamespace

import pytest

import config
from services.providers import fallback_candidates
from services.generation import RAGPipeline


# ─────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────
class _FakeLLM:
    """Minimal stand-in for a LangChain chat model."""

    def __init__(self, text="ok", *, invoke_fails=False, stream_tokens=None,
                 stream_fails_before=False, stream_fails_mid=False):
        self.text = text
        self.invoke_fails = invoke_fails
        self.stream_tokens = stream_tokens if stream_tokens is not None else ["he", "llo"]
        self.stream_fails_before = stream_fails_before
        self.stream_fails_mid = stream_fails_mid

    def invoke(self, _messages):
        if self.invoke_fails:
            raise RuntimeError("rate limit")
        return SimpleNamespace(content=self.text)

    def stream(self, _messages):
        fails_before, fails_mid = self.stream_fails_before, self.stream_fails_mid
        tokens, txt = self.stream_tokens, self.text

        def _gen():
            if fails_before:
                raise RuntimeError("connection refused")
            for t in tokens:
                yield SimpleNamespace(content=t)
            if fails_mid:
                raise RuntimeError("dropped mid-stream")

        gen = _gen()
        # Surface a "before first token" failure when .stream() is first iterated,
        # matching how auth/rate-limit errors typically present.
        return gen


def _pipeline():
    return RAGPipeline(vector_manager=None)


def _only_keys(monkeypatch, present):
    """Make exactly `present` remote providers look configured (via env keys)."""
    for name, cfg in config.PROVIDERS.items():
        env = cfg.get("api_key_env")
        if not env:
            continue
        if name in present:
            monkeypatch.setenv(env, "test-key")
        else:
            monkeypatch.delenv(env, raising=False)


# ─────────────────────────────────────────────────────────────────────
# fallback_candidates
# ─────────────────────────────────────────────────────────────────────
def test_candidates_requested_first_then_configured(monkeypatch):
    _only_keys(monkeypatch, {"groq", "google"})
    cands = fallback_candidates("groq", "llama-3.1-8b-instant")
    assert cands[0] == ("groq", "llama-3.1-8b-instant")
    assert ("google", "gemini-2.0-flash") in cands
    # An unconfigured provider must not appear as a fallback target.
    assert all(p != "deepseek" for p, _ in cands)


def test_candidates_single_when_no_other_configured(monkeypatch):
    _only_keys(monkeypatch, {"groq"})
    cands = fallback_candidates("groq", "llama-3.1-8b-instant")
    assert cands == [("groq", "llama-3.1-8b-instant")]


def test_candidates_resolve_provider_from_model(monkeypatch):
    _only_keys(monkeypatch, set())
    # provider=None -> resolved from the model id's owning provider.
    cands = fallback_candidates(None, "llama-3.1-8b-instant")
    assert cands[0] == ("groq", "llama-3.1-8b-instant")


# ─────────────────────────────────────────────────────────────────────
# _build_first_working
# ─────────────────────────────────────────────────────────────────────
def test_build_first_working_skips_unbuildable(monkeypatch):
    def fake_build(provider, model):
        if provider == "groq":
            raise ValueError("No Groq API key configured.")
        return _FakeLLM("from google")

    monkeypatch.setattr("services.generation.build_chat_model", fake_build)
    p = _pipeline()
    cands = [("groq", "llama-3.1-8b-instant"), ("google", "gemini-2.0-flash")]
    llm, prov, model, remaining, errors = p._build_first_working(cands)
    assert prov == "google" and llm is not None
    assert remaining == []          # google was last
    assert len(errors) == 1 and "Groq" in errors[0]


def test_format_build_error_single_preserves_message():
    p = _pipeline()
    msg = p._format_build_error(["Groq · llama-3.1-8b-instant: No Groq API key configured."])
    assert msg == "No Groq API key configured."


def test_format_build_error_multi_lists_all():
    p = _pipeline()
    msg = p._format_build_error(["Groq · m: no key", "Google Gemini · g: no key"])
    assert "Groq" in msg and "Google Gemini" in msg and "Settings" in msg


# ─────────────────────────────────────────────────────────────────────
# _invoke_with_fallback  (non-streaming)
# ─────────────────────────────────────────────────────────────────────
def test_invoke_no_fallback_when_primary_succeeds():
    p = _pipeline()
    answer, notice = p._invoke_with_fallback(_FakeLLM("primary"), [], fallback=[])
    assert answer == "primary" and notice == ""


def test_invoke_falls_back_to_second(monkeypatch):
    monkeypatch.setattr("services.generation.build_chat_model",
                        lambda prov, model: _FakeLLM("from fallback"))
    p = _pipeline()
    primary = _FakeLLM(invoke_fails=True)
    answer, notice = p._invoke_with_fallback(
        primary, [], fallback=[("google", "gemini-2.0-flash")]
    )
    assert answer == "from fallback"
    assert "Google Gemini" in notice


def test_invoke_raises_when_all_fail(monkeypatch):
    monkeypatch.setattr("services.generation.build_chat_model",
                        lambda prov, model: _FakeLLM(invoke_fails=True))
    p = _pipeline()
    primary = _FakeLLM(invoke_fails=True)
    with pytest.raises(ValueError) as exc:
        p._invoke_with_fallback(primary, [], fallback=[("google", "gemini-2.0-flash")])
    assert "no fallback provider succeeded" in str(exc.value)


# ─────────────────────────────────────────────────────────────────────
# _stream_with_fallback  (streaming)
# ─────────────────────────────────────────────────────────────────────
def _types(events):
    return [e["type"] for e in events]


def test_stream_emits_build_notice_then_tokens():
    p = _pipeline()
    events = list(p._stream_with_fallback(
        _FakeLLM(stream_tokens=["x", "y"]), [], fallback=[], build_notice="heads up"
    ))
    assert events[0] == {"type": "notice", "content": "heads up"}
    assert _types(events)[-1] == "done"
    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert tokens == "xy"


def test_stream_no_notice_when_no_fallback():
    p = _pipeline()
    events = list(p._stream_with_fallback(
        _FakeLLM(stream_tokens=["a"]), [], fallback=[], build_notice=""
    ))
    assert "notice" not in _types(events)
    assert _types(events)[-1] == "done"


def test_stream_falls_back_before_first_token(monkeypatch):
    monkeypatch.setattr("services.generation.build_chat_model",
                        lambda prov, model: _FakeLLM(stream_tokens=["ok"]))
    p = _pipeline()
    primary = _FakeLLM(stream_fails_before=True)
    events = list(p._stream_with_fallback(
        primary, [], fallback=[("google", "gemini-2.0-flash")], build_notice=""
    ))
    assert "notice" in _types(events)               # runtime switch announced
    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert tokens == "ok"
    assert _types(events)[-1] == "done"


def test_stream_all_fail_emits_error():
    p = _pipeline()
    primary = _FakeLLM(stream_fails_before=True)
    events = list(p._stream_with_fallback(primary, [], fallback=[], build_notice=""))
    assert _types(events) == ["error"]
    assert "no fallback provider succeeded" in events[0]["detail"]


def test_stream_mid_failure_surfaces_error():
    p = _pipeline()
    primary = _FakeLLM(stream_tokens=["a", "b"], stream_fails_mid=True)
    events = list(p._stream_with_fallback(primary, [], fallback=[], build_notice=""))
    # Tokens already flowed, then a mid-stream error event (no clean retry).
    assert "error" in _types(events)
    assert "token" in _types(events)


# ─────────────────────────────────────────────────────────────────────
# config.fallback_enabled
# ─────────────────────────────────────────────────────────────────────
def test_fallback_enabled_default_true(restore_settings):
    config.save_settings({"llm_fallback": True})
    assert config.fallback_enabled() is True


def test_fallback_can_be_disabled(restore_settings):
    config.save_settings({"llm_fallback": False})
    assert config.fallback_enabled() is False
