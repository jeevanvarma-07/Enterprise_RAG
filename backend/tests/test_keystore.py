"""
Tests for the encrypted in-app API-key store and its integration with
`config.provider_api_key`.

Isolation: conftest points RAG_DATA_DIR at a temp dir, so the keystore reads and
writes its `secret.key` / `keys.enc` there — never the developer's real data dir.
"""

import importlib

import pytest

import config
from services import keystore

# The whole module is meaningless without the optional crypto dependency.
pytestmark = pytest.mark.skipif(
    not keystore.available(), reason="cryptography not installed"
)


@pytest.fixture(autouse=True)
def _clean_store():
    """Start each test from an empty store and clean up after."""
    for name in list(keystore.configured_providers()):
        keystore.delete_key(name)
    yield
    for name in list(keystore.configured_providers()):
        keystore.delete_key(name)


def test_set_get_roundtrip():
    assert keystore.set_key("groq", "gsk_secret_value_123") is True
    assert keystore.get_key("groq") == "gsk_secret_value_123"
    assert keystore.has_key("groq") is True
    assert "groq" in keystore.configured_providers()


def test_value_is_encrypted_on_disk():
    keystore.set_key("groq", "gsk_plaintext_should_not_appear")
    blob = (config.DATA_DIR / "keys.enc").read_bytes()
    # The raw key must not be recoverable from the ciphertext blob.
    assert b"gsk_plaintext_should_not_appear" not in blob


def test_overwrite_and_clear():
    keystore.set_key("groq", "first")
    keystore.set_key("groq", "second")
    assert keystore.get_key("groq") == "second"
    # Empty value clears the key.
    keystore.set_key("groq", "   ")
    assert keystore.get_key("groq") == ""
    assert keystore.has_key("groq") is False


def test_delete_key():
    keystore.set_key("mistral", "abc")
    assert keystore.delete_key("mistral") is True
    assert keystore.get_key("mistral") == ""


def test_unknown_provider_returns_empty():
    assert keystore.get_key("does-not-exist") == ""


def test_stored_key_overrides_env(monkeypatch):
    """provider_api_key prefers the encrypted store over the environment."""
    env_name = config.PROVIDERS["groq"]["api_key_env"]
    monkeypatch.setenv(env_name, "from_env")
    keystore.set_key("groq", "from_store")
    assert config.provider_api_key("groq") == "from_store"


def test_env_fallback_when_no_stored_key(monkeypatch):
    env_name = config.PROVIDERS["groq"]["api_key_env"]
    monkeypatch.setenv(env_name, "from_env_only")
    # no stored key for groq (cleaned by fixture)
    assert config.provider_api_key("groq") == "from_env_only"


def test_provider_is_configured_via_store(monkeypatch):
    env_name = config.PROVIDERS["groq"]["api_key_env"]
    monkeypatch.delenv(env_name, raising=False)
    assert config.provider_is_configured("groq") is False
    keystore.set_key("groq", "some-key")
    assert config.provider_is_configured("groq") is True


def test_persists_across_reimport():
    """A fresh import of the module still reads previously stored keys."""
    keystore.set_key("deepseek", "persisted-value")
    reloaded = importlib.reload(keystore)
    try:
        assert reloaded.get_key("deepseek") == "persisted-value"
    finally:
        reloaded.delete_key("deepseek")
