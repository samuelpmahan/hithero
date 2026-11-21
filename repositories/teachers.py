"""Teacher pages (teacher_list)."""
import datetime

from sqlalchemy import String, cast, delete, desc, func, insert, select, update
from sqlalchemy.orm import Session

from models import TeacherList


def get_by_user_id(db: Session, user_id: int) -> TeacherList | None:
    return db.execute(select(TeacherList).where(TeacherList.regUserID == user_id)).scalars().first()


def get_by_url_id(db: Session, url_id: str) -> TeacherList | None:
    return db.execute(
        select(TeacherList).where(cast(TeacherList.url_id, String) == url_id)
    ).scalars().first()


def url_id_taken(db: Session, url_id: str) -> bool:
    query = select(TeacherList.id).where(cast(TeacherList.url_id, String) == cast(url_id, String))
    return db.execute(query).first() is not None


def _location_and_name(state, county, district, school, name):
    return (
        (cast(TeacherList.state, String) == state)
        & (cast(TeacherList.county, String) == county)
        & (cast(TeacherList.district, String) == district)
        & (cast(TeacherList.school, String) == school)
        & (cast(TeacherList.name, String) == name)
    )


def get_by_location_and_name(db: Session, state, county, district, school, name) -> TeacherList | None:
    """The teacher a page is showing, from the five values kept in the session."""
    query = select(TeacherList).where(_location_and_name(state, county, district, school, name))
    return db.execute(query).scalars().first()


def random_teacher(db: Session) -> TeacherList | None:
    return db.execute(select(TeacherList).order_by(func.newid()).limit(1)).scalar_one_or_none()


def pick_teacher_of_the_day(db: Session, cutoff: datetime.datetime) -> TeacherList | None:
    """A random teacher not featured since cutoff (or never featured).

    If everyone was featured since cutoff, the one featured longest ago.
    None only when there are no teachers at all.
    """
    eligible = select(TeacherList).where(
        (TeacherList.last_TOD.is_(None)) | (TeacherList.last_TOD < cutoff)
    ).order_by(func.newid()).limit(1)
    teacher = db.execute(eligible).scalar_one_or_none()
    if teacher is None:
        oldest = select(TeacherList).order_by(TeacherList.last_TOD).limit(1)
        teacher = db.execute(oldest).scalar_one_or_none()
    return teacher


def latest_teacher_of_the_day(db: Session) -> TeacherList | None:
    query = (
        select(TeacherList)
        .where(TeacherList.last_TOD.isnot(None))
        .order_by(desc(TeacherList.last_TOD))
        .limit(1)
    )
    return db.execute(query).scalars().first()


def stamp_teacher_of_the_day(db: Session, teacher_id: int, when: datetime.datetime) -> None:
    db.execute(update(TeacherList).where(TeacherList.id == teacher_id).values(last_TOD=when))


def create(db: Session, **values) -> None:
    db.execute(insert(TeacherList).values(**values))


def update_for_user(db: Session, user_id: int, **values) -> None:
    db.execute(update(TeacherList).where(TeacherList.regUserID == user_id).values(**values))


def delete_for_user(db: Session, user_id: int) -> None:
    db.execute(delete(TeacherList).where(TeacherList.regUserID == user_id))


# Browsing teachers who have pages (the Donate page dropdowns)

def index_states(db: Session) -> list[str]:
    return [row[0] for row in db.execute(select(cast(TeacherList.state, String)).distinct()).all()]


def index_counties(db: Session, state: str) -> list[str]:
    query = select(cast(TeacherList.county, String)).distinct().where(cast(TeacherList.state, String) == state)
    return [row[0] for row in db.execute(query).all()]


def index_districts(db: Session, state: str, county: str) -> list[str]:
    query = select(cast(TeacherList.district, String)).distinct().where(
        (cast(TeacherList.state, String) == state) & (cast(TeacherList.county, String) == county)
    )
    return [row[0] for row in db.execute(query).all()]


def index_schools(db: Session, state: str, county: str, district: str) -> list[str]:
    query = select(cast(TeacherList.school, String)).distinct().where(
        (cast(TeacherList.state, String) == state)
        & (cast(TeacherList.county, String) == county)
        & (cast(TeacherList.district, String) == district)
    )
    return [row[0] for row in db.execute(query).all()]


def _filtered(query, state, county, district, school):
    query = query.where(cast(TeacherList.state, String) == state)
    if county:
        query = query.where(cast(TeacherList.county, String) == county)
    if district:
        query = query.where(cast(TeacherList.district, String) == district)
    if school:
        query = query.where(cast(TeacherList.school, String) == school)
    return query


def search(db: Session, state, county=None, district=None, school=None):
    """Rows with .name and .url_id for teachers matching the filters."""
    query = _filtered(select(TeacherList.name, TeacherList.url_id), state, county, district, school)
    return db.execute(query).fetchall()


def report_rows(db: Session, state, county=None, district=None, school=None):
    """Rows with .name, .school and .regUserID for the admin report."""
    query = _filtered(
        select(TeacherList.name, TeacherList.school, TeacherList.regUserID), state, county, district, school
    )
    return db.execute(query).fetchall()
