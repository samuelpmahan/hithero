"""Accounts: users waiting for validation, validated users and password reset tokens."""
from sqlalchemy import Column, DateTime, Integer, String

from models.base import Base


class NewUsers(Base):
    __tablename__ = "new_users"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String)
    state = Column(String)
    county = Column(String)
    district = Column(String)
    school = Column(String)
    phone_number = Column(String)
    password = Column(String)
    role = Column(String)
    report = Column(Integer)
    emailed = Column(Integer)


class RegisteredUsers(Base):
    __tablename__ = "registered_users"

    id = Column(Integer, primary_key=True)
    email = Column(String)
    phone_number = Column(String)
    password = Column(String)
    role = Column(String)
    createCount = Column(Integer)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False)
    token = Column(String, nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Integer, default=0)
