"""Password hashing and password-reset token hashing.

New passwords are hashed with argon2id (argon2-cffi). Accounts created
before this change still hold sha256_crypt hashes; those are checked with
passlib and replaced by an argon2 hash the next time the person logs in,
so nobody has to reset their password. passlib is only used for that
legacy check and can be dropped once no sha256_crypt hashes remain.

Reset tokens are mailed to the user as-is but stored only as a SHA-256
digest, so someone who can read the table cannot use an open token.
"""

import base64
import hashlib

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from passlib.hash import sha256_crypt

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored: str | None) -> tuple[bool, str | None]:
    """Check a password against a stored hash.

    Returns (ok, new_hash). new_hash is set when the password is right but
    the stored hash is a legacy sha256_crypt one or uses old argon2
    settings; the caller should save it.
    """
    if not stored:
        return False, None
    if stored.startswith("$argon2"):
        try:
            _hasher.verify(stored, password)
        except (VerificationError, InvalidHashError):
            return False, None
        return True, (hash_password(password) if _hasher.check_needs_rehash(stored) else None)
    try:
        ok = sha256_crypt.verify(password, stored)
    except ValueError:
        return False, None
    return ok, (hash_password(password) if ok else None)


def hash_reset_token(token: str) -> str:
    """SHA-256 of the token, URL-safe base64 without padding.

    43 characters, the same length as the secrets.token_urlsafe(32) tokens
    the table held before, so the column needs no change.
    """
    digest = hashlib.sha256(token.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
