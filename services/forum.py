"""Forum rules: cleaning user HTML, vote counting, comment counts, and who
may edit or delete what."""

import bleach
from sqlalchemy.orm import Session

from models import ForumComment, ForumPost, PostVote
from repositories import forum
from services.errors import Forbidden, Invalid, NotFound

ALLOWED_TAGS = ["b", "i", "em", "strong", "a", "p", "br"]
ALLOWED_ATTRS = {"a": ["href"]}


def clean(text: str) -> str:
    """Strip any HTML except a few formatting tags and plain links."""
    return bleach.clean(text, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)


def get_post(db: Session, post_id: int, detail: str | None = None) -> ForumPost:
    post = forum.get_post(db, post_id)
    if post is None:
        raise NotFound(detail or f"Post with ID {post_id} not found.")
    return post


def create_post(db: Session, user_id: int, title: str, content: str) -> ForumPost:
    post = ForumPost(title=clean(title), content=clean(content), user_id=user_id)
    forum.add(db, post)
    db.commit()
    db.refresh(post)
    return post


def check_vote_type(vote_type: int) -> None:
    if vote_type not in (1, -1):
        raise Invalid("Invalid vote type. Must be 1 (upvote) or -1 (downvote).")


def vote(db: Session, post: ForumPost, user_id: int, vote_type: int) -> ForumPost:
    """One vote per user per post, kept in step with post.upvote_count.

    Same vote again retracts it; the opposite vote flips it (a change of 2).
    """
    existing = forum.get_vote(db, post.id, user_id)
    if existing and existing.vote_type == vote_type:
        forum.remove(db, existing)
        post.upvote_count -= vote_type
    elif existing:
        post.upvote_count += vote_type - existing.vote_type
        existing.vote_type = vote_type
    else:
        forum.add(db, PostVote(post_id=post.id, user_id=user_id, vote_type=vote_type))
        post.upvote_count += vote_type
    db.commit()
    db.refresh(post)
    return post


def check_parent_comment(db: Session, parent_comment_id: int | None) -> None:
    if parent_comment_id and not forum.get_comment(db, parent_comment_id):
        raise NotFound(f"Parent comment with ID {parent_comment_id} not found.")


def add_comment(db: Session, post: ForumPost, user_id: int, content: str, parent_comment_id: int | None) -> ForumComment:
    comment = ForumComment(post_id=post.id, user_id=user_id, content=clean(content), parent_comment_id=parent_comment_id)
    forum.add(db, comment)
    post.comment_count += 1
    db.commit()
    db.refresh(comment)
    return comment


def delete_post(db: Session, post_id: int) -> None:
    """Admins only (enforced by the route). Fails on the forum foreign keys
    if the post still has comments or votes."""
    forum.remove(db, get_post(db, post_id, "Post not found"))
    db.commit()


def delete_comment(db: Session, comment_id: int) -> None:
    comment = forum.get_comment(db, comment_id)
    if not comment:
        raise NotFound("Comment not found")
    post = forum.get_post(db, comment.post_id)
    if post and post.comment_count > 0:
        post.comment_count -= 1
    forum.remove(db, comment)
    db.commit()


def edit_post(db: Session, post_id: int, user_id: int, title: str, content: str) -> ForumPost:
    """Only the author may edit a post."""
    post = get_post(db, post_id)
    if post.user_id != user_id:
        raise Forbidden("Not authorized to edit this post. You must be the author.")
    post.title, post.content = clean(title), clean(content)
    db.commit()
    db.refresh(post)
    return post


def edit_comment(db: Session, comment_id: int, user_id: int, content: str) -> ForumComment:
    """Only the author may edit a comment."""
    comment = forum.get_comment(db, comment_id)
    if comment is None:
        raise NotFound(f"Comment with ID {comment_id} not found.")
    if comment.user_id != user_id:
        raise Forbidden("Not authorized to edit this comment. You must be the author.")
    comment.content = clean(content)
    db.commit()
    db.refresh(comment)
    return comment
