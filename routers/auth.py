"""Register, log in, log out and password reset."""

import datetime
import logging
import secrets
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth import recaptcha
from auth.passwords import hash_password, verify_password
from config import settings
from db import get_db
from emails import render_email_template, send_email, send_registration_email
from ratelimit import limiter
from repositories import users

logger = logging.getLogger("app")
router = APIRouter()


#######apis#######
###api used to register a new user (and only a new user) into the new_user list
@router.post("/profile/register/")
@limiter.limit("5/minute")
async def register_user(request: Request, name: str = Form(...), email: str = Form(...), phone_number: str = Form(...), password: str = Form(...), confirm_password: str = Form(...), state: str = Form(...),county: str = Form(...),district: str = Form(...), school: str = Form(...), recaptcha_response: str = Form(...), db: Session = Depends(get_db)):
    # Verify reCAPTCHA
    if not recaptcha.verify_recaptcha(recaptcha_response):
        raise HTTPException(status_code=400, detail="reCAPTCHA verification failed. Please try again.")

    try:
        if users.email_registered(db, email):
            return {"message": "User with this email already exists."}
        if users.email_pending(db, email):
            return {"message": "User with this email is already in the registration queue."}
        if password != confirm_password:
            return {"message": "Password do not match."}
        hashed_password = hash_password(password)
        role = 'teacher'
        users.add_pending(db, name=name, email=email, state=state, county=county, district=district, school=school, phone_number=phone_number, password=hashed_password, role=role, report=0, emailed=0)
        db.commit()
        send_registration_email(email)
        return {"message": "User registered successfully. You should recieve an email shortly. Please check your spam folder"}
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        return {"message": "Registration unsuccessful. Please try again later."}

    
###api used to create cookie based session via authentication with registered_user table
@router.post("/profile/login/")
@limiter.limit("5/minute")
async def login_user(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    try:
        user = users.get_by_email(db, email)
        if user:
            ok, upgraded_hash = verify_password(password, user.password)
            if ok:
                if upgraded_hash:
                    # Move legacy sha256_crypt hashes to argon2 on login. A
                    # failed save must not block the login itself.
                    try:
                        users.set_password_by_id(db, user.id, upgraded_hash)
                        db.commit()
                    except Exception as e:
                        db.rollback()
                        logger.warning(f"Password hash upgrade failed for user {user.id}: {e}")
                message = "Login successful as " + user.role
                request.session["user_email"] = email
                request.session["user_role"] = user.role
                request.session["user_id"] = user.id
                return JSONResponse(content={"message": message, "createCount": user.createCount, "role": user.role})
            else:
                message = "Invalid login credentials."
        else:
            message = "Invalid login credentials."
        return JSONResponse(content={"message": message})
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")

##end cookie session
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
        if users.email_registered(db, email):
            # Generate a secure token
            token = secrets.token_urlsafe(32)
            expires_at = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
            # Store the token
            users.add_reset_token(db, email, token, expires_at)
            db.commit()
            # Send email with link instead of temp password
            reset_link = f"{settings.base_url}/pages/reset_password.html?token={token}"
            template_data = {
                'recipient_name': email,
                'message_body': (
                    f"We received a request to reset your password. "
                    f"Click the link below to reset it (expires in 1 hour):\n\n"
                    f"{reset_link}\n\n"
                    f"If you did not request this, you can ignore this email."
                )
            }
            html_message = render_email_template('static/email_template.html', template_data)
            plain_message = f"Dear {email},\n\nReset your password here: {reset_link}\n\nExpires in 1 hour."
            send_email(email, 'Password Reset Request', html_message, plain_message)
        else:
            time.sleep(1)
        return JSONResponse(content={"message": "If an account exists, a reset link will be sent to your email."})
    except Exception as e:
        db.rollback()
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")
    
@router.post("/profile/reset_password/")
async def reset_password(token: str = Form(...), new_password: str = Form(...), confirm_password: str = Form(...), db: Session = Depends(get_db)):
    try:
        if new_password != confirm_password:
            raise HTTPException(status_code=400, detail="Passwords do not match.")
        # Look up the token
        reset = users.get_usable_reset_token(db, token, datetime.datetime.utcnow())
        if not reset:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token.")
        # Update the password
        hashed = hash_password(new_password)
        users.set_password_by_email(db, reset.email, hashed)
        # Mark token as used
        reset.used = 1
        db.commit()
        return JSONResponse(content={"message": "Password reset successfully. You can now log in."})
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")
