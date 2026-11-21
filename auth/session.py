"""Session-cookie helpers: who is logged in, and the teacher page they last opened."""


from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from repositories import teachers


#########functions############
def get_current_id(request: Request):
    return request.session.get("user_id", None)

def get_current_role(request: Request):
    return request.session.get("user_role", None)

def get_current_email(request: Request):
    return request.session.get("user_email", None)

def get_index_cookie(index: str, request: Request):
    return request.session.get(index, None)

def store_my_cookies(request: Request, id: int, db: Session):
    teacher = teachers.get_by_user_id(db, id)
    if teacher:
        name, state, county, district, school = teacher.name, teacher.state, teacher.county, teacher.district, teacher.school
        request.session["state"] = state
        request.session["county"] = county
        request.session["district"] = district
        request.session["school"] = school
        request.session["teacher"] = name
    else:
        raise HTTPException(status_code=404, detail="Your account does not have a database listing")
