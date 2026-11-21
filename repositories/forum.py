"""Forum posts, comments and votes."""
from sqlalchemy import desc
from sqlalchemy.orm import Session

from models import ForumComment, ForumPost, PostVote


def list_posts(db: Session) -> list[ForumPost]:
    return db.query(ForumPost).order_by(ForumPost.created_at.desc()).all()


def get_post(db: Session, post_id: int) -> ForumPost | None:
    return db.query(ForumPost).filter(ForumPost.id == post_id).first()


def get_comment(db: Session, comment_id: int) -> ForumComment | None:
    return db.query(ForumComment).filter(ForumComment.id == comment_id).first()


def list_comments(db: Session, post_id: int) -> list[ForumComment]:
    return (
        db.query(ForumComment)
        .filter(ForumComment.post_id == post_id)
        .order_by(desc(ForumComment.created_at))
        .all()
    )


def get_vote(db: Session, post_id: int, user_id: int) -> PostVote | None:
    return db.query(PostVote).filter(PostVote.post_id == post_id, PostVote.user_id == user_id).first()


def add(db: Session, item) -> None:
    db.add(item)


def remove(db: Session, item) -> None:
    db.delete(item)
