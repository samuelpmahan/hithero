"""BE2-11: password and reset-token hashing (no database needed)."""

from passlib.hash import sha256_crypt

from auth.passwords import hash_password, hash_reset_token, verify_password


def test_argon2_round_trip():
    stored = hash_password("s3cret-pass")
    assert stored.startswith("$argon2id$")
    assert verify_password("s3cret-pass", stored) == (True, None)
    assert verify_password("wrong", stored) == (False, None)


def test_legacy_sha256_crypt_verifies_and_asks_for_upgrade():
    legacy = sha256_crypt.using(rounds=1000).hash("old-pass")
    ok, new_hash = verify_password("old-pass", legacy)
    assert ok and new_hash.startswith("$argon2id$")
    assert verify_password("old-pass", new_hash) == (True, None)
    assert verify_password("wrong", legacy) == (False, None)


def test_missing_or_garbage_hash_is_a_failed_login():
    for stored in (None, "", "not-a-hash", "$argon2id$broken"):
        assert verify_password("anything", stored) == (False, None)


def test_reset_token_hash_is_stable_and_same_length():
    token = "A" * 43
    assert hash_reset_token(token) == hash_reset_token(token)
    assert hash_reset_token(token) != token
    assert len(hash_reset_token(token)) == 43
