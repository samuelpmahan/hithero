"""Who is calling, and whether they may (BE3-1).

Login state lives in the signed session cookie set by /profile/login/.
Routes declare what they need instead of checking role strings:

    user: CurrentUser = Depends(require_login)              # any logged-in user, else 401
    user: CurrentUser = Depends(require_role("admin"))      # else 403
    user: CurrentUser = Depends(require_role("admin", "teacher"))

Routes still compare roles where the behaviour differs by role (for
example a teacher may only validate people in their own district).
"""
from dataclasses import dataclass

from fastapi import HTTPException, Request, status


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str
    role: str


def current_user(request: Request) -> CurrentUser | None:
    session = request.session
    if session.get("user_id") is None or not session.get("user_role"):
        return None
    return CurrentUser(id=session["user_id"], email=session.get("user_email"), role=session["user_role"])


def require_login(request: Request) -> CurrentUser:
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="You must be logged in.")
    return user


def require_role(*roles: str):
    def dependency(request: Request) -> CurrentUser:
        user = current_user(request)
        if user is None or user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")
        return user

    dependency.__name__ = f"require_role_{'_'.join(roles)}"
    return dependency


require_admin = require_role("admin")
require_member = require_role("admin", "teacher")
