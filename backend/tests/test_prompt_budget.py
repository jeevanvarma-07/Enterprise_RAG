"""
Tests for the prompt-size budget — the fix for the 413 "Request too large"
rate-limit error. Two levers:
  - history_turns: trims the conversation re-sent each turn to a sliding window
  - context_chars: caps the retrieved context text per request

config.prompt_budget() resolves + clamps them; RAGPipeline._prepare() applies
them when assembling the LLM messages. All offline (a fake vector manager +
fake LLM), so no network or keys.
"""

from types import SimpleNamespace

import config
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from services.generation import RAGPipeline, SYSTEM_PROMPT


# ─────────────────────────────────────────────────────────────────────
# config.prompt_budget — resolution + clamping
# ─────────────────────────────────────────────────────────────────────
def test_prompt_budget_defaults(restore_settings):
    config.save_settings({"history_turns": 3, "context_chars": 6000})
    b = config.prompt_budget()
    assert b == {"history_turns": 3, "history_messages": 6, "context_chars": 6000}


def test_prompt_budget_clamps_out_of_range(restore_settings):
    config.save_settings({"history_turns": 999, "context_chars": 1})
    b = config.prompt_budget()
    assert b["history_turns"] == 20            # clamped to upper bound
    assert b["history_messages"] == 40
    assert b["context_chars"] == 500           # clamped to lower bound


def test_prompt_budget_zero_history(restore_settings):
    config.save_settings({"history_turns": 0})
    b = config.prompt_budget()
    assert b["history_turns"] == 0 and b["history_messages"] == 0


def test_prompt_budget_handles_garbage(restore_settings):
    config.save_settings({"history_turns": "abc", "context_chars": None})
    b = config.prompt_budget()
    assert b["history_turns"] == 3 and b["context_chars"] == 6000   # fall back to defaults


# ─────────────────────────────────────────────────────────────────────
# _prepare — actually applies the budget when building the prompt
# ─────────────────────────────────────────────────────────────────────
class _FakeRetriever:
    def __init__(self, docs):
        self._docs = docs

    def invoke(self, _q):
        return self._docs


class _FakeVM:
    """Minimal vector-manager stand-in that returns fixed docs."""

    def __init__(self, docs):
        self._docs = docs

    def is_loaded(self):
        return True

    def as_retriever(self, search_kwargs=None):
        return _FakeRetriever(self._docs)

    def bm25_retriever(self, k=8):
        return None


class _FakeLLM:
    def invoke(self, _messages):
        return SimpleNamespace(content="ok")

    # multi-query path: structured output just echoes the original query
    def with_structured_output(self, _schema):
        outer = self

        class _S:
            def invoke(self, _prompt):
                return SimpleNamespace(queries=[])
        return _S()


def _doc(text):
    from langchain_core.documents import Document
    return Document(page_content=text, metadata={"source": "f.txt"})


def _long_history(pairs):
    """`pairs` user/ai exchanges as the API's [{role, content}] dicts."""
    h = []
    for i in range(pairs):
        h.append({"role": "user", "content": f"q{i}"})
        h.append({"role": "ai", "content": f"a{i}"})
    return h


def test_prepare_trims_history_to_window(restore_settings, monkeypatch):
    config.save_settings({"history_turns": 2, "context_chars": 6000})
    monkeypatch.setattr("services.generation.build_chat_model", lambda p, m: _FakeLLM())
    # No exact-match scan noise.
    monkeypatch.setattr("services.generation._scan_uploads_for_exact_match", lambda *a, **k: "")

    p = RAGPipeline(vector_manager=_FakeVM([_doc("some context")]))
    llm, messages, sources, early, fallback, notice = p._prepare(
        "new question", config.DEFAULT_MODEL, "groq", _long_history(10)
    )
    assert early is None
    history = [m for m in messages if isinstance(m, (HumanMessage, AIMessage))]
    # 2 turns = 4 messages kept, plus the current question (HumanMessage).
    kept = [m for m in history if m.content != "new question"]
    assert len(kept) == 4
    assert kept[0].content == "q8" and kept[-1].content == "a9"   # the *last* 2 turns


def test_prepare_caps_context_chars(restore_settings, monkeypatch):
    config.save_settings({"history_turns": 0, "context_chars": 500})
    monkeypatch.setattr("services.generation.build_chat_model", lambda p, m: _FakeLLM())
    monkeypatch.setattr("services.generation._scan_uploads_for_exact_match", lambda *a, **k: "")

    huge = _doc("x" * 5000)
    p = RAGPipeline(vector_manager=_FakeVM([huge]))
    llm, messages, sources, early, fallback, notice = p._prepare(
        "q", config.DEFAULT_MODEL, "groq", []
    )
    system = next(m for m in messages if isinstance(m, SystemMessage))
    # The 5000-char "x" chunk must have been trimmed to the 500-char budget.
    # Subtract the x's the prompt template itself contributes so we measure
    # only the retrieved-context portion the budget actually caps.
    template_xs = SYSTEM_PROMPT.format(context="").count("x")
    assert system.content.count("x") - template_xs <= 500
