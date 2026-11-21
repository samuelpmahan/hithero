"""BE1-6: flow tests for the write paths.

Golden files cover reads; these walk the main write journeys end to end
through the HTTP API, each on a freshly seeded database:
  - register > validate > login > create profile > open the teacher page
  - forgot password > reset > log in with the new password
  - forum post > comment > vote > edit > delete

They assert today's behaviour, so the refactor can't change it silently.
When a task changes behaviour on purpose, the assertion changes with it.
"""
import re
import time

import pytest

from models import RegisteredUsers, TeacherList
from tests import helpers
from tests.helpers import fresh_db, no_rate_limits, outbox, requires_db  # noqa: F401  (fixtures)
from tests.seed import SEED_PASSWORD

pytestmark = requires_db


def login(c, email, password=SEED_PASSWORD):
    return c.post("/profile/login/", data={"email": email, "password": password})


def test_register_validate_create_profile(fresh_db):
    outbox = fresh_db
    new = {
        "name": "Dana Diaz", "email": "dana@example.com", "phone_number": "5551112222",
        "password": "Dana-Passw0rd!", "confirm_password": "Dana-Passw0rd!",
        "state": "Illinois", "county": "Sangamon", "district": "Springfield District",
        "school": "Douglas Middle", "recaptcha_response": "ok",
    }

    # Register: goes into the validation queue and gets an email.
    visitor = helpers.client()
    r = visitor.post("/profile/register/", data=new)
    assert r.status_code == 200
    assert r.json()["message"].startswith("User registered successfully")
    assert outbox.sent[-1]["content"]["subject"] == "Registration successful"

    r = visitor.post("/profile/register/", data=new)
    assert r.json() == {"message": "User with this email is already in the registration queue."}

    # Not validated yet: can't log in.
    r = login(visitor, new["email"], new["password"])
    assert r.json() == {"message": "Invalid login credentials."}

    # A teacher in another district can't validate.
    carol = helpers.client()
    login(carol, "carol@example.com")
    r = carol.post(f"/validation/validate_user/{new['email']}")
    assert r.status_code == 403

    # A teacher in the same district can.
    alice = helpers.client()
    login(alice, "alice@example.com")
    r = alice.get("/api/validation_list/")
    assert new["email"] in [u["email"] for u in r.json()["new_users"]]
    r = alice.post(f"/validation/validate_user/{new['email']}")
    assert r.status_code == 200
    assert r.json() == {"message": "User validated."}
    assert outbox.sent[-1]["content"]["subject"] == "Validation Notification"

    # Log in and create the teacher profile.
    dana = helpers.client()
    r = login(dana, new["email"], new["password"])
    assert r.json() == {"message": "Login successful as teacher", "createCount": 0, "role": "teacher"}
    r = dana.post("/profile/create_teacher_profile/", data={
        "name": "Dana Diaz", "state": "Illinois", "county": "Sangamon",
        "district": "Springfield District", "school": "Douglas Middle",
        "aboutMe": "Music teacher.", "wishlist": "https://www.amazon.com/hz/wishlist/ls/DANA",
    })
    assert r.json() == {"message": "Teacher created successfully", "role": "teacher"}


def test_create_profile_and_open_teacher_page(fresh_db):
    """Create a profile, then open it as a visitor."""
    import app

    db = app.SessionLocal()
    db.add(RegisteredUsers(email="erin@example.com", phone_number="5553334444",
                               password=db.query(RegisteredUsers.password).first()[0],
                               role="teacher", createCount=0))
    db.commit()
    db.close()

    erin = helpers.client()
    r = login(erin, "erin@example.com")
    assert r.json() == {"message": "Login successful as teacher", "createCount": 0, "role": "teacher"}

    r = erin.post("/profile/create_teacher_profile/", data={
        "name": "Erin Evans", "state": "Texas", "county": "Bexar",
        "district": "San Antonio ISD", "school": "Alamo Elementary",
        "aboutMe": "PE teacher.", "wishlist": "https://www.amazon.com/hz/wishlist/ls/ERIN",
    })
    assert r.json() == {"message": "Teacher created successfully", "role": "teacher"}

    r = erin.post("/profile/create_teacher_profile/", data={
        "name": "Erin Again", "state": "Texas", "county": "Bexar",
        "district": "San Antonio ISD", "school": "Alamo Elementary",
        "aboutMe": "x", "wishlist": "https://www.amazon.com/hz/wishlist/ls/ERIN",
    })
    assert r.json() == {"message": "Unable to create new profile. Profile already created."}

    r = erin.get("/profile/myinfo/")
    assert r.json() == {"state": "Texas", "county": "Bexar", "district": "San Antonio ISD",
                        "school": "Alamo Elementary", "teacher": "Erin Evans"}

    db = app.SessionLocal()
    url_id = db.query(TeacherList.url_id).filter(TeacherList.name == "Erin Evans").scalar()
    db.close()
    assert re.fullmatch(r"erin\d{1,4}", url_id)

    visitor = helpers.client()
    r = visitor.get(f"/teacher/{url_id}")
    assert r.status_code == 307
    assert r.headers["location"] == "/pages/teacher.html"
    r = visitor.get("/api/get_teacher_info/")
    assert r.json()["name"] == "Erin Evans"
    assert r.json()["wishlist_url"] == "https://www.amazon.com/hz/wishlist/ls/ERIN&tag=h0mer00mher0-20"

    r = erin.get("/api/check_access_teacher/")
    assert r.json() == {"status": "success", "message": "Access granted"}


