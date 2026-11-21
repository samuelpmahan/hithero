"""Forum posts, comments and votes."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func

from models.base import Base


class ForumPost(Base):
    __tablename__ = "forum_posts"

    # Core Post Data
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    content = Column(String, nullable=False)
    
    # User and Timestamp
    user_id = Column(Integer, ForeignKey("registered_users.id"), nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    
    # Denormalized/Cached Metrics (for fast sorting/display)
    upvote_count = Column(Integer, default=0, nullable=False)
    comment_count = Column(Integer, default=0, nullable=False)


class ForumComment(Base):
    __tablename__ = "forum_comments"

    # Core Comment Data
    id = Column(Integer, primary_key=True)
    content = Column(String, nullable=False)
    
    # Relationships
    post_id = Column(Integer, ForeignKey("forum_posts.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("registered_users.id"), nullable=False)
    
    # Hierarchy and Timestamp
    parent_comment_id = Column(Integer, ForeignKey("forum_comments.id"), nullable=True) # For nested replies
    created_at = Column(DateTime, default=func.now(), nullable=False)


class PostVote(Base):
    __tablename__ = "post_votes"

    # Core Vote Data
    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("forum_posts.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("registered_users.id"), nullable=False)
    
    # 1 for Upvote, -1 for Downvote
    vote_type = Column(Integer, nullable=False) 

    # Enforce uniqueness: a user can only vote on a post once
    __table_args__ = (UniqueConstraint('post_id', 'user_id', name='uq_post_user_vote'), )
