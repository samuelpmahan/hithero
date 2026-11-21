"""Public teacher pages: lookup, random teacher, teacher of the day, search."""

import base64

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from auth.dependencies import CurrentUser, require_role
from auth.session import get_index_cookie
from config import settings
from db import get_db
from jobs import fetch_random_teacher
from repositories import teachers

router = APIRouter()


##api gets a random teacher from the list teacher_list in the hithero data base

@router.get("/api/random_teacher/")
async def get_random_teacher(request: Request, db: Session = Depends(get_db)):
    teacher = fetch_random_teacher(db)
    if not teacher:
        raise HTTPException(status_code=404, detail="No teachers found in the database")
    if teacher.image_data:
        image_data = base64.b64encode(teacher.image_data).decode('utf-8')
    else:
        image_data = None
    data = {
        "name": teacher.name,
        "state": teacher.state,
        "county": teacher.county,
        "district": teacher.district,
        "school": teacher.school,
        "image_data": image_data
    }
    if hasattr(request, "session"):
        request.session["state"] = data["state"]
        request.session["county"] = data["county"]
        request.session["district"] = data["district"]
        request.session["school"] = data["school"]
        request.session["teacher"] = data["name"]
    return data

###api gets a teacher data from teacher_list table
@router.get("/api/get_teacher_info/")
async def get_teacher_info(request: Request, db: Session = Depends(get_db)):
    state = get_index_cookie('state', request)
    county = get_index_cookie('county', request)
    district = get_index_cookie('district', request)
    school = get_index_cookie('school', request)
    name = get_index_cookie('teacher', request)
    teacher_info = teachers.get_by_location_and_name(db, state, county, district, school, name)
    if teacher_info:
        if teacher_info.image_data:
            image_data = base64.b64encode(teacher_info.image_data).decode('utf-8')
        else:
            image_data = None
        data = {
            "state": teacher_info.state,
            "county": teacher_info.county,
            "district": teacher_info.district,
            "school": teacher_info.school,
            "name": teacher_info.name,
            "wishlist_url": teacher_info.wishlist_url,
            "about_me": teacher_info.about_me,
            "image_data": image_data
        }
        return data
    else:
        raise HTTPException(status_code=404, detail="Teacher not found")


#api to check if a user has edit acces to teacher page
@router.get("/api/check_access_teacher/")
async def check_access_teacher(request: Request, user: CurrentUser = Depends(require_role("teacher")), db: Session = Depends(get_db)):
    state = get_index_cookie('state', request)
    county = get_index_cookie('county', request)
    district = get_index_cookie('district', request)
    school = get_index_cookie('school', request)
    name = get_index_cookie('teacher', request)
    teacher = teachers.get_by_location_and_name(db, state, county, district, school, name)
    if teacher is not None and teacher.regUserID == user.id:
        return {"status": "success", "message": "Access granted"}
    raise HTTPException(status_code=403, detail="No access")

#api that gets today's Teacher of the Day (whoever has the most recent last_TOD)
@router.get("/api/teacher_of_the_day")
async def get_teacher_of_the_day(request: Request, db: Session = Depends(get_db)):
    data = teachers.latest_teacher_of_the_day(db)
    if data:
        if data.image_data:
            image_data = base64.b64encode(data.image_data).decode('utf-8')
        else:
            image_data = None
        request.session['state'] = data.state
        request.session['county'] = data.county
        if data.district:
            request.session['district'] = data.district
        if data.school:
            request.session['school'] = data.school
            request.session['teacher'] = data.name
        data_dict = {
            "state": data.state,
            "county": data.county,
            "district": data.district,
            "school": data.school,
            "name": data.name,
            "image_data": image_data,
            "url_id": data.url_id
        }
        return data_dict
    else:
        raise HTTPException(status_code=404, detail="Teacher of the Day not found")

###api to get a link for the url to your page to share
@router.get("/api/teacher_url/")
async def get_teacher_url(request: Request, db: Session = Depends(get_db)):
    state = get_index_cookie('state', request)
    county = get_index_cookie('county', request)
    district = get_index_cookie('district', request)
    school = get_index_cookie('school', request)
    name = get_index_cookie('teacher', request)
    teacher = teachers.get_by_location_and_name(db, state, county, district, school, name)
    if not teacher:
        raise HTTPException(status_code=404, detail="No matching teacher found")
    url = f"{settings.display_host}/teacher/" + teacher.url_id
    return {"url": url}  # Return as JSON

##this api gets the token, gets the data, sets the data, then redirects
@router.get("/teacher/{url_id}")
async def open_teacher_page(url_id: str, request: Request, db: Session = Depends(get_db)):
    teacher_info = teachers.get_by_url_id(db, url_id)
    if not teacher_info:
        return RedirectResponse(url="/pages/404.html")
    request.session['state'] = teacher_info.state
    request.session['county'] = teacher_info.county
    request.session['district'] = teacher_info.district
    request.session['school'] = teacher_info.school
    request.session['teacher'] = teacher_info.name
    return RedirectResponse(url="/pages/teacher.html")

###api gets the teachers and their url_id for the index
@router.post("/api/index_teachers/")
async def index_teachers(state: str = Form(...),county: str = Form(None),district: str = Form(None),school: str = Form(None), db: Session = Depends(get_db)):
    matches = teachers.search(db, state, county, district, school)

    if matches:
        return [{"name": teacher.name, "url_id": teacher.url_id} for teacher in matches]
    else:
        raise HTTPException(
            status_code=404,
            detail="No teachers found with the given criteria."
        )
