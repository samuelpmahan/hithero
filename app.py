"""Homeroom Heroes web app: builds the FastAPI app and wires the pieces together.

Azure starts the app as app:app, so this module keeps that name. Routes
live in routers/, queries in repositories/, emails in emails.py and the
scheduled jobs in jobs.py.
"""

import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from config import settings
from db import SessionLocal, engine  # noqa: F401  (SessionLocal: tests open sessions through app)
from models import Base
from ratelimit import limiter
from routers import (
    admin,
    auth,
    forum,
    internal_jobs,
    locations,
    me,
    site,
    teachers,
    validation,
)

logger = logging.getLogger("app")

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, https_only=True)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Disable documentation routes
app.openapi_url = None
app.redoc_url = None

app.mount("/pages", StaticFiles(directory="pages"), name="pages")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Create database tables
Base.metadata.create_all(bind=engine)

for module in (internal_jobs, auth, validation, me, teachers, locations, admin, forum):
    app.include_router(module.router)
app.include_router(site.router)  # last: GET /{token} matches any one-segment path


def _error_page(name: str, status_code: int) -> HTMLResponse:
    with open(os.path.join("pages/", name), "r", encoding="utf-8") as file:
        return HTMLResponse(content=file.read(), status_code=status_code)


@app.exception_handler(404)
async def not_found(request: Request, exc: HTTPException):
    return _error_page("404.html", 404)


@app.exception_handler(403)
async def forbidden(request: Request, exc: HTTPException):
    return _error_page("403.html", 403)


@app.exception_handler(Exception)
async def server_error(request: Request, exc: Exception):
    """The one catch-all: log the failure with the request path, answer 500."""
    logger.error(f"Internal Server Error on {request.method} {request.url.path}: {exc!r}", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
