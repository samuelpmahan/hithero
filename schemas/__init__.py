"""API request and response shapes (Pydantic), split out of app.py in BE2-5."""
from schemas.forum import CreatePostRequest, PostDisplay, PostUpdate, VoteInput

__all__ = ["CreatePostRequest", "PostDisplay", "PostUpdate", "VoteInput"]
