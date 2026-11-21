"""Accounts: pending users (new_users), validated users (registered_users)
and password reset tokens."""
import datetime

from sqlalchemy import String, cast, delete, insert, select, update
from sqlalchemy.orm import Session

from models import NewUsers, PasswordResetToken, RegisteredUsers, TeacherList


def _email_is(column, email):
    return cast(column, String) == cast(email, String)


# Validated users

def get_by_email(db: Session, email: str) -> RegisteredUsers | None:
    return db.execute(select(RegisteredUsers).where(_email_is(RegisteredUsers.email, email))).scalars().first()


def get_by_id(db: Session, user_id: int) -> RegisteredUsers | None:
    return db.execute(select(RegisteredUsers).where(RegisteredUsers.id == user_id)).scalars().first()


def email_registered(db: Session, email: str) -> bool:
    return db.execute(select(RegisteredUsers.id).where(_email_is(RegisteredUsers.email, email))).first() is not None


def email_by_id(db: Session, user_id: int) -> str | None:
    return db.execute(select(RegisteredUsers.email).where(RegisteredUsers.id == user_id)).scalar_one_or_none()


def password_hash(db: Session, user_id: int) -> str | None:
    return db.execute(select(RegisteredUsers.password).where(RegisteredUsers.id == user_id)).scalar()


def set_password_by_id(db: Session, user_id: int, hashed: str) -> None:
    db.execute(update(RegisteredUsers).where(RegisteredUsers.id == user_id).values(password=hashed))


def set_password_by_email(db: Session, email: str, hashed: str) -> None:
    db.execute(update(RegisteredUsers).where(_email_is(RegisteredUsers.email, email)).values(password=hashed))


def create_count(db: Session, user_id: int) -> int | None:
    return db.execute(select(RegisteredUsers.createCount).where(RegisteredUsers.id == user_id)).scalar()


def increment_create_count(db: Session, user_id: int) -> None:
    db.execute(
        update(RegisteredUsers)
        .where(RegisteredUsers.id == user_id)
        .values(createCount=RegisteredUsers.createCount + 1)
    )


def without_profile(db: Session) -> list[RegisteredUsers]:
    """Validated users who haven't created a teacher page."""
    return db.execute(select(RegisteredUsers).where(RegisteredUsers.createCount == 0)).scalars().all()


def contacts_by_id(db: Session, user_ids: list[int]):
    """Rows with .id, .email and .phone_number."""
    query = select(RegisteredUsers.id, RegisteredUsers.email, RegisteredUsers.phone_number).where(
        RegisteredUsers.id.in_(user_ids)
    )
    return db.execute(query).fetchall()


def teacher_emails_in_district(db: Session, state: str, county: str, district: str) -> list[str]:
    """Emails of validated users whose teacher page is in this district."""
    rows = (
        db.query(RegisteredUsers.email)
        .join(TeacherList, TeacherList.regUserID == RegisteredUsers.id)
        .filter(
            cast(TeacherList.state, String) == state,
            cast(TeacherList.county, String) == county,
            cast(TeacherList.district, String) == district,
        )
        .all()
    )
    return [r.email for r in rows]


def create_admin(db: Session, email: str, hashed: str) -> None:
    db.add(RegisteredUsers(email=email, password=hashed, role="admin", createCount=0))


def delete_by_email(db: Session, email: str) -> None:
    db.execute(delete(RegisteredUsers).where(_email_is(RegisteredUsers.email, email)))


# Users waiting for validation

def get_pending(db: Session, email: str) -> NewUsers | None:
    return db.execute(select(NewUsers).where(_email_is(NewUsers.email, email))).scalars().first()


def email_pending(db: Session, email: str) -> bool:
    return db.execute(select(NewUsers.id).where(_email_is(NewUsers.email, email))).first() is not None


def add_pending(db: Session, **values) -> None:
    db.add(NewUsers(**values))


def list_pending(db: Session) -> list[NewUsers]:
    return db.execute(select(NewUsers)).scalars().all()


def list_pending_in_district(db: Session, state, county, district) -> list[NewUsers]:
    query = select(NewUsers).where(
        (cast(NewUsers.state, String) == state)
        & (cast(NewUsers.county, String) == county)
        & (cast(NewUsers.district, String) == district)
    )
    return db.execute(query).scalars().all()


def pending_districts(db: Session) -> list[tuple[str, str, str]]:
    """(state, county, district) for every district with someone waiting."""
    columns = (cast(NewUsers.state, String), cast(NewUsers.county, String), cast(NewUsers.district, String))
    return db.query(*columns).group_by(*columns).all()


def promote_pending(db: Session, pending: NewUsers) -> None:
    """Move a validated user from new_users to registered_users."""
    db.execute(insert(RegisteredUsers).values(
        email=pending.email, password=pending.password, role=pending.role, phone_number=pending.phone_number,
    ))
    delete_pending(db, pending.email)


def delete_pending(db: Session, email: str) -> None:
    db.execute(delete(NewUsers).where(_email_is(NewUsers.email, email)))


def flag_pending(db: Session, email: str, **flags) -> None:
    """Set report=1 or emailed=1 on a pending user."""
    db.execute(update(NewUsers).where(_email_is(NewUsers.email, email)).values(**flags))


# Password reset tokens

def add_reset_token(db: Session, email: str, token: str, expires_at: datetime.datetime) -> None:
    db.add(PasswordResetToken(email=email, token=token, expires_at=expires_at))


def get_usable_reset_token(db: Session, token: str, now: datetime.datetime) -> PasswordResetToken | None:
    return db.query(PasswordResetToken).filter(
        PasswordResetToken.token == token,
        PasswordResetToken.used == 0,
        PasswordResetToken.expires_at > now,
    ).first()
