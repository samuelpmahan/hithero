"""Shared test setup.

app.py reads its settings from environment variables and connects to the
database when it is imported. The defaults below let the tests import it
without a real deployment. Set TEST_DATABASE=1 (see BE1-3) to point the
tests at the local SQL Server container instead.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # app.py mounts "pages" and "static" by relative path

_TEST_ENV = {
    "SECRET_KEY": "test-secret-key",
    "DATABASE_SERVER": "localhost",
    "DATABASE_NAME": "hithero_test",
    "DATABASE_UID": "sa",
    "DATABASE_PASSWORD": "Test_Passw0rd!",
    "DATABASE_PORT": "1433",
    "INTERNAL_JOB_SECRET": "test-job-secret",
    "admin_secret": "test-admin-secret",
}
for key, value in _TEST_ENV.items():
    os.environ.setdefault(key, value)

if os.environ.get("TEST_DATABASE") != "1":
    # No database: stop app.py's import-time create_all from connecting.
    import sqlalchemy.sql.schema

    sqlalchemy.sql.schema.MetaData.create_all = lambda *args, **kwargs: None


def update_golden() -> bool:
    """True when the run should rewrite golden files instead of comparing."""
    return os.environ.get("UPDATE_GOLDEN") == "1"
