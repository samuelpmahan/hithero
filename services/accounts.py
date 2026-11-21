"""Accounts: registering, logging in, passwords and admin account changes."""

import datetime
import logging
import secrets

from sqlalchemy.orm import Session

from auth.passwords import hash_password, verify_password
from config import settings
from emails import render_email_template, send_email, send_registration_email
from repositories import teachers, users
from services.errors import Forbidden, Invalid, NotFound

logger = logging.getLogger("app")

RESET_TOKEN_LIFETIME = datetime.timedelta(hours=1)


def register(db: Session, *, name, email, phone_number, password, confirm_password, state, county, district, school) -> str:
    """Queue a new teacher for validation. Returns the message for the page."""
    if users.email_registered(db, email):
        return "User with this email already exists."
    if users.email_pending(db, email):
        return "User with this email is already in the registration queue."
    if password != confirm_password:
        return "Password do not match."
    users.add_pending(db, name=name, email=email, state=state, county=county, district=district, school=school,
                      phone_number=phone_number, password=hash_password(password), role="teacher", report=0, emailed=0)
    db.commit()
    send_registration_email(email)
    return "User registered successfully. You should recieve an email shortly. Please check your spam folder"


def authenticate(db: Session, email: str, password: str):
    """The registered user for these credentials, or None.

    Legacy sha256_crypt hashes are swapped for argon2 on success; a failed
    save is logged and does not block the login.
    """
    user = users.get_by_email(db, email)
    if not user:
        return None
    ok, upgraded_hash = verify_password(password, user.password)
    if not ok:
        return None
    if upgraded_hash:
        try:
            users.set_password_by_id(db, user.id, upgraded_hash)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.warning(f"Password hash upgrade failed for user {user.id}: {e}")
    return user


def change_password(db: Session, user_id: int, old_password: str, new_password: str) -> bool:
    """False if old_password is wrong."""
    if not verify_password(old_password, users.password_hash(db, user_id))[0]:
        return False
    users.set_password_by_id(db, user_id, hash_password(new_password))
    db.commit()
    return True


def request_password_reset(db: Session, email: str) -> bool:
    """Email a one-hour reset link if the address has an account.

    Returns whether it did; the caller answers the same either way.
    """
    if not users.email_registered(db, email):
        return False
    token = secrets.token_urlsafe(32)
    users.add_reset_token(db, email, token, datetime.datetime.utcnow() + RESET_TOKEN_LIFETIME)
    db.commit()
    reset_link = f"{settings.base_url}/pages/reset_password.html?token={token}"
    template_data = {
        'recipient_name': email,
        'message_body': (
            f"We received a request to reset your password. "
            f"Click the link below to reset it (expires in 1 hour):\n\n"
            f"{reset_link}\n\n"
            f"If you did not request this, you can ignore this email."
        )
    }
    html_message = render_email_template('static/email_template.html', template_data)
    plain_message = f"Dear {email},\n\nReset your password here: {reset_link}\n\nExpires in 1 hour."
    send_email(email, 'Password Reset Request', html_message, plain_message)
    return True


def reset_password(db: Session, token: str, new_password: str, confirm_password: str) -> None:
    """Set a new password from a mailed token. Each token works once."""
    if new_password != confirm_password:
        raise Invalid("Passwords do not match.")
    reset = users.get_usable_reset_token(db, token, datetime.datetime.utcnow())
    if not reset:
        raise Invalid("Invalid or expired reset token.")
    users.set_password_by_email(db, reset.email, hash_password(new_password))
    reset.used = 1
    db.commit()


def check_admin_secret(supplied: str) -> None:
    """Sensitive admin actions also need the server's admin secret."""
    if not settings.admin_secret or supplied != settings.admin_secret:
        raise Forbidden("Invalid administrator secret provided.")


def delete_account(db: Session, email: str) -> None:
    """Delete a registered user and their teacher page."""
    target = users.get_by_email(db, email)
    if not target:
        raise NotFound(f"User account linked to '{email}' not found.")
    teachers.delete_for_user(db, target.id)
    users.delete_by_email(db, email)
    db.commit()


def check_new_admin_password(password: str, confirm_password: str) -> None:
    if password != confirm_password:
        raise Invalid("Passwords do not match.")
    if len(password) < 8:
        raise Invalid("Password must be at least 8 characters long.")


def create_admin(db: Session, email: str, password: str) -> None:
    if users.email_registered(db, email) or users.email_pending(db, email):
        raise Invalid("An account with this email already exists.")
    users.create_admin(db, email, hash_password(password))
    db.commit()
