"""Validating new users: who may see and approve whom."""

from sqlalchemy.orm import Session

from auth.dependencies import CurrentUser
from emails import send_validation_email
from repositories import teachers, users
from services.errors import Forbidden, NotFound


def validate(db: Session, caller: CurrentUser, email: str) -> None:
    """Move a pending user into registered_users and email them.

    Admins may validate anyone; teachers only people in their own
    state, county and district.
    """
    pending = users.get_pending(db, email)
    if not pending:
        raise NotFound("User not found in new_users")
    if caller.role == "teacher":
        own = teachers.get_by_user_id(db, caller.id)
        if not own or (pending.state, pending.county, pending.district) != (own.state, own.county, own.district):
            raise Forbidden("You can only validate teachers in your own district.")
    address = pending.email
    users.promote_pending(db, pending)
    db.commit()
    send_validation_email(address)


def _as_dict(u) -> dict:
    return {"name": u.name, "email": u.email, "state": u.state, "district": u.district, "school": u.school,
            "phone_number": u.phone_number, "report": u.report, "emailed": u.emailed}


def pending_for(db: Session, role: str, state=None, county=None, district=None) -> list[dict] | None:
    """Pending users the caller may see: all of them for admins, those in
    the given district for teachers, None for any other role."""
    if role == "admin":
        return [_as_dict(u) for u in users.list_pending(db)]
    if role == "teacher":
        return [_as_dict(u) for u in users.list_pending_in_district(db, state, county, district)]
    return None


def delete(db: Session, email: str) -> None:
    if not users.email_pending(db, email):
        raise NotFound("User not found in new_users")
    users.delete_pending(db, email)
    db.commit()


def flag(db: Session, email: str, **flags: int) -> None:
    """Set report=1 or emailed=1 on a pending user."""
    users.flag_pending(db, email, **flags)
    db.commit()
