"""Tests for Phase 3 performance profiles + hardware detection."""

import config
from services import system_info


# ── Mode resolution ──────────────────────────────────────────────────

def test_active_mode_default(restore_settings):
    config.save_settings({"mode": "lite"})
    assert config.active_mode() == "lite"


def test_active_mode_validates_unknown(restore_settings):
    # A bogus mode in settings must fall back to the safe default, never crash.
    config.save_settings({"mode": "ludicrous"})
    assert config.active_mode() == "lite"


def test_all_profiles_have_required_fields():
    for name, prof in config.MODE_PROFILES.items():
        for key in ("label", "description", "rerank", "ocr", "upload_concurrency", "embedding"):
            assert key in prof, f"{name} missing {key}"


# ── OCR gating (mirrors rerank's auto/on/off contract) ───────────────

def test_ocr_auto_follows_profile(restore_settings):
    config.save_settings({"ocr": "auto", "mode": "lite"})
    assert config.ocr_enabled() is False          # Lite: OCR off
    config.save_settings({"mode": "balanced"})
    assert config.ocr_enabled() is True           # Balanced: OCR on
    config.save_settings({"mode": "power"})
    assert config.ocr_enabled() is True


def test_ocr_explicit_overrides_profile(restore_settings):
    config.save_settings({"mode": "lite", "ocr": "on"})
    assert config.ocr_enabled() is True           # explicit on beats Lite
    config.save_settings({"mode": "power", "ocr": "off"})
    assert config.ocr_enabled() is False          # explicit off beats Power


# ── Rerank stays consistent with the profile table ───────────────────

def test_rerank_auto_follows_profile(restore_settings):
    config.save_settings({"rerank": "auto", "mode": "lite"})
    assert config.rerank_enabled() is False
    config.save_settings({"mode": "balanced"})
    assert config.rerank_enabled() is True


# ── Upload concurrency scales with the profile ───────────────────────

def test_upload_concurrency_scales(restore_settings):
    config.save_settings({"mode": "lite"})
    lite = config.upload_concurrency()
    config.save_settings({"mode": "power"})
    power = config.upload_concurrency()
    assert lite >= 1 and power > lite


# ── Hardware detection ───────────────────────────────────────────────

def test_detect_system_shape():
    info = system_info.detect_system()
    for key in ("ram_gb", "cpu_count", "gpu", "has_gpu", "suggested_mode",
                "current_mode", "profiles"):
        assert key in info
    assert info["suggested_mode"] in config.MODE_PROFILES
    assert isinstance(info["has_gpu"], bool)


def test_suggest_mode_logic():
    # Weak / unknown machine → Lite; big + GPU → Power; mid → Balanced.
    assert system_info._suggest_mode(None, False) == "lite"
    assert system_info._suggest_mode(8.0, False) == "lite"
    assert system_info._suggest_mode(16.0, False) == "balanced"
    assert system_info._suggest_mode(16.0, True) == "power"
    assert system_info._suggest_mode(8.0, True) == "lite"   # GPU but too little RAM
