"""BE2-3: settings load once and fail early."""
import os
import subprocess
import sys

from tests.testenv import ROOT


def test_missing_secret_key_fails_at_startup_and_names_it():
    env = {k: v for k, v in os.environ.items() if k.upper() != "SECRET_KEY"}
    result = subprocess.run(
        [sys.executable, "-c", "import config"],
        cwd=ROOT / "tests",  # no .env file here
        env={**env, "PYTHONPATH": str(ROOT)},
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "secret_key" in result.stderr.lower()


def test_os_getenv_only_in_config():
    offenders = [
        p.name for p in ROOT.glob("*.py")
        if p.name != "config.py" and "os.getenv" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []
