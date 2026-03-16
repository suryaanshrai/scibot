"""
User management for SciBot.

Public API
----------
create_user(username, password)                          -> None
authenticate(username, password)                         -> bytes  (Fernet key)
delete_user(username, password)                          -> None
list_users()                                             -> list[str]
update_password(username, old_password, new_password)    -> None

AuthError
    Raised when credentials are invalid (wrong username or wrong password).
    The error message is intentionally generic to prevent user enumeration.

Username rules
--------------
  - 3–64 characters
  - Letters, digits, underscores, and hyphens only  (a-z A-Z 0-9 _ -)
  - Must be unique (case-sensitive)
"""

from __future__ import annotations

import base64
import re

from app.users.crypto import (
    derive_fernet_key,
    encrypt_json,
    generate_salt,
    hash_password,
    verify_password,
)
from app.users.database import get_connection

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\-]{3,64}$")


class AuthError(Exception):
    """Raised when authentication fails."""


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_username(username: str) -> None:
    if not _USERNAME_RE.match(username):
        raise ValueError(
            "Username must be 3–64 characters and contain only "
            "letters, digits, underscores, or hyphens."
        )


# ── Public API ────────────────────────────────────────────────────────────────

def create_user(username: str, password: str) -> None:
    """
    Create a new user account with the given *username* and *password*.

    Raises
    ------
    ValueError
        If the username is malformed, the password is empty, or the username
        already exists.
    """
    _validate_username(username)
    if not password:
        raise ValueError("Password must not be empty.")

    auth_salt = generate_salt()
    enc_salt = generate_salt()
    pw_hash = hash_password(password, auth_salt)
    fernet_key = derive_fernet_key(password, enc_salt)

    # Initialise an empty encrypted config blob for this user.
    config_enc = encrypt_json({}, fernet_key)

    auth_salt_b64 = base64.b64encode(auth_salt).decode("ascii")
    enc_salt_b64 = base64.b64encode(enc_salt).decode("ascii")

    with get_connection() as conn:
        try:
            conn.execute(
                """
                INSERT INTO users (username, password_hash, auth_salt, enc_salt, config_encrypted)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, pw_hash, auth_salt_b64, enc_salt_b64, config_enc),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError(f"Username {username!r} is already taken.") from exc
            raise


def authenticate(username: str, password: str) -> bytes:
    """
    Verify *username* / *password* and return the user's Fernet encryption key.

    The returned key is required to encrypt or decrypt the user's config JSON.

    Raises
    ------
    AuthError
        If the username does not exist or the password is incorrect.
        The message is kept generic to prevent user-enumeration attacks.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT password_hash, auth_salt, enc_salt FROM users WHERE username = ?",
            (username,),
        ).fetchone()

    if row is None or not verify_password(password, row["auth_salt"], row["password_hash"]):
        raise AuthError("Invalid username or password.")

    enc_salt = base64.b64decode(row["enc_salt"])
    return derive_fernet_key(password, enc_salt)


def delete_user(username: str, password: str) -> None:
    """
    Delete a user account (and all their collections via FK cascade).

    Raises
    ------
    AuthError   If credentials are invalid.
    """
    authenticate(username, password)  # raises AuthError on failure
    with get_connection() as conn:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))


def list_users() -> list[str]:
    """Return all usernames sorted alphabetically."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT username FROM users ORDER BY username"
        ).fetchall()
    return [row["username"] for row in rows]


def update_password(username: str, old_password: str, new_password: str) -> None:
    """
    Change a user's password.

    The existing encrypted config is decrypted with the old Fernet key and
    re-encrypted under the new key.  New salts are generated for both
    authentication and encryption, making old tokens/hashes invalid.

    Raises
    ------
    AuthError   If *old_password* is incorrect.
    ValueError  If *new_password* is empty.
    """
    if not new_password:
        raise ValueError("New password must not be empty.")

    old_key = authenticate(username, old_password)  # raises AuthError on failure

    # Load existing encrypted config.
    with get_connection() as conn:
        row = conn.execute(
            "SELECT config_encrypted FROM users WHERE username = ?",
            (username,),
        ).fetchone()

    from app.users.crypto import decrypt_json

    config = decrypt_json(row["config_encrypted"], old_key)

    # Re-derive everything under the new password.
    new_auth_salt = generate_salt()
    new_enc_salt = generate_salt()
    new_pw_hash = hash_password(new_password, new_auth_salt)
    new_fernet_key = derive_fernet_key(new_password, new_enc_salt)
    new_config_enc = encrypt_json(config, new_fernet_key)

    new_auth_salt_b64 = base64.b64encode(new_auth_salt).decode("ascii")
    new_enc_salt_b64 = base64.b64encode(new_enc_salt).decode("ascii")

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE users
            SET    password_hash = ?,
                   auth_salt     = ?,
                   enc_salt      = ?,
                   config_encrypted = ?
            WHERE  username = ?
            """,
            (new_pw_hash, new_auth_salt_b64, new_enc_salt_b64, new_config_enc, username),
        )

    from app.users.config import _invalidate_user_config_cache

    _invalidate_user_config_cache(username)


def update_username(username: str, password: str, new_username: str) -> None:
    """
    Rename a user account.

    Raises
    ------
    AuthError   If *password* is incorrect.
    ValueError  If *new_username* is malformed or already taken.
    """
    _validate_username(new_username)
    authenticate(username, password)  # raises AuthError on failure
    with get_connection() as conn:
        try:
            conn.execute(
                "UPDATE users SET username = ? WHERE username = ?",
                (new_username, username),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError(f"Username {new_username!r} is already taken.") from exc
            raise

    from app.users.config import _invalidate_user_config_cache

    _invalidate_user_config_cache(username)
