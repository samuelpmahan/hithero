"""School directory lookups for the registration dropdowns."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from models import School


def list_states(db: Session) -> list[str]:
    return [row[0] for row in db.execute(select(School.state).distinct()).all()]


def list_counties(db: Session, state: str) -> list[str]:
    query = select(School.county).distinct().where(School.state == state)
    return [row[0] for row in db.execute(query).all()]


def list_districts(db: Session, state: str, county: str) -> list[str]:
    query = select(School.district).distinct().where((School.state == state) & (School.county == county))
    return [row[0] for row in db.execute(query).all()]


def list_schools(db: Session, state: str, county: str, district: str) -> list[str]:
    query = select(School.school_name).distinct().where(
        (School.state == state) & (School.county == county) & (School.district == district)
    )
    return [row[0] for row in db.execute(query).all()]