def test_forgot_and_reset_password(fresh_db, monkeypatch):
    import app

    outbox = fresh_db
    visitor = helpers.client()
    r = visitor.post("/profile/forgot_password/", data={"email": "bob@example.com"})
    assert r.json() == {"message": "If an account exists, a reset link will be sent to your email."}
    token = re.search(r"token=([\w-]+)", outbox.sent[-1]["content"]["plainText"]).group(1)

    # BE2-11: the table holds only the token's hash, never the mailed token.
    from models import PasswordResetToken
    with app.SessionLocal() as db:
        stored = [row.token for row in db.query(PasswordResetToken).all()]
    assert token not in stored
    assert len(stored) == 1 and len(stored[0]) == len(token) == 43

    # Unknown address: same answer, no email.
    monkeypatch.setattr(time, "sleep", lambda s: None)
    sent_before = len(outbox.sent)
    r = visitor.post("/profile/forgot_password/", data={"email": "nobody@example.com"})
    assert r.json() == {"message": "If an account exists, a reset link will be sent to your email."}
    assert len(outbox.sent) == sent_before

    r = visitor.post("/profile/reset_password/", data={
        "token": token, "new_password": "New-Passw0rd!", "confirm_password": "Mismatch!"})
    assert r.status_code == 400

    r = visitor.post("/profile/reset_password/", data={
        "token": token, "new_password": "New-Passw0rd!", "confirm_password": "New-Passw0rd!"})
    assert r.json() == {"message": "Password reset successfully. You can now log in."}

    # The token works once.
    r = visitor.post("/profile/reset_password/", data={
        "token": token, "new_password": "Other-Passw0rd!", "confirm_password": "Other-Passw0rd!"})
    assert r.status_code == 400

    bob = helpers.client()
    assert login(bob, "bob@example.com").json() == {"message": "Invalid login credentials."}
    assert login(bob, "bob@example.com", "New-Passw0rd!").json()["message"] == "Login successful as teacher"


