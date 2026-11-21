"""Main journeys through the real pages, against the local app.

These log in and rely on the seeded data (tests/seed.py), so they only run
against the local app. Pages use Tailwind from a CDN; where that can't
load, elements marked "hidden" still show, so checks look at content and
classes rather than visibility.
"""
import re

import pytest

from tests.e2e.test_pages import KNOWN_ISSUES
from tests.seed import SEED_PASSWORD

pytestmark = pytest.mark.local_only
KNOWN = list(KNOWN_ISSUES)


def login(page, site_url, email):
    page.goto(site_url + "/pages/login.html", wait_until="networkidle")
    page.fill("#email", email)
    page.fill("#password", SEED_PASSWORD)
    with page.expect_navigation(wait_until="networkidle"):
        page.click("#submitButton")


def test_homepage_shows_teacher_of_the_day(page, issues, site_url):
    page.goto(site_url + "/pages/homepage.html", wait_until="networkidle")
    page.wait_for_function("!document.querySelector('#teacherDay').innerText.includes('Loading')")
    page.get_by_text("Find Random Teacher").click()
    page.wait_for_selector("#randomTeacherInfo h2", state="attached")
    assert "Alice Adams" in page.inner_text("#teacherDay")
    random_teacher = page.inner_text("#randomTeacherInfo h2")
    assert any(n in random_teacher for n in ("Alice Adams", "Bob Brown", "Carol Cruz")), random_teacher
    assert issues.unexpected(KNOWN) == []


def test_find_a_teacher_and_open_their_page(page, issues, site_url):
    page.goto(site_url + "/pages/index.html", wait_until="networkidle")
    page.wait_for_selector("#state option[value='Illinois']", state="attached")
    page.select_option("#state", "Illinois")
    page.wait_for_selector("#county option[value='Sangamon']", state="attached")
    page.select_option("#county", "Sangamon")
    page.wait_for_selector("#district option[value='Springfield District']", state="attached")
    page.select_option("#district", "Springfield District")
    page.wait_for_selector("#school option[value='Lincoln Elementary']", state="attached")
    page.select_option("#school", "Lincoln Elementary")
    page.click("#submitButton")
    page.wait_for_selector("#teacherListGrid a", state="attached")
    names = sorted(page.locator("#teacherListGrid a").all_inner_texts())
    assert names == ["Alice Adams", "Bob Brown"]

    with page.expect_navigation(wait_until="networkidle"):
        page.locator("#teacherListGrid a", has_text="Alice Adams").click()
    assert page.url.endswith("/pages/teacher.html")
    page.wait_for_function("document.querySelector('#teacher-name').innerText.includes('Alice')")
    assert page.inner_text("#teacher-name").strip() == "Alice Adams"
    assert "Lincoln Elementary" in page.inner_text("#school-name")
    assert "I teach 3rd grade." in page.inner_text("#about-me")
    assert "ALICE1234" in (page.get_attribute("#wishlistLink", "href") or "")
    # Logged out: no edit controls.
    assert "hidden" in page.get_attribute("#editButton", "class")
    assert issues.unexpected(KNOWN) == []


def test_teacher_can_edit_only_their_own_page(page, issues, site_url):
    login(page, site_url, "alice@example.com")
    assert issues.dialogs == ["Login successful as teacher"]

    page.goto(site_url + "/teacher/alice1234", wait_until="networkidle")
    page.wait_for_function("!document.querySelector('#editButton').classList.contains('hidden')")

    page.goto(site_url + "/teacher/bob5678", wait_until="networkidle")
    page.wait_for_function("document.querySelector('#teacher-name').innerText.includes('Bob')")
    assert "hidden" in page.get_attribute("#editButton", "class")
    # Bob's page: check_access_teacher refuses. It means 403 but answers 500.
    known = KNOWN + ["HTTP 500: GET /api/check_access_teacher/"]
    assert issues.unexpected(known) == []


def test_teacher_sees_pending_teachers_in_their_district(page, issues, site_url):
    login(page, site_url, "alice@example.com")
    page.goto(site_url + "/pages/validation.html", wait_until="networkidle")
    page.wait_for_selector("#validationList li", state="attached")
    text = page.inner_text("#validationList")
    assert "Pat Pending" in text and "pending@example.com" in text
    assert issues.unexpected(KNOWN) == []


