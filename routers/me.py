"""The logged-in user's own session info, teacher profile and password."""

import logging
import re
import secrets

import puremagic
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from auth.dependencies import CurrentUser, require_member
from auth.passwords import hash_password, verify_password
from auth.session import get_current_email, get_current_id, get_current_role
from db import get_db
from repositories import teachers, users

logger = logging.getLogger("app")
router = APIRouter()


# Maximum allowed file size in bytes (e.g., 1MB)
MAX_FILE_SIZE = 1 * 1024 * 1024

##this api allows a logged in user to create an item in the table teacher_list in the hithero database if they have not created a user already
@router.post("/profile/create_teacher_profile/")
async def create_teacher_profile(request: Request, name: str = Form(...), state: str = Form(...), county: str = Form(...), district: str = Form(...), school: str = Form(...), aboutMe: str = Form(...), wishlist: str = Form(...), user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    id, role = user.id, user.role
    try:
        create_count = users.create_count(db, id)
        if create_count == 0 or role == 'admin':
            aa_link = wishlist + "&tag=h0mer00mher0-20" 
            email = get_current_email(request)
            first_part_email = email.split('@')[0]
            random_number = secrets.randbelow(9999)
            auto_url_id = f"{first_part_email}{random_number}"
            while teachers.url_id_taken(db, auto_url_id):
                random_number = secrets.randbelow(9999)
                auto_url_id = f"{first_part_email}{random_number}"

            teachers.create(
                db,
                name=name,
                state=state,
                county=county,
                district=district,
                school=school,
                regUserID=id,
                about_me=aboutMe,
                wishlist_url=aa_link,
                url_id=auto_url_id
            )
            users.increment_create_count(db, id)
            db.commit()
            return {"message": "Teacher created successfully", "role": role}
        else:
            return {"message": "Unable to create new profile. Profile already created."}
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")


###api gets the current session info of the logged in user
@router.get("/api/profile/")
async def get_user_profile(email: str = Depends(get_current_email), role: str = Depends(get_current_role), id: str = Depends(get_current_id)):
    if email:
        user_info = {
            "user_id": id,
            "user_role": role,
            "user_email": email
        }
        return JSONResponse(content=user_info)
    else:
        raise HTTPException(status_code=404, detail="No user logged in.")

##api that updates about me info
@router.post("/profile/update_info/")
async def update_info(request: Request, aboutMe: str = Form(...), user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    id = user.id
    try:
        teachers.update_for_user(db, id, about_me=aboutMe)
        db.commit()
        return {"message": "Info updated."}
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")

##api that updates school
@router.post("/profile/update_teacher_school/")
async def update_teacher_school(
    request: Request,
    state: str = Form(...),
    county: str = Form(...),
    district: str = Form(...),
    school: str = Form(...),
    user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)
):
    id = user.id
    try:
        teachers.update_for_user(db, id, state=state, county=county, district=district, school=school)
        db.commit()
        return JSONResponse(content={"message": "School information updated successfully."})
    except Exception as e:
        db.rollback()
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")

##api that updates name
@router.post("/profile/update_teacher_name/")
async def update_teacher_name(request: Request, teacher: str = Form(...), user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    id = user.id
    try:
        teachers.update_for_user(db, id, name=teacher)
        db.commit()
        return {"message": "Name updated."}
    except Exception as e:
        db.rollback()
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")

##api to update wishlist
@router.post("/profile/update_wishlist/")
async def update_wishlist(request: Request, wishlist: str = Form(...), user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    id = user.id
    try:
        aa_link = wishlist + "&tag=h0mer00mher0-20"
        teachers.update_for_user(db, id, wishlist_url=aa_link)
        db.commit()
        return {"message": "Wishlist updated."}
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")


#api that update the url of a teachers page
@router.post("/profile/update_url_id/")
async def update_url_id(request: Request, url_id: str = Form(...), user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    id = user.id
    try:
        if not re.match(r'^[a-zA-Z0-9_-]{3,50}$', url_id):
            raise HTTPException(status_code=400, detail="URL ID may only contain letters, numbers, hyphens, and underscores (3–50 characters).")
        if teachers.url_id_taken(db, url_id):
            raise HTTPException(status_code=409, detail="URL ID already in use.")
        teachers.update_for_user(db, id, url_id=url_id)
        db.commit()
        return {"message": "URL ID updated successfully."}
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")

    
###api used to update the logged in users teacher page image
@router.post("/profile/update_teacher_image/")
async def edit_teacher_image(request: Request, image: UploadFile = Form(...), user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    id = user.id
    try:
        if image.size > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File size exceeds the allowed limit")
        
        # Read bytes once, then use for both magic check and DB storage
        image_bytes = await image.read()
        
        # Validate by actual file signature, not client-supplied content_type
        ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        
        # puremagic has no magic_buffer; magic_string takes bytes and returns
        # matches best first (empty or unreadable input raises PureError/ValueError).
        try:
            results = puremagic.magic_string(image_bytes)
        except (puremagic.PureError, ValueError):
            results = []
        detected_type = results[0].mime_type if results else None

        if detected_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(status_code=400, detail="Invalid file type. Only JPEG, PNG, GIF, and WebP are allowed.")
        
        teachers.update_for_user(db, id, image_data=image_bytes)
        db.commit()
        return {"message": "Information updated."}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")


##api gets your page based on the id in reg_users and and regUserID in teacher_list
@router.get("/profile/myinfo/")
async def get_myinfo(request: Request, id: int = Depends(get_current_id), db: Session = Depends(get_db)):
    try:
        teacher_data = teachers.get_by_user_id(db, id)
        if teacher_data:
            state = teacher_data.state
            county = teacher_data.county
            district = teacher_data.district
            school = teacher_data.school
            name = teacher_data.name
            request.session["state"] = state
            request.session["county"] = county
            request.session["district"] = district
            request.session["school"] = school
            request.session["teacher"] = name
            return {"state": state, "county": county, "district": district, "school": school, "teacher": name}
        else:
            return {"message": "Your account does not have a database listing"}
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")


##api lets the logged in user update their password
@router.post("/profile/update_password/")
async def update_password(request: Request, id: int = Depends(get_current_id), old_password: str = Form(...), new_password: str = Form(...), new_password_confirmed: str = Form(...), db: Session = Depends(get_db)):
    try:
        if new_password == new_password_confirmed:
            old_pass = users.password_hash(db, id)
            if verify_password(old_password, old_pass)[0]:
                hashed_new_password = hash_password(new_password)
                users.set_password_by_id(db, id, hashed_new_password)
                db.commit()
                return {"status": "success", "message": "Password updated successfully"}
            else:
                return {"message": "Invalid old password"}
        else:
            return {"message": "New passwords do not match."}
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")
