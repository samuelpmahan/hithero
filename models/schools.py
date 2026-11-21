"""School directory: every school a teacher can pick when registering."""
from sqlalchemy import Column, Integer, String

from models.base import Base


class School(Base):
    __tablename__ = "schools"

    id = Column(Integer, primary_key=True)
    school_name = Column(String)
    district = Column(String)
    county = Column(String)
    state = Column(String)
