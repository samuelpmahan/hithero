"""Forum posts, comments and votes."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Path, Request, status
from sqlalchemy.orm import Session

from auth.dependencies import CurrentUser, require_admin, require_login
from auth.session import get_current_id
from db import get_db
from ratelimit import limiter
from repositories import forum as forum_repo
from schemas import PostUpdate, VoteInput
from services import forum

logger = logging.getLogger("app")
router = APIRouter()


def _failed(db: Session | None, what: str, e: Exception, detail: str) -> HTTPException:
    if db is not None:
        db.rollback()
    logger.error(f"Database error during {what}: {e}")
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail)


def model_to_dict(model):
    """Converts a SQLAlchemy model instance to a dictionary, handling dates for JSON serialization."""
    data = {}
    for column in model.__table__.columns:
        value = getattr(model, column.name)
        data[column.name] = value.isoformat() if hasattr(value, 'isoformat') else value
    return data


@router.post("/forum/create_post")
@limiter.limit("5/minute")
def create_post(request: Request, title: str = Form(...), content: str = Form(...), user: CurrentUser = Depends(require_login), db: Session = Depends(get_db)):
    try:
        return forum.create_post(db, user.id, title, content)
    except Exception as e:
        raise _failed(db, "post creation", e, "Could not create post due to a server error.")


@router.get("/forum/get_posts")
def get_posts(db: Session = Depends(get_db)):
    """
    Retrieves a list of all forum posts.

    The resulting list is ordered by creation date (newest first).
    If you implement an upvote mechanism, you can modify the order_by clause
    to use upvotes first:
    .order_by(ForumPost.upvotes.desc(), ForumPost.created_at.desc())
    """
    try:
        return forum_repo.list_posts(db)
    except Exception as e:
        raise _failed(None, "post retrieval", e, "Could not retrieve posts due to a server error.")


@router.get("/forum/get_post")
def get_post(post_id: int, db: Session = Depends(get_db)):
    """
    Retrieves a single forum post using its unique ID.
    
    Raises HTTPException 404 if the post is not found.
    """
    try:
        return forum.get_post(db, post_id)
    except HTTPException:
        raise
    except Exception as e:
        raise _failed(None, f"single post retrieval (ID: {post_id})", e, "Could not retrieve post due to a server error.")


@router.post("/forum/posts/{post_id}/vote")
def handle_post_vote(post_id: int, vote_data: VoteInput, user: CurrentUser = Depends(require_login), db: Session = Depends(get_db)):
    forum.check_vote_type(vote_data.vote_type)
    post = forum.get_post(db, post_id)
    try:
        return forum.vote(db, post, user.id, vote_data.vote_type)
    except Exception as e:
        raise _failed(db, f"voting operation on post {post_id}", e, "A server error prevented the vote from being recorded.")


@router.post("/forum/posts/{post_id}/comment", summary="Add a new comment to a specific post")
@limiter.limit("5/minute")
def add_comment_to_post(request: Request, post_id: int, content: str = Form(...), parent_comment_id: Optional[int] = Form(None), user: CurrentUser = Depends(require_login), db: Session = Depends(get_db)):
    post = forum.get_post(db, post_id)
    forum.check_parent_comment(db, parent_comment_id)
    try:
        return forum.add_comment(db, post, user.id, content, parent_comment_id)
    except Exception as e:
        raise _failed(db, f"comment creation on post {post_id}", e, "Could not create comment due to a server error.")


@router.get("/forum/comments/{post_id}/")
def get_comments_for_post(post_id: int = Path(..., gt=0), db: Session = Depends(get_db)) -> List[dict]:
    """
    Fetches all comments associated with a specific post, ordered by creation date (newest first).
    """
    forum.get_post(db, post_id)
    try:
        return [model_to_dict(comment) for comment in forum_repo.list_comments(db, post_id)]
    except Exception as e:
        raise _failed(None, f"comment retrieval on post {post_id}", e, "Could not retrieve comments due to a server error.")


@router.delete("/forum/post/{post_id}/delete")
def delete_post(post_id: int, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    """
    Deletes a post. Only allowed for role = 'admin'.
    """
    forum.delete_post(db, post_id)
    return


@router.delete("/forum/comment/{comment_id}/delete")
def delete_comment(comment_id: int, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    """
    Deletes a comment. Only allowed for admin OR the comment's author (not yet but can be if you uncomment below)
    """
    forum.delete_comment(db, comment_id)
    return {"detail": f"Comment ID {comment_id} successfully deleted."}


@router.patch("/forum/post/{post_id}/update")
async def update_post(post_id: int, post_data: PostUpdate, id: int = Depends(get_current_id), db: Session = Depends(get_db)):
    """
    Allows the author of a post to update its title and content.
    """
    try:
        return forum.edit_post(db, post_id, id, post_data.title, post_data.content)
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error during post update.")


@router.patch("/forum/comment/{comment_id}/update")
async def update_comment(comment_id: int, content: str = Form(...), user: int = Depends(get_current_id), db: Session = Depends(get_db)):
    """
    Allows the author of a comment to update its content.
    """
    try:
        return forum.edit_comment(db, comment_id, user, content)
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error during comment update.")
