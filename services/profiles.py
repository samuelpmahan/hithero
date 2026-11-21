"""Teacher profiles: creating one, and the rules for each field a teacher edits."""

import re
import secrets

import puremagic
from sqlalchemy.orm import Session

from auth.dependencies import CurrentUser
from repositories import teachers, users
from services.errors import Conflict, Invalid

AMAZON_TAG = "&tag=h0mer00mher0-20"
MAX_IMAGE_BYTES = 1 * 1024 * 1024
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
URL_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{3,50}$")


def wishlist_link(wishlist: str) -> str:
    """The wishlist URL with the site's Amazon associate tag appended."""
    return wishlist + AMAZON_TAG


def _new_url_id(db: Session, email: str) -> str:
    """email's local part plus a random number, retried until unused."""
    first_part = email.split("@")[0]
    while True:
        candidate = f"{first_part}{secrets.randbelow(9999)}"
        if not teachers.url_id_taken(db, candidate):
            return candidate


def create(db: Session, user: CurrentUser, email: str, *, name, state, county, district, school, about_me, wishlist) -> bool:
    """Create the user's teacher page. One page per user, except admins.

    Returns False (and changes nothing) when the user already made one.
    """
    if users.create_count(db, user.id) != 0 and user.role != "admin":
        return False
    teachers.create(
        db, name=name, state=state, county=county, district=district, school=school,
        regUserID=user.id, about_me=about_me, wishlist_url=wishlist_link(wishlist),
        url_id=_new_url_id(db, email),
    )
    users.increment_create_count(db, user.id)
    db.commit()
    return True


def update(db: Session, user_id: int, **fields) -> None:
    """Change fields on the user's teacher page (about_me, name, school, ...)."""
    teachers.update_for_user(db, user_id, **fields)
    db.commit()


def set_wishlist(db: Session, user_id: int, wishlist: str) -> None:
    update(db, user_id, wishlist_url=wishlist_link(wishlist))


def set_url_id(db: Session, user_id: int, url_id: str) -> None:
    if not URL_ID_PATTERN.match(url_id):
        raise Invalid("URL ID may only contain letters, numbers, hyphens, and underscores (3–50 characters).")
    if teachers.url_id_taken(db, url_id):
        raise Conflict("URL ID already in use.")
    update(db, user_id, url_id=url_id)


def check_image_size(size: int | None) -> None:
    if size > MAX_IMAGE_BYTES:
        raise Invalid("File size exceeds the allowed limit")


def set_image(db: Session, user_id: int, image_bytes: bytes) -> None:
    """Store a profile photo, checked by its file signature (not the
    client's content type). puremagic.magic_string returns matches best
    first; empty or unreadable input raises PureError/ValueError."""
    try:
        results = puremagic.magic_string(image_bytes)
    except (puremagic.PureError, ValueError):
        results = []
    if (results[0].mime_type if results else None) not in IMAGE_TYPES:
        raise Invalid("Invalid file type. Only JPEG, PNG, GIF, and WebP are allowed.")
    update(db, user_id, image_data=image_bytes)
