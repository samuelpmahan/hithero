"""Checks that the deployed site matches this code, without a browser page.

Read-only (GET requests only), so they run against the live site too:
    E2E=1 E2E_BASE_URL=https://www.helpteachers.net pytest tests/e2e

Against the local app they mostly pass by construction; their value is
against a deployment, where they catch drift between the code here and
what is actually running.
"""
import re

import pytest

from tests.e2e.conftest import LOCAL
from tests.testenv import ROOT


def _get(playwright, url, **kwargs):
    ctx = playwright.request.new_context()
    try:
        response = ctx.get(url, **kwargs)
        return response.status, dict(response.headers), response.body()
    finally:
        ctx.dispose()


def _operations(spec: dict) -> set[tuple[str, str]]:
    return {(method.upper(), path) for path, item in spec["paths"].items() for method in item}


def test_deployed_routes_match_the_code(playwright, site_url):
    """The site serves the same API (routes, parameters, bodies) as this code."""
    import json

    import app

    status, _, body = _get(playwright, site_url + "/openapi.json")
    assert status == 200
    deployed, code = json.loads(body), app.app.openapi()
    assert sorted(_operations(deployed) ^ _operations(code)) == [], "routes differ"
    assert deployed == code, "same routes, but parameters, bodies or schemas differ"


@pytest.mark.xfail(
    not LOCAL, strict=False,
    reason="live app is not told it sits behind Azure's HTTPS proxy, so it redirects to http:// (startup command is in Azure, not the repo)",
)
def test_trailing_slash_redirect_keeps_the_scheme(playwright, site_url):
    """/api/get_states redirects to /api/get_states/ on the same scheme.

    An http:// redirect from an https page breaks a fetch() (mixed content)
    and leaks the request over plain http.
    """
    status, headers, _ = _get(playwright, site_url + "/api/get_states", max_redirects=0)
    assert status in (307, 308)
    location = headers["location"]
    assert not location.startswith("http") or location.startswith(site_url.split("://")[0] + "://"), location


def test_static_files_referenced_by_pages_exist(playwright, site_url):
    """Every /static/... path written in a page is served (and exists here)."""
    from tests.e2e.test_pages import KNOWN_ISSUES

    refs = set()
    for page in (ROOT / "pages").glob("*.html"):
        refs |= set(re.findall(r"""["'(](/static/[^"')?#\s]+)""", page.read_text(encoding="utf-8")))
    assert refs
    missing = []
    for ref in sorted(refs):
        status, _, _ = _get(playwright, site_url + ref)
        on_disk = (ROOT / ref.lstrip("/")).is_file()
        if status != 200 or not on_disk:
            if not any(ref in k for k in KNOWN_ISSUES):
                missing.append(f"{ref}: HTTP {status}, on disk: {on_disk}")
    assert missing == []


def test_public_json_endpoints_keep_their_shape(playwright, site_url):
    """The read-only JSON the logged-out pages use has the fields the JS reads."""
    import json

    status, headers, body = _get(playwright, site_url + "/api/get_states/")
    assert status == 200 and headers["content-type"].startswith("application/json")
    states = json.loads(body)
    assert states and all(isinstance(s, str) for s in states)

    status, _, body = _get(playwright, site_url + "/api/random_teacher/")
    assert status == 200
    teacher = json.loads(body)
    assert set(teacher) >= {"name", "state", "county", "district", "school", "image_data"}

    status, _, body = _get(playwright, site_url + "/promo/get_promo_info/")
    assert status == 200
    assert set(json.loads(body)) == {"promo_image_url", "promo_title"}