def test_forum_post_comment_vote_edit_delete(fresh_db):
    alice, bob, admin = helpers.client(), helpers.client(), helpers.client()
    login(alice, "alice@example.com")
    login(bob, "bob@example.com")
    login(admin, "admin@example.com")

    # Logged out can't post, comment or vote.
    anon = helpers.client()
    assert anon.post("/forum/create_post", data={"title": "x", "content": "y"}).status_code == 401
    assert anon.post("/forum/posts/1/comment", data={"content": "x"}).status_code == 401
    assert anon.post("/forum/posts/1/vote", json={"vote_type": 1}).status_code == 401

    r = alice.post("/forum/create_post", data={
        "title": "Field trip <script>x</script>ideas", "content": "<p>Where do you <b>go</b>?</p>"})
    assert r.status_code == 200
    post = r.json()
    assert post["title"] == "Field trip xideas"  # tags outside the allow list are stripped
    assert post["content"] == "<p>Where do you <b>go</b>?</p>"
    assert (post["upvote_count"], post["comment_count"]) == (0, 0)
    post_id = post["id"]

    r = bob.post(f"/forum/posts/{post_id}/comment", data={"content": "The science museum."})
    assert r.status_code == 200
    comment_id = r.json()["id"]
    r = alice.post(f"/forum/posts/{post_id}/comment",
                   data={"content": "Good one!", "parent_comment_id": str(comment_id)})
    assert r.json()["parent_comment_id"] == comment_id
    assert helpers.client().get(f"/forum/get_post?post_id={post_id}").json()["comment_count"] == 2

    # Vote: up, same again retracts, then down.
    assert bob.post(f"/forum/posts/{post_id}/vote", json={"vote_type": 1}).json()["upvote_count"] == 1
    assert bob.post(f"/forum/posts/{post_id}/vote", json={"vote_type": 1}).json()["upvote_count"] == 0
    assert bob.post(f"/forum/posts/{post_id}/vote", json={"vote_type": -1}).json()["upvote_count"] == -1
    assert alice.post(f"/forum/posts/{post_id}/vote", json={"vote_type": 1}).json()["upvote_count"] == 0
    assert bob.post(f"/forum/posts/{post_id}/vote", json={"vote_type": 1}).json()["upvote_count"] == 2
    assert bob.post(f"/forum/posts/{post_id}/vote", json={"vote_type": 5}).status_code == 400

    # Edit: only the author.
    r = bob.patch(f"/forum/post/{post_id}/update", json={"title": "Hacked", "content": "x"})
    assert r.status_code == 403
    r = alice.patch(f"/forum/post/{post_id}/update", json={"title": "Field trips", "content": "<p>Updated</p>"})
    assert r.status_code == 200
    assert (r.json()["title"], r.json()["content"]) == ("Field trips", "<p>Updated</p>")

    r = alice.patch(f"/forum/comment/{comment_id}/update", data={"content": "Not mine"})
    assert r.status_code == 403
    r = bob.patch(f"/forum/comment/{comment_id}/update", data={"content": "The art museum."})
    assert r.json()["content"] == "The art museum."

    # Delete: admin only, for comments and posts.
    assert bob.delete(f"/forum/comment/{comment_id}/delete").status_code == 403
    assert alice.delete(f"/forum/post/{post_id}/delete").status_code == 403

    reply_id = comment_id + 1
    r = admin.delete(f"/forum/comment/{reply_id}/delete")
    assert r.json() == {"detail": f"Comment ID {reply_id} successfully deleted."}
    assert helpers.client().get(f"/forum/get_post?post_id={post_id}").json()["comment_count"] == 1


def test_delete_post_with_comments(fresh_db, caplog):
    """Deleting a post that still has comments or votes.

    The handler's comment says the database cascades, but the models
    declare no ON DELETE CASCADE, so the delete fails. This records
    today's behaviour; BE2-8 decides what it should do.
    """
    admin = helpers.client(raise_errors=False)
    login(admin, "admin@example.com")
    r = admin.delete("/forum/post/1/delete")
    assert r.status_code == 500
    assert r.json() == {"detail": "Internal Server Error"}
    # BE3-4: the one error handler logs the path and the cause.
    assert "DELETE /forum/post/1/delete" in caplog.text
    assert "REFERENCE constraint" in caplog.text


def test_daily_teacher_of_the_day_job(fresh_db):
    """Daily job: picks a teacher, stamps last_TOD, emails them, and the
    homepage's teacher of the day becomes that teacher."""
    import jobs

    outbox = fresh_db
    jobs.daily_job()
    assert len(outbox.sent) == 1
    message = outbox.sent[0]
    assert message["content"]["subject"] == "🎉 You're Today's Homeroom Hero!"
    recipient = message["recipients"]["to"][0]["address"]
    assert recipient in {"alice@example.com", "bob@example.com", "carol@example.com"}

    featured = helpers.client().get("/api/teacher_of_the_day").json()
    assert featured["url_id"] in message["content"]["plainText"]


DENIED = [
    # (who, method, path, form data or JSON) -> expect 403
    (None, "post", "/validation/validate_user/pending@example.com", None),
    (None, "post", "/validation/report_user/pending@example.com", None),
    (None, "post", "/validation/emailed_user/pending@example.com", None),
    ("alice@example.com", "post", "/validation/delete_user/pending@example.com", None),
    (None, "post", "/profile/update_info/", {"aboutMe": "x"}),
    (None, "post", "/profile/update_teacher_name/", {"teacher": "x"}),
    (None, "post", "/profile/update_wishlist/", {"wishlist": "x"}),
    (None, "post", "/profile/update_url_id/", {"url_id": "xyz123"}),
    (None, "post", "/profile/update_teacher_school/",
     {"state": "x", "county": "x", "district": "x", "school": "x"}),
    (None, "post", "/profile/create_teacher_profile/",
     {"name": "x", "state": "x", "county": "x", "district": "x", "school": "x", "aboutMe": "x", "wishlist": "x"}),
    ("alice@example.com", "post", "/admin/generate_teacher_report/", {"state": "Illinois"}),
    ("alice@example.com", "post", "/profile/delete/", {"target_email": "bob@example.com", "admin_secret_input": "x"}),
    ("alice@example.com", "post", "/admin/create_admin/",
     {"email": "x@example.com", "password": "x", "confirm_password": "x", "admin_secret_input": "x"}),
    ("alice@example.com", "delete", "/forum/post/1/delete", None),
    ("alice@example.com", "delete", "/forum/comment/1/delete", None),
    (None, "get", "/api/validation_list/", None),
    ("admin@example.com", "get", "/api/check_access_teacher/", None),
]


