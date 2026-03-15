"""
Cryptographic utilities for SciBot user accounts.

Password hashing
----------------
PBKDF2-HMAC-SHA256 with 600 000 iterations and a 16-byte random salt.
Uses two separate salts per user:
  auth_salt  — used only for password verification
  enc_salt   — used only for Fernet key derivation

This separation prevents related-key attacks: even though the same password
is used for both purposes, the distinct salts guarantee independent outputs.

Config encryption
-----------------
Derives a 32-byte Fernet-compatible key from (password, enc_salt) and
encrypts the entire config JSON as one opaque blob — no field is stored
in plaintext.

Usage
-----
    from app.users.crypto import (
        generate_salt,
        hash_password, verify_password,
        derive_fernet_key,
        encrypt_json, decrypt_json,
    )
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

_PBKDF2_ITERATIONS = 600_000


def generate_salt() -> bytes:
    """Return 16 cryptographically random bytes."""
    return os.urandom(16)


def _pbkdf2(password: str, salt: bytes) -> bytes:
    """Return a 32-byte PBKDF2-HMAC-SHA256 derived key."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
        dklen=32,
    )


# ── Password hashing ──────────────────────────────────────────────────────────

def hash_password(password: str, salt: bytes) -> str:
    """Hash *password* with *salt* using PBKDF2-HMAC-SHA256; return a hex digest."""
    return _pbkdf2(password, salt).hex()


def verify_password(password: str, salt_b64: str, stored_hash: str) -> bool:
    """
    Return True iff *password* hashes to *stored_hash* with the given salt.

    Uses ``hmac.compare_digest`` to resist timing attacks.
    """
    salt = base64.b64decode(salt_b64)
    candidate = hash_password(password, salt)
    return hmac.compare_digest(candidate, stored_hash)


# ── Fernet key derivation ─────────────────────────────────────────────────────

def derive_fernet_key(password: str, salt: bytes) -> bytes:
    """
    Derive a Fernet-compatible 32-byte key from *password* and *salt*.

    The raw 32-byte PBKDF2 output is base64-url-encoded as required by
    ``cryptography.fernet.Fernet``.
    """
    raw = _pbkdf2(password, salt)
    return base64.urlsafe_b64encode(raw)


# ── JSON encryption / decryption ──────────────────────────────────────────────

def encrypt_json(data: dict, key: bytes) -> str:
    """Serialise *data* to JSON, Fernet-encrypt it, and return a str token."""
    from cryptography.fernet import Fernet

    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return Fernet(key).encrypt(payload).decode("ascii")


def decrypt_json(token: str, key: bytes) -> dict:
    """Decrypt a Fernet token and parse the JSON payload back to a dict."""
    from cryptography.fernet import Fernet

    payload = Fernet(key).decrypt(token.encode("ascii"))
    return json.loads(payload.decode("utf-8"))
