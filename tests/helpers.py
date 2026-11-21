"""Helpers for tests that call the app.

Sessions are signed cookies (Starlette SessionMiddleware). Tests build a
logged-in session directly instead of calling /profile/login/, which is
rate limited to 5 a minute.
"""
import base64
import json
import os

import itsdangerous
import pytest
from fastapi.testclient import TestClient

from tests import testenv

requires_db = pytest.mark.skipif(
    not testenv.use_database(),
    reason="needs the test database: run scripts/test_db.sh, then TEST_DATABASE=1 pytest",
)

# Seeded users (see tests/seed.py). Ids follow insert order.
ADMIN = {"user_id": 1, "user_email": "admin@example.com", "user_role": "admin"}
ALICE = {"user_id": 2, "user_email": "alice@example.com", "user_role": "teacher"}
BOB = {"user_id": 3, "user_email": "bob@example.com", "user_role": "teacher"}
CAROL = {"user_id": 4, "user_email": "carol@example.com", "user_role": "teacher"}

# Session keys the teacher pages use to know which teacher is shown.
ALICE_PAGE = {"state": "Illinois", "county": "Sangamon",
              "district": "Springfield District", "school": "Lincoln Elementary",
              "teacher": "Alice Adams"}
BOB_PAGE = {**ALICE_PAGE, "teacher": "Bob Brown"}


def _signer() -> itsdangerous.TimestampSigner:
    return itsdangerous.TimestampSigner(os.environ["SECRET_KEY"])


def encode_session(data: dict) -> str:
    payload = base64.b64encode(json.dumps(data).encode("utf-8"))
    return _signer().sign(payload).decode("utf-8")


def decode_session(cookie: str | None) -> dict:
    if not cookie:
        return {}
    payload = _signer().unsign(cookie)
    return json.loads(base64.b64decode(payload))


def client(session: dict | None = None) -> TestClient:
    import app as app_module

    c = TestClient(app_module.app, base_url="https://testserver", follow_redirects=False)
    if session:
        c.cookies.set("session", encode_session(session), domain="testserver.local")
    return c


def session_of(c: TestClient) -> dict:
    return decode_session(c.cookies.get("session"))
