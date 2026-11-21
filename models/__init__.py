"""Database tables (SQLAlchemy models), split out of app.py in BE2-5.

These mirror what app.py declared. The real production columns may
differ (see BE2-1 / BE2-2); the models get corrected after the audit.
"""
from models.base import Base
from models.forum import ForumComment, ForumPost, PostVote
from models.schools import School
from models.teachers import TeacherList
from models.users import NewUsers, PasswordResetToken, RegisteredUsers

__all__ = [
    "Base",
    "ForumComment",
    "ForumPost",
    "NewUsers",
    "PasswordResetToken",
    "PostVote",
    "RegisteredUsers",
    "School",
    "TeacherList",
]
