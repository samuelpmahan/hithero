"""Browser tests (Playwright).

Off by default. Run against the local app and test database with:
    scripts/test_db.sh
    E2E=1 pytest tests/e2e

Run the read-only checks against another deployment (for example the live
site) with:
    E2E=1 E2E_BASE_URL=https://www.helpteachers.net pytest tests/e2e

Against anything but the local app, tests marked local_only are skipped:
they log in or rely on the seeded data. The remaining tests only load
pages and read; they never submit a form or write anything.

Needs: pip install pytest-playwright && playwright install chromium
(or set PLAYWRIGHT_CHROMIUM_EXECUTABLE to an installed Chromium).
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlparse

import pytest

from tests.testenv import ROOT

ENABLED = os.environ.get("E2E") == "1"
EXTERNAL_URL = os.environ.get("E2E_BASE_URL", "").rstrip("/")
LOCAL = not EXTERNAL_URL


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "tests/e2e" not in str(item.fspath).replace(os.sep, "/"):
            continue
        if not ENABLED:
            item.add_marker(pytest.mark.skip(reason="browser tests: set E2E=1"))
        elif not LOCAL and item.get_closest_marker("local_only"):
            item.add_marker(pytest.mark.skip(reason="local_only: needs the local app and seed data"))


def pytest_configure(config):
    config.addinivalue_line("markers", "local_only: needs the local app and seeded test database")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def site_url():
    if EXTERNAL_URL:
        yield EXTERNAL_URL
        return
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.e2e.serve", str(port)],
        cwd=ROOT, env={**os.environ, "TEST_DATABASE": "1"},
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/api/get_states/", timeout=1)
            break
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError("local app failed to start")
            time.sleep(0.2)
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    return {**browser_type_launch_args, **({"executable_path": exe} if exe else {})}


@dataclass
class Issues:
    """Problems seen while a page ran, split by origin."""

    origin: str
    own: list[str] = field(default_factory=list)          # this site
    third_party: list[str] = field(default_factory=list)  # CDNs, ads, analytics
    dialogs: list[str] = field(default_factory=list)      # alert() texts

    def _add(self, url: str, text: str) -> None:
        same = not url or urlparse(url).netloc == urlparse(self.origin).netloc
        (self.own if same else self.third_party).append(text)

    def unexpected(self, known: list[str]) -> list[str]:
        return [i for i in self.own if not any(k in i for k in known)]


@pytest.fixture
def issues(page, site_url) -> Issues:
    found = Issues(origin=site_url)

    def on_console(msg):
        if msg.type == "error":
            url = (msg.location or {}).get("url", "")
            # Chromium logs every failed resource load; the response and
            # requestfailed handlers below report those with their URL.
            if not msg.text.startswith("Failed to load resource"):
                found._add(url, f"console error: {msg.text[:200]}")

    def on_dialog(dialog):
        found.dialogs.append(dialog.message)
        dialog.accept()

    page.on("console", on_console)
    page.on("pageerror", lambda err: found.own.append(f"page error: {str(err)[:200]}"))
    page.on("requestfailed", lambda r: found._add(r.url, f"request failed: {r.method} {_path(r.url, site_url)} {r.failure}"))
    page.on("response", lambda r: found._add(r.url, f"HTTP {r.status}: {r.request.method} {_path(r.url, site_url)}") if r.status >= 400 else None)
    page.on("dialog", on_dialog)
    return found


def _path(url: str, site_url: str) -> str:
    return url[len(site_url):] if url.startswith(site_url) else url
