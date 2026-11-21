"""Load every public page in a real browser and report what goes wrong.

Read-only: these tests only open pages, so they are safe to point at the
live site (see conftest.py). A page fails if it causes an error on this
site's side: a 4xx/5xx response from the site, a JavaScript error, or a
console error. Third-party failures (CDNs, ads, analytics) are collected
but don't fail the test, since they depend on the network the test runs on.

KNOWN_ISSUES lists problems already found and not fixed yet, with the
reason. Remove an entry when its fix lands; the test then guards it.
"""
import pytest

KNOWN_ISSUES = {
    # Every page asks /api/profile/ who is logged in. Logged out, it answers
    # 404, and the app's custom 404 handler turns that into the HTML 404
    # page, so pages that parse the answer as JSON log a SyntaxError.
    "HTTP 404: GET /api/profile/": "logged-out profile check answers 404 (by design today)",
    "Failed to fetch profile. Status: 404": "same logged-out profile check",
    "Auth check error: SyntaxError": "404 handler returns HTML to a JSON call (contact page)",
    "Error checking teacher access: SyntaxError": "404 handler returns HTML to a JSON call (teacher page)",
    # homepage.html line 66 points at /static/images/hero_border.jpg; the
    # file is at /static/images/homepage/hero_border.jpg.
    "HTTP 404: GET /static/images/hero_border.jpg": "wrong path for the promo hero background",
}

PUBLIC_PAGES = [
    "/",
    "/pages/homepage.html",
    "/pages/about.html",
    "/pages/contact.html",
    "/pages/partners.html",
    "/pages/terms_conditions.html",
    "/pages/index.html",
    "/pages/forum.html",
    "/pages/login.html",
    "/pages/register.html",
    "/pages/forgot.html",
    "/pages/reset_password.html",
    "/pages/wishlist_setup.html",
    "/pages/404.html",
    "/pages/403.html",
    "/ads.txt",
    "/sitemap.xml",
]


@pytest.mark.parametrize("path", PUBLIC_PAGES)
def test_public_page_loads_cleanly(page, issues, site_url, path):
    response = page.goto(site_url + path, wait_until="networkidle")
    assert response is not None and response.status < 400, f"{path} answered {response and response.status}"
    assert issues.unexpected(list(KNOWN_ISSUES)) == [], f"Problems on {path}"


def test_every_page_file_is_covered():
    """New files in pages/ should be added here or to the logged-in tests."""
    from tests.testenv import ROOT

    logged_in = {"admin.html", "create.html", "create_post.html", "edit_teacher.html",
                 "update_password.html", "validation.html", "post.html", "teacher.html"}
    covered = {p.rsplit("/", 1)[1] for p in PUBLIC_PAGES if p.startswith("/pages/")} | logged_in
    files = {p.name for p in (ROOT / "pages").glob("*.html")}
    assert files - covered == set()