@pytest.mark.parametrize("who,method,path,data", DENIED, ids=[f"{d[0] or 'anon'} {d[2]}" for d in DENIED])
def test_denied_calls_return_403(no_rate_limits, who, method, path, data):
    """BE3-1: every refused call answers 403, not 200 or 500."""
    c = helpers.client()
    if who:
        login(c, who)
    r = getattr(c, method)(path, data=data) if data else getattr(c, method)(path)
    assert r.status_code == 403, f"{path} answered {r.status_code}"


PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d4944415478da63f8ffff3f0005fe02fea7d6a4c80000000049454e44ae426082"
)


def test_teacher_profile_edits(fresh_db):
    alice = helpers.client()
    login(alice, "alice@example.com")
    assert alice.post("/profile/update_info/", data={"aboutMe": "New about."}).json() == {"message": "Info updated."}
    assert alice.post("/profile/update_teacher_name/", data={"teacher": "Alice A."}).json() == {"message": "Name updated."}
    assert alice.post("/profile/update_wishlist/", data={"wishlist": "https://a.co/new"}).json() == {"message": "Wishlist updated."}
    r = alice.post("/profile/update_teacher_school/", data={
        "state": "Illinois", "county": "Sangamon", "district": "Springfield District", "school": "Douglas Middle"})
    assert r.json() == {"message": "School information updated successfully."}
    assert alice.post("/profile/update_url_id/", data={"url_id": "bob5678"}).status_code == 409
    assert alice.post("/profile/update_url_id/", data={"url_id": "no spaces"}).status_code == 400
    assert alice.post("/profile/update_url_id/", data={"url_id": "alice-new"}).json() == {"message": "URL ID updated successfully."}
    r = alice.post("/profile/update_teacher_image/", files={"image": ("a.png", PNG_1PX, "image/png")})
    assert r.json() == {"message": "Information updated."}
    r = alice.post("/profile/update_teacher_image/", files={"image": ("a.txt", b"not an image", "text/plain")})
    assert r.status_code == 400

    visitor = helpers.client()
    visitor.get("/teacher/alice-new")
    info = visitor.get("/api/get_teacher_info/").json()
    assert (info["name"], info["school"], info["about_me"]) == ("Alice A.", "Douglas Middle", "New about.")
    assert info["wishlist_url"] == "https://a.co/new&tag=h0mer00mher0-20"
    assert info["image_data"] is not None


def test_change_password(fresh_db):
    bob = helpers.client()
    login(bob, "bob@example.com")
    r = bob.post("/profile/update_password/", data={
        "old_password": "wrong", "new_password": "N3w-pass!", "new_password_confirmed": "N3w-pass!"})
    assert r.json() == {"message": "Invalid old password"}
    r = bob.post("/profile/update_password/", data={
        "old_password": SEED_PASSWORD, "new_password": "N3w-pass!", "new_password_confirmed": "N3w-pass!"})
    assert r.json() == {"status": "success", "message": "Password updated successfully"}
    assert login(helpers.client(), "bob@example.com", "N3w-pass!").json()["message"] == "Login successful as teacher"


def test_validation_actions(fresh_db):
    alice, admin = helpers.client(), helpers.client()
    login(alice, "alice@example.com")
    login(admin, "admin@example.com")
    assert alice.post("/validation/report_user/pending@example.com").json() == {"message": "User reported."}
    assert alice.post("/validation/emailed_user/pending@example.com").json() == {"message": "User emailed."}
    pending = admin.get("/api/validation_list/").json()["new_users"][0]
    assert (pending["report"], pending["emailed"]) == (1, 1)
    assert admin.post("/validation/delete_user/pending@example.com").json() == {"message": "User deleted successfully."}
    assert admin.get("/api/validation_list/").json()["new_users"] == []


