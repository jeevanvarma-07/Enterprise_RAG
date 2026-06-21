"""Tests for the config layer: provider registry + rerank gating."""

import config


def test_default_provider_and_model_exist():
    assert config.DEFAULT_PROVIDER in config.PROVIDERS
    model_ids = {m["id"] for m in config.list_models()}
    assert config.DEFAULT_MODEL in model_ids


def test_provider_for_model_resolves_known_and_falls_back():
    assert config.provider_for_model("llama-3.1-8b-instant") == "groq"
    assert config.provider_for_model("does-not-exist") == config.DEFAULT_PROVIDER


def test_local_providers_always_configured():
    # Local providers need no key, so they're always "configured".
    assert config.provider_is_configured("ollama") is True
    assert config.provider_is_configured("llamacpp") is True


def test_list_models_tags_provider_and_availability():
    models = config.list_models()
    assert models
    for m in models:
        assert "provider" in m and "available" in m and "provider_label" in m


def test_rerank_enabled_respects_explicit_on_off(restore_settings):
    config.save_settings({"mode": "lite", "rerank": "on"})
    assert config.rerank_enabled() is True
    config.save_settings({"rerank": "off"})
    assert config.rerank_enabled() is False


def test_rerank_auto_follows_mode(restore_settings):
    config.save_settings({"rerank": "auto", "mode": "lite"})
    assert config.rerank_enabled() is False
    config.save_settings({"mode": "balanced"})
    assert config.rerank_enabled() is True
    config.save_settings({"mode": "power"})
    assert config.rerank_enabled() is True


def test_retrieval_params_defaults_match_settings(restore_settings):
    config.save_settings({})  # nothing custom -> defaults
    rp = config.retrieval_params()
    assert rp["top_k"] == config.DEFAULT_SETTINGS["top_k"]
    assert rp["final_k"] == config.DEFAULT_SETTINGS["final_k"]
    assert set(rp) == {
        "top_k", "fetch_k", "mmr_lambda", "bm25_k", "final_k", "rerank_candidates",
    }


def test_retrieval_params_clamps_out_of_range(restore_settings):
    config.save_settings({"top_k": 999, "fetch_k": -5, "mmr_lambda": 3.0, "bm25_k": 0})
    rp = config.retrieval_params()
    assert rp["top_k"] == 20        # clamped to upper bound
    assert rp["fetch_k"] == 1       # clamped to lower bound
    assert rp["mmr_lambda"] == 1.0  # clamped to upper bound
    assert rp["bm25_k"] == 0        # 0 is valid (disables sparse)


def test_retrieval_params_falls_back_on_garbage(restore_settings):
    config.save_settings({"top_k": "abc", "mmr_lambda": None})
    rp = config.retrieval_params()
    assert rp["top_k"] == config.DEFAULT_SETTINGS["top_k"]
    assert rp["mmr_lambda"] == config.DEFAULT_SETTINGS["mmr_lambda"]
