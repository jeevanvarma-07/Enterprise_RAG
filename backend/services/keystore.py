"""
Encrypted at-rest store for per-provider API keys.

Keys entered in the app's Settings UI are encrypted with Fernet (AES-128-CBC +
HMAC) and written to the per-user app-data dir — never to the repo, never to a
plaintext `.env`. This is the long-term fix for the secret-handling problem:
the only key material on disk is an opaque ciphertext blob plus a local master
key file, both outside any tracked directory.

Threat model: protects keys from casual disk / backup / repo / screenshot
exposure on a single-user desktop machine. It is *not* a defence against an
attacker who already has read access to the user's home dir (they could read the
master key too) — that would need an OS keyring or a user passphrase, which we
can layer on later behind the same interface.

Graceful degradation: if `cryptography` is not installed (it is an optional dep,
kept out of the very leanest builds), every function no-ops and the app falls
back to reading keys from environment variables. So this module never breaks
startup — it only *adds* the option of in-app keys.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Dict

import config

# ─────────────────────────────────────────────────────────────────────
# Optional dependency: import lazily so a build without `cryptography`
# still boots and simply offers no encrypted store.
# ─────────────────────────────────────────────────────────────────────
try:
    from cryptography.fernet import Fernet, InvalidToken
    _CRYPTO_OK = True
except Exception:  # pragma: no cover - exercised only on lean builds
    Fernet = None  # type: ignore
    InvalidToken = Exception  # type: ignore
    _CRYPTO_OK = False

# File names inside the app-data dir (config.DATA_DIR).
_MASTER_KEY_FILE = "secret.key"     # the Fernet master key (local-only)
_BLOB_FILE = "keys.enc"             # Fernet ciphertext of the {provider: key} map

_lock = threading.Lock()


def available() -> bool:
    """True when an encrypted key store can be used (cryptography present)."""
    return _CRYPTO_OK


# ─────────────────────────────────────────────────────────────────────
# Master key
# ─────────────────────────────────────────────────────────────────────
def _master_key_path():
    return config.DATA_DIR / _MASTER_KEY_FILE


def _blob_path():
    return config.DATA_DIR / _BLOB_FILE


def _load_or_create_master_key() -> bytes:
    """
    Return the Fernet master key, generating and persisting one on first use.
    The file is created with owner-only permissions where the OS supports it.
    """
    config.ensure_dirs()
    path = _master_key_path()
    if path.exists():
        return path.read_bytes()

    key = Fernet.generate_key()
    path.write_bytes(key)
    # Best-effort lock-down (POSIX). On Windows this is a no-op; the file still
    # lives under the per-user app-data dir.
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


def _fernet() -> "Fernet":
    return Fernet(_load_or_create_master_key())


# ─────────────────────────────────────────────────────────────────────
# Read / write the {provider: api_key} map
# ─────────────────────────────────────────────────────────────────────
def _read_all() -> Dict[str, str]:
    """Decrypt and return the full provider→key map ({} if none / unreadable)."""
    if not _CRYPTO_OK:
        return {}
    path = _blob_path()
    if not path.exists():
        return {}
    try:
        raw = _fernet().decrypt(path.read_bytes())
        data = json.loads(raw.decode("utf-8"))
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (InvalidToken, ValueError, OSError):
        # Corrupt blob or master-key mismatch → treat as empty rather than crash.
        return {}


def _write_all(data: Dict[str, str]) -> None:
    """Encrypt and persist the full provider→key map."""
    config.ensure_dirs()
    token = _fernet().encrypt(json.dumps(data).encode("utf-8"))
    path = _blob_path()
    path.write_bytes(token)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────
def get_key(provider: str) -> str:
    """Return the stored key for `provider`, or '' if none / store unavailable."""
    if not _CRYPTO_OK:
        return ""
    with _lock:
        return _read_all().get(provider, "")


def set_key(provider: str, api_key: str) -> bool:
    """
    Store (or replace) the key for `provider`. An empty/whitespace value clears
    it. Returns True on success, False if the encrypted store is unavailable.
    """
    if not _CRYPTO_OK:
        return False
    with _lock:
        data = _read_all()
        api_key = (api_key or "").strip()
        if api_key:
            data[provider] = api_key
        else:
            data.pop(provider, None)
        _write_all(data)
        return True


def delete_key(provider: str) -> bool:
    """Remove any stored key for `provider`. Returns True if the store is usable."""
    if not _CRYPTO_OK:
        return False
    with _lock:
        data = _read_all()
        if provider in data:
            data.pop(provider, None)
            _write_all(data)
        return True


def has_key(provider: str) -> bool:
    """Whether a non-empty key is stored for `provider`."""
    return bool(get_key(provider))


def configured_providers() -> list[str]:
    """Names of providers that currently have a stored key (no values leaked)."""
    if not _CRYPTO_OK:
        return []
    with _lock:
        return [k for k, v in _read_all().items() if v]
