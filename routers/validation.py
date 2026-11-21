"""Validating new users (teachers in their district, and admins)."""


from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from auth.dependencies import CurrentUser, require_admin, require_member
from auth.session import get_index_cookie, store_my_cookies
from db import get_db
from services import validation

router = APIRouter()


@router.post("/validation/validate_user/{user_email}")
async def move_user(user_email: str, caller: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    validation.validate(db, caller, user_email)
    return {"message": "User validated."}


@router.get("/api/validation_list/")
async def validation_page(request: Request, caller: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    if caller.role == "teacher":
        # Also refreshes the teacher's location in the session (500 if they have no page).
        store_my_cookies(request, caller.id, db)
    new_users = validation.pending_for(
        db, caller.role, get_index_cookie("state", request), get_index_cookie("county", request),
        get_index_cookie("district", request))
    if new_users is None:
        return None
    return {"new_users": new_users, "role": caller.role}


@router.post("/validation/delete_user/{user_email}")
async def delete_user(user_email: str, caller: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    validation.delete(db, user_email)
    return {"message": "User deleted successfully."}


@router.post("/validation/report_user/{user_email}")
async def report_user(user_email: str, user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    validation.flag(db, user_email, report=1)
    return {"message": "User reported."}


@router.post("/validation/emailed_user/{user_email}")
async def emailed_user(user_email: str, user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    validation.flag(db, user_email, emailed=1)
    return {"message": "User emailed."}
