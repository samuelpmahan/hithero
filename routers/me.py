"""The logged-in user's own session info, teacher profile and password."""

import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from auth.dependencies import CurrentUser, require_member
from auth.session import get_current_email, get_current_id, get_current_role
from db import get_db
from repositories import teachers
from services import accounts, profiles

logger = logging.getLogger("app")
router = APIRouter()


def _server_error(e: Exception) -> HTTPException:
    logger.error(f"Internal Server Error: {str(e)}")
    return HTTPException(status_code=500, detail="Internal Server Error")


@router.post("/profile/create_teacher_profile/")
async def create_teacher_profile(request: Request, name: str = Form(...), state: str = Form(...), county: str = Form(...), district: str = Form(...), school: str = Form(...), aboutMe: str = Form(...), wishlist: str = Form(...), user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    try:
        created = profiles.create(db, user, get_current_email(request), name=name, state=state, county=county,
                                  district=district, school=school, about_me=aboutMe, wishlist=wishlist)
    except Exception as e:
        raise _server_error(e)
    if not created:
        return {"message": "Unable to create new profile. Profile already created."}
    return {"message": "Teacher created successfully", "role": user.role}


@router.get("/api/profile/")
async def get_user_profile(email: str = Depends(get_current_email), role: str = Depends(get_current_role), id: str = Depends(get_current_id)):
    if not email:
        raise HTTPException(status_code=404, detail="No user logged in.")
    return JSONResponse(content={"user_id": id, "user_role": role, "user_email": email})


@router.post("/profile/update_info/")
async def update_info(request: Request, aboutMe: str = Form(...), user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    try:
        profiles.update(db, user.id, about_me=aboutMe)
    except Exception as e:
        raise _server_error(e)
    return {"message": "Info updated."}


@router.post("/profile/update_teacher_school/")
async def update_teacher_school(
    request: Request,
    state: str = Form(...),
    county: str = Form(...),
    district: str = Form(...),
    school: str = Form(...),
    user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)
):
    try:
        profiles.update(db, user.id, state=state, county=county, district=district, school=school)
    except Exception as e:
        db.rollback()
        raise _server_error(e)
    return JSONResponse(content={"message": "School information updated successfully."})


@router.post("/profile/update_teacher_name/")
async def update_teacher_name(request: Request, teacher: str = Form(...), user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    try:
        profiles.update(db, user.id, name=teacher)
    except Exception as e:
        db.rollback()
        raise _server_error(e)
    return {"message": "Name updated."}


@router.post("/profile/update_wishlist/")
async def update_wishlist(request: Request, wishlist: str = Form(...), user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    try:
        profiles.set_wishlist(db, user.id, wishlist)
    except Exception as e:
        raise _server_error(e)
    return {"message": "Wishlist updated."}


@router.post("/profile/update_url_id/")
async def update_url_id(request: Request, url_id: str = Form(...), user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    try:
        profiles.set_url_id(db, user.id, url_id)
    except HTTPException:
        raise
    except Exception as e:
        raise _server_error(e)
    return {"message": "URL ID updated successfully."}


@router.post("/profile/update_teacher_image/")
async def edit_teacher_image(request: Request, image: UploadFile = Form(...), user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    try:
        profiles.check_image_size(image.size)
        profiles.set_image(db, user.id, await image.read())
    except HTTPException:
        raise
    except Exception as e:
        raise _server_error(e)
    return {"message": "Information updated."}


@router.get("/profile/myinfo/")
async def get_myinfo(request: Request, id: int = Depends(get_current_id), db: Session = Depends(get_db)):
    try:
        teacher = teachers.get_by_user_id(db, id)
    except Exception as e:
        raise _server_error(e)
    if not teacher:
        return {"message": "Your account does not have a database listing"}
    info = {"state": teacher.state, "county": teacher.county, "district": teacher.district,
            "school": teacher.school, "teacher": teacher.name}
    request.session.update(info)
    return info


@router.post("/profile/update_password/")
async def update_password(request: Request, id: int = Depends(get_current_id), old_password: str = Form(...), new_password: str = Form(...), new_password_confirmed: str = Form(...), db: Session = Depends(get_db)):
    if new_password != new_password_confirmed:
        return {"message": "New passwords do not match."}
    try:
        changed = accounts.change_password(db, id, old_password, new_password)
    except Exception as e:
        raise _server_error(e)
    if not changed:
        return {"message": "Invalid old password"}
    return {"status": "success", "message": "Password updated successfully"}
