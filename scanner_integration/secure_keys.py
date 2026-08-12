# -*- coding: utf-8 -*-
"""API key encryption and opaque identifier helpers.

API keys are encrypted before they enter ``config_data``.  The public API uses
an HMAC-derived identifier so callers never need to send a secret back to the
server when updating or deleting it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # Keep non-key scanner paths usable in partial dev envs.
    Fernet = None
    InvalidToken = ValueError

CRYPTO_AVAILABLE = Fernet is not None


TOKEN_PREFIX = "enc:v1:"
KEY_ID_PREFIX = "kid_"
MIN_SECRET_BYTES = 32
MAX_API_KEY_LENGTH = 4096
_LEGACY_KEY_ID_SECRET = secrets.token_bytes(32)


class SecretConfigurationError(RuntimeError):
    """Raised when encryption is required but ``IPTV_SECRET_KEY`` is unsafe."""


def _secret_bytes(required: bool = True) -> bytes:
    value = os.environ.get("IPTV_SECRET_KEY", "")
    raw = value.encode("utf-8")
    if len(raw) < MIN_SECRET_BYTES:
        if not required:
            return b""
        raise SecretConfigurationError(
            "IPTV_SECRET_KEY must contain at least 32 UTF-8 bytes"
        )
    return raw


def secret_is_configured() -> bool:
    """Return whether a sufficiently strong application secret is configured."""
    return bool(_secret_bytes(required=False))


def _fernet():
    if Fernet is None:
        raise SecretConfigurationError(
            "cryptography is required to store API keys; install project dependencies"
        )
    derived = hashlib.sha256(b"iptv-api-key-fernet-v1\0" + _secret_bytes()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def is_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith(TOKEN_PREFIX)


def encrypt_api_key(value: str) -> str:
    """Encrypt one API key using the deployment application secret."""
    key = (value or "").strip()
    if not key:
        return ""
    if len(key) > MAX_API_KEY_LENGTH:
        raise ValueError("API key exceeds the 4096 character limit")
    if is_encrypted(key):
        return key
    token = _fernet().encrypt(key.encode("utf-8")).decode("ascii")
    return TOKEN_PREFIX + token


def decrypt_api_key(value: str) -> str:
    """Decrypt a stored API key, while accepting legacy plaintext for migration."""
    key = (value or "").strip()
    if not key or not is_encrypted(key):
        return key
    try:
        return _fernet().decrypt(key[len(TOKEN_PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        raise SecretConfigurationError(
            "API key ciphertext cannot be decrypted with IPTV_SECRET_KEY"
        ) from exc


def key_id(platform: str, value: str) -> str:
    """Return a stable, non-reversible identifier for a platform API key."""
    platform_name = (platform or "").strip().lower()
    key = (value or "").strip()
    if not platform_name or not key:
        raise ValueError("platform and API key are required")
    secret = _secret_bytes(required=False)
    if not secret:
        # Compatibility mode for 1.x deployments that have not created an
        # IPTV_SECRET_KEY yet. Use a process-local HMAC so the UI can manage
        # legacy plaintext keys without exposing a stable cross-deployment
        # fingerprint. IDs intentionally change after restart or migration.
        secret = _LEGACY_KEY_ID_SECRET
        domain = b"iptv-api-key-id-legacy-v1\0"
    else:
        domain = b"iptv-api-key-id-v1\0"
    digest = hmac.new(
        secret,
        domain + platform_name.encode("utf-8") + b"\0" + key.encode("utf-8"),
        hashlib.sha256,
    ).digest()[:18]
    return KEY_ID_PREFIX + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def key_suffix(value: str) -> str:
    """Return only the last six characters for display."""
    return (value or "")[-6:]


def find_key_by_id(platform: str, keys: list[str], requested_id: str):
    """Resolve an opaque identifier to ``(index, value)`` using constant-time compare."""
    wanted = (requested_id or "").strip()
    if not wanted:
        return None
    for index, value in enumerate(keys or []):
        if hmac.compare_digest(key_id(platform, value), wanted):
            return index, value
    return None
