"""Register, log in, log out and password reset."""

import logging
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import recaptcha
from db import get_db
from ratelimit import limiter
from services import accounts

logger = logging.getLogger("app")
router = APIRouter()


@router.post("/profile/register/")
@limiter.limit("5/minute")
async def register_user(request: Request, name: str = Form(...), email: str = Form(...), phone_number: str = Form(...), password: str = Form(...), confirm_password: str = Form(...), state: str = Form(...),county: str = Form(...),district: str = Form(...), school: str = Form(...), recaptcha_response: str = Form(...), db: Session = Depends(get_db)):
    if not recaptcha.verify_recaptcha(recaptcha_response):
        raise HTTPException(status_code=400, detail="reCAPTCHA verification failed. Please try again.")
    try:
        message = accounts.register(db, name=name, email=email, phone_number=phone_number, password=password,
                                    confirm_password=confirm_password, state=state, county=county, district=district, school=school)
        return {"message": message}
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        return {"message": "Registration unsuccessful. Please try again later."}


@router.post("/profile/login/")
@limiter.limit("5/minute")
async def login_user(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    try:
        user = accounts.authenticate(db, email, password)
        if not user:
            return JSONResponse(content={"message": "Invalid login credentials."})
        request.session["user_email"] = email
        request.session["user_role"] = user.role
        request.session["user_id"] = user.id
        return JSONResponse(content={"message": "Login successful as " + user.role, "createCount": user.createCount, "role": user.role})
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post("/profile/logout/")
async def logout_user(request: Request):
    if "user_id" in request.session:
        del request.session["user_id"]
        del request.session["user_role"]
        del request.session["user_email"]
    return RedirectResponse(url="/", status_code=303)


@router.post("/profile/forgot_password/")
@limiter.limit("5/minute")
async def forgot_password(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    try:
        if not accounts.request_password_reset(db, email):
            time.sleep(1)  # unknown address: take about as long, answer the same
        return JSONResponse(content={"message": "If an account exists, a reset link will be sent to your email."})
    except Exception as e:
        db.rollback()
        logger.error(f"Internal Server Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


@router.post("/profile/reset_password/")
async def reset_password(token: str = Form(...), new_password: str = Form(...), confirm_password: str = Form(...), db: Session = Depends(get_db)):
    try:
        accounts.reset_password(db, token, new_password, confirm_password)
        return JSONResponse(content={"message": "Password reset successfully. You can now log in."})
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Internal Server Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