def test_admin_report_and_account_actions(fresh_db):
    admin = helpers.client(raise_errors=False)
    login(admin, "admin@example.com")

    r = admin.post("/admin/generate_teacher_report/", data={"state": "Illinois", "county": "Sangamon"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    assert admin.post("/admin/generate_teacher_report/", data={"state": "Nowhere"}).status_code == 404

    secret = "test-admin-secret"
    r = admin.post("/admin/create_admin/", data={
        "email": "admin2@example.com", "password": "Adm1n-pass", "confirm_password": "Adm1n-pass",
        "admin_secret_input": secret})
    assert r.json() == {"message": "Admin account created successfully for admin2@example.com."}
    r = admin.post("/admin/create_admin/", data={
        "email": "alice@example.com", "password": "Adm1n-pass", "confirm_password": "Adm1n-pass",
        "admin_secret_input": secret})
    assert r.status_code == 400
    r = admin.post("/admin/create_admin/", data={
        "email": "x@example.com", "password": "Adm1n-pass", "confirm_password": "Adm1n-pass",
        "admin_secret_input": "wrong"})
    assert r.status_code == 403
    assert login(helpers.client(), "admin2@example.com", "Adm1n-pass").json()["message"] == "Login successful as admin"

    # Existing behaviour: deleting an account that still has forum posts,
    # comments or votes hits the forum foreign keys and returns 500 (see
    # SCHEMA_ASSUMPTIONS.md; depends on production having those FKs).
    r = admin.post("/profile/delete/", data={"target_email": "carol@example.com", "admin_secret_input": secret})
    assert r.status_code == 500
    import app
    from models import ForumComment, ForumPost, PostVote
    with app.SessionLocal() as db:
        db.query(ForumComment).filter(ForumComment.post_id == 2).delete()
        db.query(PostVote).filter(PostVote.user_id == 4).delete()
        db.query(PostVote).filter(PostVote.post_id == 2).delete()
        db.query(ForumPost).filter(ForumPost.user_id == 4).delete()
        db.commit()
    r = admin.post("/profile/delete/", data={"target_email": "carol@example.com", "admin_secret_input": secret})
    assert r.json() == {"message": "Successfully deleted account and associated data for target user: carol@example.com."}
    assert login(helpers.client(), "carol@example.com").json() == {"message": "Invalid login credentials."}
    assert helpers.client().get("/teacher/carol42").headers["location"] == "/pages/404.html"
    r = admin.post("/profile/delete/", data={"target_email": "nobody@example.com", "admin_secret_input": secret})
    assert r.status_code == 404


def test_login_upgrades_legacy_password_hash(fresh_db):
    """BE2-11: seed users hold sha256_crypt hashes (like production today).
    A successful login swaps in an argon2 hash, and the same password keeps
    working. A wrong password changes nothing."""
    import app
    from repositories import users

    def stored_hash():
        with app.SessionLocal() as db:
            return users.password_hash(db, 3)

    assert stored_hash().startswith("$5$")
    assert login(helpers.client(), "bob@example.com", "wrong").json() == {"message": "Invalid login credentials."}
    assert stored_hash().startswith("$5$")

    assert login(helpers.client(), "bob@example.com").json()["message"] == "Login successful as teacher"
    upgraded = stored_hash()
    assert upgraded.startswith("$argon2id$")
    assert login(helpers.client(), "bob@example.com").json()["message"] == "Login successful as teacher"
    assert stored_hash() == upgraded
    assert login(helpers.client(), "bob@example.com", "wrong").json() == {"message": "Invalid login credentials."}


def test_teacher_of_the_day_when_everyone_was_featured_recently(fresh_db):
    """BE4-4: the old picker looped forever once every teacher had been
    featured within 90 days. Now it takes whoever was featured longest ago."""
    import datetime

    import app
    import jobs

    now = datetime.datetime.utcnow()
    with app.SessionLocal() as db:
        for i, teacher in enumerate(db.query(TeacherList).order_by(TeacherList.id)):
            teacher.last_TOD = now - datetime.timedelta(days=1, hours=i)
        db.commit()
        oldest = db.query(TeacherList).order_by(TeacherList.last_TOD).first().url_id
        picked = jobs.fetch_teacher_for_tod(db)
    assert picked is not None and picked.url_id == oldest

    outbox = fresh_db
    jobs.daily_job()
    assert len(outbox.sent) == 1