def test_teacher_in_another_district_sees_no_pending_teachers(page, issues, site_url):
    login(page, site_url, "carol@example.com")
    page.goto(site_url + "/pages/validation.html", wait_until="networkidle")
    assert "Pat Pending" not in page.inner_text("#validationList")
    assert issues.unexpected(KNOWN) == []


def test_admin_pages_load(page, issues, site_url):
    login(page, site_url, "admin@example.com")
    assert issues.dialogs == ["Login successful as admin"]
    for path in ("/pages/validation.html", "/pages/admin.html"):
        page.goto(site_url + path, wait_until="networkidle")
        assert page.url.endswith(path), f"{path} redirected to {page.url}"
    assert issues.unexpected(KNOWN) == []


@pytest.mark.parametrize("path", [
    "/pages/edit_teacher.html", "/pages/update_password.html",
    "/pages/create_post.html", "/pages/create.html",
])
def test_logged_in_teacher_pages_load(page, issues, site_url, path):
    login(page, site_url, "alice@example.com")
    page.goto(site_url + path, wait_until="networkidle")
    assert issues.unexpected(KNOWN) == [], f"Problems on {path}"


def test_forum_list_and_post(page, issues, site_url):
    page.goto(site_url + "/pages/forum.html", wait_until="networkidle")
    page.wait_for_selector("#posts-container a[href*='post.html']", state="attached")
    text = page.inner_text("#posts-container")
    assert "Classroom library ideas" in text and "Fundraising tips" in text

    with page.expect_navigation(wait_until="networkidle"):
        page.locator("#posts-container a", has_text="Classroom library ideas").first.click()
    assert re.search(r"/pages/post\.html\?id=1$", page.url)
    page.wait_for_selector(".comment-content", state="attached")
    comments = page.locator(".comment-content").all_inner_texts()
    assert "Graphic novels!" in comments
    assert "Agreed, they fly off the shelf." in comments
    assert issues.unexpected(KNOWN) == []


def test_partner_link_shows_promo_on_homepage(page, issues, site_url):
    page.goto(site_url + "/seattlewolf", wait_until="networkidle")
    assert page.url.endswith("/pages/homepage.html")
    page.wait_for_function("document.querySelector('#promoHeroImage').getAttribute('src')")
    assert page.get_attribute("#promoHeroImage", "src").endswith("1007TheWolf.png")
    assert issues.unexpected(KNOWN) == []


@pytest.mark.xfail(strict=True, reason=(
    "Race: the homepage loads the teacher of the day on page load, and 'Find "
    "Random Teacher' loads another; both store 'which teacher to show' in the "
    "session. 'View Random Teacher' just opens teacher.html, so if the visitor "
    "asks for a random teacher before the teacher of the day has loaded, it "
    "opens the teacher of the day instead."))
def test_view_random_teacher_opens_that_teacher(page, issues, site_url):
    # Make the teacher-of-the-day answer arrive last, as it can on a slow
    # connection. Carol is the only teacher who isn't teacher of the day.
    def slow_tod(route):
        page.wait_for_timeout(1500)
        route.continue_()

    page.route("**/api/teacher_of_the_day", slow_tod)
    for _ in range(20):  # random_teacher is random: retry until it picks Carol
        page.goto(site_url + "/pages/homepage.html", wait_until="domcontentloaded")
        page.get_by_text("Find Random Teacher").click()
        page.wait_for_selector("#randomTeacherInfo h2", state="attached")
        if page.inner_text("#randomTeacherInfo h2").strip() == "Carol Cruz":
            break
    else:
        pytest.skip("random teacher never picked Carol")
    page.wait_for_load_state("networkidle")

    with page.expect_navigation(wait_until="networkidle"):
        page.locator("#randomTeacherInfo button").click()
    page.wait_for_function("document.querySelector('#teacher-name').innerText.trim() !== ''")
    assert page.inner_text("#teacher-name").strip() == "Carol Cruz"
