"""Errors a service raises when a business rule says no.

They subclass HTTPException so a route can let them through unchanged and
the app's 403/404 pages still apply. Services stay free of request and
session handling; this is the one place they touch FastAPI.
"""

from fastapi import HTTPException


class ServiceError(HTTPException):
    status_code = 400

    def __init__(self, detail: str):
        super().__init__(status_code=self.status_code, detail=detail)


class Invalid(ServiceError):
    status_code = 400


class Forbidden(ServiceError):
    status_code = 403


class NotFound(ServiceError):
    status_code = 404


class Conflict(ServiceError):
    status_code = 409
