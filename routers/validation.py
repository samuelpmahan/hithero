"""Validating new users (teachers in their district, and admins)."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from auth.dependencies import CurrentUser, require_admin, require_member
from auth.session import get_index_cookie, store_my_cookies
from db import get_db
from emails import send_validation_email
from repositories import teachers, users

logger = logging.getLogger("app")
router = APIRouter()


# Endpoint to move a user from new_users to registered_users and delete item in new_users
@router.post("/validation/validate_user/{user_email}")
async def move_user(user_email: str, caller: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    try:
        pending = users.get_pending(db, user_email)
        if not pending:
            raise HTTPException(status_code=404, detail="User not found in new_users")

        # Teachers can only validate users within their own district
        if caller.role == 'teacher':
            teacher_record = teachers.get_by_user_id(db, caller.id)
            if not teacher_record or (
                pending.state != teacher_record.state or
                pending.county != teacher_record.county or
                pending.district != teacher_record.district
            ):
                raise HTTPException(status_code=403, detail="You can only validate teachers in your own district.")

        email = pending.email
        users.promote_pending(db, pending)
        db.commit()
        send_validation_email(email)
        return {"message": "User validated."}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")


def _pending_dict(u) -> dict:
    return {"name": u.name, "email": u.email, "state": u.state, "district": u.district, "school": u.school,
            "phone_number": u.phone_number, "report": u.report, "emailed": u.emailed}


#gets a list of unverified users to validate based on the role of the user
@router.get("/api/validation_list/")
async def validation_page(request: Request, caller: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    role, id = caller.role, caller.id
    try:
        if role == "admin":
            new_users = users.list_pending(db)
            return {"new_users": [_pending_dict(u) for u in new_users], "role": role}
        if role == 'teacher':
            store_my_cookies(request, id, db)
            state = get_index_cookie('state', request)
            county = get_index_cookie('county', request)
            district = get_index_cookie('district', request)
            new_users = users.list_pending_in_district(db, state, county, district)
            return {"new_users": [_pending_dict(u) for u in new_users], "role": role}
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")          

# Endpoint to  users
@router.post("/validation/delete_user/{user_email}")
async def delete_user(user_email: str, caller: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        if not users.email_pending(db, user_email):
            raise HTTPException(status_code=404, detail="User not found in new_users")
        users.delete_pending(db, user_email)
        db.commit()
        return {"message": "User deleted successfully."}
    except Exception as e:
        db.rollback()
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")

# Function to report a user in validation
@router.post("/validation/report_user/{user_email}")
async def report_user(user_email: str, user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    try:
        users.flag_pending(db, user_email, report=1)
        db.commit()
        return {"message": "User reported."}
    except Exception as e:
        db.rollback()
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")

# Endpoint to mark that a new users has been emailed
@router.post("/validation/emailed_user/{user_email}")
async def emailed_user(user_email: str, user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    try:
        users.flag_pending(db, user_email, emailed=1)
        db.commit()
        return {"message": "User emailed."}
    except Exception as e:
        db.rollback()
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")
