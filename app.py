from fastapi import FastAPI, HTTPException, Request, Form, Depends, Body, File, UploadFile, Response, status, Path
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, FileResponse, StreamingResponse
from pydantic import BaseModel, Field
import os, logging, smtplib, secrets, string, pyodbc, time, ssl, datetime, base64, requests, threading
from auth.dependencies import CurrentUser, require_admin, require_login, require_member, require_role
from config import settings
from db import SessionLocal, engine, get_db
from models import Base, ForumComment, ForumPost, PostVote
from schemas import CreatePostRequest, PostDisplay, PostUpdate, VoteInput
from repositories import forum, schools, teachers, users
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.applications import Starlette
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import FileResponse
from passlib.hash import sha256_crypt
from sqlalchemy.orm import Session
from typing import Optional, List
from azure.communication.email import EmailClient
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import bleach, puremagic, re, io
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

app = FastAPI()
logger = logging.getLogger(__name__)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, https_only=True)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)
RECAPTCHA_SECRET_KEY = settings.server_key_captcha

##limiter
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Disable documentation routes
app.openapi_url = None
app.redoc_url = None

###content cleanup and formatting for forum
ALLOWED_TAGS = ["b", "i", "em", "strong", "a", "p", "br"]
ALLOWED_ATTRS = {"a": ["href"]}

# Determine the path to the directory
app.mount("/pages", StaticFiles(directory="pages"), name="pages")
app.mount("/static", StaticFiles(directory="static"), name="static")
BASE_STATIC_DIR = "static"

ADS_TXT_PATH = f"{BASE_STATIC_DIR}/ads.txt"
SITEMAP_XML_PATH = f"{BASE_STATIC_DIR}/sitemap.xml"

# 1. Route for ads.txt (media_type='text/plain')
@app.get("/ads.txt", include_in_schema=False)
async def get_ads_txt():
    """Serves ads.txt from the static folder at the root URL."""
    return FileResponse(ADS_TXT_PATH, media_type='text/plain')

# 2. Route for sitemap.xml (media_type='application/xml')
@app.get("/sitemap.xml", include_in_schema=False)
async def get_sitemap_xml():
    """Serves sitemap.xml from the static folder at the root URL."""
    return FileResponse(SITEMAP_XML_PATH, media_type='application/xml')

# --- Configuration for Promotional Images Mapping ---
PROMO_IMAGE_MAPPING = settings.promo_images

###cronjob ip white list
CRONJOB_ALLOWED_IPS = {
    "116.203.129.16",
    "116.203.134.67",
    "23.88.105.37",
    "128.140.8.200",
    "91.99.23.109",
}


# Maximum allowed file size in bytes (e.g., 1MB)
MAX_FILE_SIZE = 1 * 1024 * 1024

# Create database tables
Base.metadata.create_all(bind=engine)


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
    try:
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
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")

def render_email_template(template_path: str, data: dict) -> str:
    """
    Loads an HTML template and replaces placeholders with provided data.
    """
    with open(template_path, 'r', encoding='utf-8') as f:
        template_content = f.read()

    # Replace placeholders with data values
    for key, value in data.items():
        template_content = template_content.replace(f'{{{{ {key} }}}}', str(value))
    
    return template_content

def send_email(recipient_email: str, subject: str, html_message: str, plain_message: str): ###AZURE REPLACEMENT###
    """
    Sends an email using Azure Communication Services Email.
    """
    try:
        connection_string = settings.azure_email_connection_string
        sender_address = settings.azure_email_sender

        client = EmailClient.from_connection_string(connection_string)

        message = {
            "senderAddress": sender_address,
            "recipients": {
                "to": [{"address": recipient_email}]
            },
            "content": {
                "subject": subject,
                "html": html_message,
                "plainText": plain_message
            }
        }

        poller = client.begin_send(message)
        result = poller.result()

        print("Azure email sent:", result)
        return True

    except Exception as ex:
        print("Azure email error:", ex)
        return False

def send_registration_email(recipient_email: str):
    """
    Prepares and sends the registration success email using the HTML template.
    """
    # Define the data to populate the template
    template_data = {
        'recipient_name': recipient_email,
        'message_body': (
            "Thank you for registering with us! Once you are validated by a "
            "fellow teacher in your district or one of us here at Homeroom Heroes, "
            "you will be able to create your profile and start receiving support."
        )
    }

    # Generate the HTML message from the template
    html_message = render_email_template('static/email_template.html', template_data)

    # Create a plain text fallback version
    plain_message = (
        f"Dear {template_data['recipient_name']},\n\n"
        f"{template_data['message_body']}\n\n"
        "Best regards,\nHomeroom Heroes Team\nhomeroom.heroes.contact@gmail.com\nhomeroom.heroes.contact@gmail.com"
    )

    # Call the core send_email function
    send_email(
        recipient_email,
        "Registration successful",
        html_message,
        plain_message
    )

def send_validation_email(recipient_email: str):
    """
    Prepares and sends the validation success email using the HTML template.
    """
    # Define the data to populate the template
    template_data = {
        'recipient_name': recipient_email,
        'message_body': (
            "We are pleased to inform you that your registration with us has been "
            "successfully validated! You may now log in and create your profile "
            "to start receiving support."
        )
    }

    # Generate the HTML message from the template
    html_message = render_email_template('static/email_template.html', template_data)

    # Create a plain text fallback version
    plain_message = (
        f"Dear {template_data['recipient_name']},\n\n"
        f"{template_data['message_body']}\n\n"
        "If you have any questions or need assistance, please do not hesitate to contact us.\n\n"
        "Best regards,\nHomeroom Heroes Team\nhomeroom.heroes.contact@gmail.com"
    )

    # Call the core send_email function
    send_email(
        recipient_email,
        "Validation Notification",
        html_message,
        plain_message
    )

# Function to fetch a random teacher from the database
def fetch_random_teacher(db: Session):
    try:
        return teachers.random_teacher(db)
    except Exception as e:
        print(f"Error fetching random teacher: {e}")
        return None

def fetch_teacher_for_tod(db: Session):
    """
    Picks the next Teacher of the Day.

    Repeatedly calls fetch_random_teacher() and checks the returned
    teacher's last_TOD against a 90-day cutoff, until it finds someone
    who either has never been featured (last_TOD is NULL) or wasn't
    featured in the last 90 days. Does not mutate any data - the caller
    is responsible for stamping last_TOD once the pick is finalized.
    """
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=90)
    while True:
        candidate = fetch_random_teacher(db)
        if candidate is None:
            # No teachers at all in teacher_list.
            return None
        if candidate.last_TOD is None or candidate.last_TOD < cutoff:
            return candidate
        # Otherwise loop and try again - candidate was featured too recently.

def send_teacher_of_the_day_email(recipient_email: str, recipient_name: str, url_id: str):
    """
    Prepares and sends the 'Teacher of the Day' notification email.
    """
    # Define the data to populate the template
    template_data = {
        'recipient_name': recipient_name,
        'message_body': (
            "Congratulations! You've been chosen as today's 'Teacher of the Day' at Homeroom Heroes! "
            "Your profile is now featured on our homepage, giving you extra visibility. "
            "Remember to share your unique page with your community. "
            f"{settings.display_host}/teacher/{url_id}"
        )
    }

    # Generate the HTML message from the template
    html_message = render_email_template('static/email_template.html', template_data)

    # Create a plain text fallback version
    plain_message = (
        f"Dear {template_data['recipient_name']},\n\n"
        f"{template_data['message_body']}\n\n"
        "Best regards,\nHomeroom Heroes Team\nhomeroom.heroes.contact@gmail.com"
    )

    # Call the core send_email function
    send_email(
        recipient_email,
        "🎉 You're Today's Homeroom Hero!",
        html_message,
        plain_message
    )

def daily_job():
    db = SessionLocal()
    try:
        # Picks a teacher who hasn't been Teacher of the Day in the last 90 days
        chosen_teacher = fetch_teacher_for_tod(db)

        if chosen_teacher:
            teacher_info = {
                "name": chosen_teacher.name,
                "state": chosen_teacher.state,
                "county": chosen_teacher.county,
                "district": chosen_teacher.district,
                "school": chosen_teacher.school,
                "image_data": chosen_teacher.image_data,
                "url_id": chosen_teacher.url_id
            }

            # Stamp last_TOD on the chosen teacher so they're excluded from
            # selection for the next 90 days.
            teachers.stamp_teacher_of_the_day(db, chosen_teacher.id, datetime.datetime.utcnow())
            db.commit()

            # Now, attempt to fetch the email and send the notification
            teacher_email = users.email_by_id(db, chosen_teacher.regUserID)

            if teacher_email:
                # Send the email notification
                send_teacher_of_the_day_email(
                    recipient_email=teacher_email,
                    recipient_name=teacher_info["name"],
                    url_id=teacher_info["url_id"]
                )
            else:
                print(f"No email found for teacher: {chosen_teacher.name}. last_TOD updated, but no email sent.")
        else:
            print("No eligible teacher found.")
    except Exception as e:
        db.rollback()
        print(f"Error in daily_job: {e}")
    finally:
        db.close()

def wednesday_job():
    db = SessionLocal()
    try:
        # 1. Find all districts with pending teachers
        pending_groups = users.pending_districts(db)
        for state, county, district in pending_groups:
            # 2. Find validated teachers in this district (recipients)
            recipient_emails = users.teacher_emails_in_district(db, state, county, district)
            if not recipient_emails:
                print(f"No validated teachers found for {district}. Skipping.")
                continue
            # 3. Get pending teachers in this district
            pending_teachers = users.list_pending_in_district(db, state, county, district)
            if not pending_teachers:
                continue
            # 4. Build email body
            teacher_lines = [
                f"- {t.name} ({t.school})"
                for t in pending_teachers
            ]
            email_body = (
                f"Hello,\n\n"
                f"The following teachers in {district} are waiting to be validated:\n\n"
                + "\n".join(teacher_lines)
                + "\n\nPlease log in to validate them.\n\n"
                "Thank you!"
            )
            # 5. Send the email
            try:
                for email in recipient_emails:
                    template_data = {
                        'recipient_name': email,
                        'message_body': email_body
                    }
                    html_message = render_email_template('static/email_template.html', template_data)
                    plain_message = (
                        f"Dear {email},\n\n"
                        f"{email_body}\n\n"
                        "Best regards,\nHomeroom Heroes Team\nhomeroom.heroes.contact@gmail.com"
                    )
                    send_email(
                        email,
                        f"Pending Teachers in {district} Need Validation",
                        html_message,
                        plain_message
                    )
                print(f"Sent validation email to {district} ({len(recipient_emails)} recipients).")
            except Exception as e:
                print(f"Failed to send email for {district}: {e}")
                continue
    except Exception as e:
        print(f"Error in wednesday_validation_job: {e}")
    finally:
        db.close()

######   EMAILER FUNCTIONS FOR CRONJOBS  ###########
def verify_cronjob_request(request: Request):
    secret = request.headers.get("x-secret-key")
    if not secret or secret != settings.internal_job_secret:
        raise HTTPException(status_code=403, detail="Forbidden")

@app.post("/internal/run-wednesday-job")
async def run_wednesday_job(request: Request, _: None = Depends(verify_cronjob_request)):
    threading.Thread(target=wednesday_job, daemon=True).start()
    return {"status": "wednesday job started"}

@app.post("/internal/run-tuesday-job")
async def run_tuesday_job(request: Request, _: None = Depends(verify_cronjob_request)):
    threading.Thread(target=tuesday_job, daemon=True).start()
    return {"status": "tuesday job started"}

@app.post("/internal/run-thursday-job")
async def run_thursday_job(request: Request, _: None = Depends(verify_cronjob_request)):
    threading.Thread(target=thursday_job, daemon=True).start()
    return {"status": "thursday job started"}

@app.post("/internal/run-daily-job")
async def run_daily_job(request: Request, _: None = Depends(verify_cronjob_request)):
    threading.Thread(target=daily_job, daemon=True).start()
    return {"status": "daily job started"}


#####################################################



def verify_recaptcha(recaptcha_response: str):
    """Verifies the reCAPTCHA response with Google's servers."""
    url = "https://www.google.com/recaptcha/api/siteverify"
    params = {"secret": RECAPTCHA_SECRET_KEY, "response": recaptcha_response}
    response = requests.post(url, params=params)
    data = response.json()
    return data["success"]

def send_profile_creation_reminders():
    """
    Checks the RegisteredUsers table and sends a profile creation reminder
    email to all users who have not yet created a profile.
    """
    db = SessionLocal()
    try:
        recipients = users.without_profile(db)

        if recipients:
            print(f"Found {len(recipients)} users who need a profile reminder.")
            for user in recipients:
                send_profile_reminder_email(user.email)
            print("Successfully sent all profile creation reminder emails.")
        else:
            print("No users found with a createCount of 0.")
    except Exception as e:
        print(f"An error occurred while sending profile reminders: {str(e)}")
    finally:
        db.close()

def send_profile_reminder_email(recipient_email: str):
    """
    Sends a reminder email to a user to complete their profile.
    """
    # Define the data to populate the template
    template_data = {
        'recipient_name': recipient_email,
        'message_body': (
            "You're almost there! Your registration with us has been "
            "successfully validated, but you haven't created your profile yet. "
            "Please log in and complete your profile to start receiving support from our community.\n"
            f"{settings.display_host}/pages/login.html"
        )
    }

    # Generate the HTML message from the template
    html_message = render_email_template('static/email_template.html', template_data)

    # Create a plain text fallback version
    plain_message = (
        f"Dear {template_data['recipient_name']},\n\n"
        f"{template_data['message_body']}\n\n"
        "If you have any questions or need assistance, please do not hesitate to contact us.\n\n"
        "Best regards,\nHomeroom Heroes Team\nhomeroom.heroes.contact@gmail.com"
    )

    # Call the core send_email function
    send_email(
        recipient_email,
        "Reminder: Complete Your Homeroom Heroes Profile!",
        html_message,
        plain_message
    )

def tuesday_job():
    send_profile_creation_reminders()
    print("Tuesday job to send profile creation reminders has completed.")


def send_validation_reminder_emails():
    """
    Checks the NewUsers table and sends a validation reminder
    email to all users who have not been validated and have  been emailed yet.
    """
    db = SessionLocal()
    try:
        recipients = users.list_pending(db)

        if recipients:
            print(f"Found {len(recipients)} new users who need a validation reminder.")
            for user in recipients:
                send_validation_reminder_email(user.email)
            print("Successfully sent all new user validation reminder emails.")
        else:
            print("No new users found who need a validation reminder.")
    except Exception as e:
        print(f"An error occurred while sending new user reminders: {str(e)}")
    finally:
        db.close()

def send_validation_reminder_email(recipient_email: str):
    """
    Sends a reminder email to a new user to reach out for validation.
    """
    # Define the data to populate the template
    template_data = {
        'recipient_name': recipient_email,
        'message_body': (
            "Thanks for signing up! We noticed you haven't been validated yet. "
            "Please reach back out to us at homeroom.heroes.contact@gmail.com to complete your validation process."
        )
    }

    # Generate the HTML message from the template
    html_message = render_email_template('static/email_template.html', template_data)

    # Create a plain text fallback version
    plain_message = (
        f"Dear {template_data['recipient_name']},\n\n"
        f"{template_data['message_body']}\n\n"
        "Best regards,\nHomeroom Heroes Team\nhomeroom.heroes.contact@gmail.com"
    )

    # Call the core send_email function
    send_email(
        recipient_email,
        "Reminder: Complete Your Homeroom Heroes Validation!",
        html_message,
        plain_message
    )

def thursday_job():
    send_validation_reminder_emails()
    print("Thursday job to send new user validation reminders has completed.")

def model_to_dict(model):
    """Converts a SQLAlchemy model instance to a dictionary, handling dates for JSON serialization."""
    data = {}
    for column in model.__table__.columns:
        value = getattr(model, column.name)
        # Convert datetime objects to ISO format string
        if hasattr(value, 'isoformat'):
            data[column.name] = value.isoformat()
        else:
            data[column.name] = value
    return data


#######apis#######
###api used to register a new user (and only a new user) into the new_user list
@app.post("/profile/register/")
@limiter.limit("5/minute")
async def register_user(request: Request, name: str = Form(...), email: str = Form(...), phone_number: str = Form(...), password: str = Form(...), confirm_password: str = Form(...), state: str = Form(...),county: str = Form(...),district: str = Form(...), school: str = Form(...), recaptcha_response: str = Form(...), db: Session = Depends(get_db)):
    # Verify reCAPTCHA
    if not verify_recaptcha(recaptcha_response):
        raise HTTPException(status_code=400, detail="reCAPTCHA verification failed. Please try again.")

    try:
        if users.email_registered(db, email):
            return {"message": "User with this email already exists."}
        if users.email_pending(db, email):
            return {"message": "User with this email is already in the registration queue."}
        if password != confirm_password:
            return {"message": "Password do not match."}
        hashed_password = sha256_crypt.hash(password)
        role = 'teacher'
        users.add_pending(db, name=name, email=email, state=state, county=county, district=district, school=school, phone_number=phone_number, password=hashed_password, role=role, report=0, emailed=0)
        db.commit()
        send_registration_email(email)
        return {"message": "User registered successfully. You should recieve an email shortly. Please check your spam folder"}
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        return {"message": "Registration unsuccessful. Please try again later."}

    
###api used to create cookie based session via authentication with registered_user table
@app.post("/profile/login/")
@limiter.limit("5/minute")
async def login_user(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    try:
        user = users.get_by_email(db, email)
        if user:
            hashed_password = user.password
            if sha256_crypt.verify(password, hashed_password):
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
@app.post("/profile/logout/")
async def logout_user(request: Request):
    if "user_id" in request.session:
        del request.session["user_id"]
        del request.session["user_role"]
        del request.session["user_email"]
    return RedirectResponse(url="/", status_code=303)

# Endpoint to move a user from new_users to registered_users and delete item in new_users
@app.post("/validation/validate_user/{user_email}")
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

##this api allows a logged in user to create an item in the table teacher_list in the hithero database if they have not created a user already
@app.post("/profile/create_teacher_profile/")
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

##api gets a random teacher from the list teacher_list in the hithero data base

@app.get("/api/random_teacher/")
async def get_random_teacher(request: Request, db: Session = Depends(get_db)):
    try:
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
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")


###api gets the current session info of the logged in user
@app.get("/api/profile/")
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


## api used to send contact us email from /contact.html
@app.post('/api/contact_us/')
async def contact_us(name: str = Form(...), email: str = Form(...), subject: str = Form(...), message: str = Form(...), recaptcha_response: str = Form(...)):

    # reCAPTCHA verification
    is_valid = verify_recaptcha(recaptcha_response)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid reCAPTCHA")

    #clean and Define the data to populate the template
    clean_name = bleach.clean(name, tags=[], attributes={}, strip=True)
    clean_email = bleach.clean(email, tags=[], attributes={}, strip=True)
    clean_message = bleach.clean(message, tags=[], attributes={}, strip=True)
    clean_subject = bleach.clean(subject, tags=[], attributes={}, strip=True)

    template_data = {
        'recipient_name': 'Homeroom Heroes Team',
        'message_body': f"Message from {clean_name} ({clean_email}):\n\n{clean_message}"
    }

    # 1. Generate the HTML message from the template
    # The path is correctly specified relative to the project root
    html_message = render_email_template('static/email_template.html', template_data)

    # 2. Create a plain text fallback version
    plain_message = (
        f"Subject: {clean_subject}\n"
        f"Message from {clean_name} ({clean_email}):\n\n"
        f"{clean_message}"
    )

    recipient_email = 'Homeroom.heroes.contact@gmail.com'
    try:
        send_email(recipient_email, clean_subject, html_message, plain_message)
        return {"message": "Email sent successfully!"}
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")

#homepage get
@app.get("/")
def read_root():
    return RedirectResponse("/pages/homepage.html")

# Custom 404 error handler
@app.exception_handler(404)
async def not_found(request: Request, exc: HTTPException):
    with open(os.path.join("pages/", "404.html"), "r", encoding="utf-8") as file:
        content = file.read()
    return HTMLResponse(content=content, status_code=404)

# Custom 403 error handler
@app.exception_handler(403)
async def forbidden(request: Request, exc: HTTPException):
    with open(os.path.join("pages/", "403.html"), "r", encoding="utf-8") as file:
        content = file.read()
    return HTMLResponse(content=content, status_code=403)

###api gets a teacher data from teacher_list table
@app.get("/api/get_teacher_info/")
async def get_teacher_info(request: Request, db: Session = Depends(get_db)):
    try:
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
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")

##api that updates about me info
@app.post("/profile/update_info/")
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
@app.post("/profile/update_teacher_school/")
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
@app.post("/profile/update_teacher_name/")
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
@app.post("/profile/update_wishlist/")
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
@app.post("/profile/update_url_id/")
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
@app.post("/profile/update_teacher_image/")
async def edit_teacher_image(request: Request, image: UploadFile = Form(...), user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    id = user.id
    try:
        if image.size > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="File size exceeds the allowed limit")
        
        # Read bytes once, then use for both magic check and DB storage
        image_bytes = await image.read()
        
        # Validate by actual file signature, not client-supplied content_type
        ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
        
        # puremagic equivalent to magic.from_buffer(..., mime=True)
        results = puremagic.magic_buffer(image_bytes)
        
        # Grab the mime type from the first (best) match
        detected_type = results[0].mime if results else None

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
@app.get("/profile/myinfo/")
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
@app.post("/profile/update_password/")
async def update_password(request: Request, id: int = Depends(get_current_id), old_password: str = Form(...), new_password: str = Form(...), new_password_confirmed: str = Form(...), db: Session = Depends(get_db)):
    try:
        if new_password == new_password_confirmed:
            old_pass = users.password_hash(db, id)
            if old_pass and sha256_crypt.verify(old_password, old_pass):
                hashed_new_password = sha256_crypt.hash(new_password)
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


#api to check if a user has edit acces to teacher page
@app.get("/api/check_access_teacher/")
async def check_access_teacher(request: Request, user: CurrentUser = Depends(require_role("teacher")), db: Session = Depends(get_db)):
    try:
        state = get_index_cookie('state', request)
        county = get_index_cookie('county', request)
        district = get_index_cookie('district', request)
        school = get_index_cookie('school', request)
        name = get_index_cookie('teacher', request)
        teacher = teachers.get_by_location_and_name(db, state, county, district, school, name)
        if teacher is not None and teacher.regUserID == user.id:
            return {"status": "success", "message": "Access granted"}
        raise HTTPException(status_code=403, detail="No access")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")


def _pending_dict(u) -> dict:
    return {"name": u.name, "email": u.email, "state": u.state, "district": u.district, "school": u.school,
            "phone_number": u.phone_number, "report": u.report, "emailed": u.emailed}


#gets a list of unverified users to validate based on the role of the user
@app.get("/api/validation_list/")
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


#api gets a list of states from statecoutny table
@app.get("/api/get_states/")
async def get_states(db: Session = Depends(get_db)):
    return sorted(schools.list_states(db))

#api gets the names of the counties in the desired state
@app.get("/api/get_counties/{state}")
async def get_counties(state: str, db: Session = Depends(get_db)):
    counties = schools.list_counties(db, state)
    if counties:
        return sorted(counties)
    else:
        return {"message": f"No counties found for state: {state}"}

#api gets the names of the school districts in the desired county and state
@app.get("/api/get_districts/{state}/{county}")
async def get_districts(state: str, county: str, db: Session = Depends(get_db)):
    districts = schools.list_districts(db, state, county)
    if districts:
        return sorted(districts)
    else:
        return {"message": f"No districts found for state: {state} and county: {county}"}

#api gets the names of the school in the desired district, coutny, and state
@app.get("/api/get_schools/{state}/{county}/{district}")
async def get_schools(state: str, county: str, district: str, db: Session = Depends(get_db)):
    school_names = schools.list_schools(db, state, county, district)
    if school_names:
        return sorted(school_names)
    else:
        return {"message": f"No schools found for state: {state}, county: {county}, and district: {district}"}

@app.post("/profile/forgot_password/")
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
    
@app.post("/profile/reset_password/")
async def reset_password(token: str = Form(...), new_password: str = Form(...), confirm_password: str = Form(...), db: Session = Depends(get_db)):
    try:
        if new_password != confirm_password:
            raise HTTPException(status_code=400, detail="Passwords do not match.")
        # Look up the token
        reset = users.get_usable_reset_token(db, token, datetime.datetime.utcnow())
        if not reset:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token.")
        # Update the password
        hashed = sha256_crypt.hash(new_password)
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

#api that gets today's Teacher of the Day (whoever has the most recent last_TOD)
@app.get("/api/teacher_of_the_day")
async def get_teacher_of_the_day(request: Request, db: Session = Depends(get_db)):
    try:
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
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

###api to get a link for the url to your page to share
@app.get("/api/teacher_url/")
async def get_teacher_url(request: Request, db: Session = Depends(get_db)):
    try:
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
    except Exception as e:
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")

##this api gets the token, gets the data, sets the data, then redirects
@app.get("/teacher/{url_id}")
async def get_teacher_info(url_id: str, request: Request, db: Session = Depends(get_db)):
    try:
        teacher_info = teachers.get_by_url_id(db, url_id)
        if not teacher_info:
            return RedirectResponse(url="/pages/404.html")
        request.session['state'] = teacher_info.state
        request.session['county'] = teacher_info.county
        request.session['district'] = teacher_info.district
        request.session['school'] = teacher_info.school
        request.session['teacher'] = teacher_info.name

        return RedirectResponse(url="/pages/teacher.html")
    except Exception as e:
        return RedirectResponse(url="/pages/404.html")

# Endpoint to  users
@app.post("/validation/delete_user/{user_email}")
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
@app.post("/validation/report_user/{user_email}")
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
@app.post("/validation/emailed_user/{user_email}")
async def emailed_user(user_email: str, user: CurrentUser = Depends(require_member), db: Session = Depends(get_db)):
    try:
        users.flag_pending(db, user_email, emailed=1)
        db.commit()
        return {"message": "User emailed."}
    except Exception as e:
        db.rollback()
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail="Internal Server Error")


#api gets a list of states from statecoutny table
@app.get("/api/index_states/")
async def index_states(db: Session = Depends(get_db)):
    return sorted(teachers.index_states(db))

#api gets the names of the counties in the desired state
@app.get("/api/index_counties/{state}")
async def index_counties(state: str, db: Session = Depends(get_db)):
    counties = teachers.index_counties(db, state)
    if counties:
        return sorted(counties)
    else:
        return {"message": f"No counties found for state: {state}"}

#api gets the names of the school districts in the desired county and state
@app.get("/api/index_districts/{state}/{county}")
async def index_districts(state: str, county: str, db: Session = Depends(get_db)):
    districts = teachers.index_districts(db, state, county)
    if districts:
        return sorted(districts)
    else:
        return {"message": f"No districts found for state: {state} and county: {county}"}

#api gets the names of the school in the desired district, coutny, and state
@app.get("/api/index_schools/{state}/{county}/{district}")
async def index_schools(state: str, county: str, district: str, db: Session = Depends(get_db)):
    school_names = teachers.index_schools(db, state, county, district)
    if school_names:
        return sorted(school_names)
    else:
        return {"message": f"No schools found for state: {state}, county: {county}, and district: {district}"}

###api gets the teachers and their url_id for the index
@app.post("/api/index_teachers/")
async def index_teachers(state: str = Form(...),county: str = Form(None),district: str = Form(None),school: str = Form(None), db: Session = Depends(get_db)):
    matches = teachers.search(db, state, county, district, school)

    if matches:
        return [{"name": teacher.name, "url_id": teacher.url_id} for teacher in matches]
    else:
        raise HTTPException(
            status_code=404,
            detail="No teachers found with the given criteria."
        )

@app.post("/admin/generate_teacher_report/")
async def generate_teacher_report(state: str = Form(...), county: str = Form(None), district: str = Form(None), school: str = Form(None), caller: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        # Step 1: Dynamically filter TeacherList based on provided fields (excluding regUserID)
        report_teachers = teachers.report_rows(db, state, county, district, school)

        if not report_teachers:
            raise HTTPException(status_code=404, detail="No teachers found with the specified criteria.")

        # Step 2: Fetch email and phone from RegisteredUsers using regUserID
        reg_user_ids = [teacher.regUserID for teacher in report_teachers]
        contacts = users.contacts_by_id(db, reg_user_ids)

        # Step 3: Map teachers to their corresponding user data (email and phone)
        user_dict = {c.id: {"email": c.email, "phone": c.phone_number} for c in contacts}

        table_data = [["Name", "School", "Email", "Phone"]]
        for teacher in report_teachers:
            table_data.append([
                teacher.name or "",
                teacher.school or "",
                user_dict.get(teacher.regUserID, {}).get('email', 'N/A'),
                user_dict.get(teacher.regUserID, {}).get('phone', 'N/A'),
            ])

        # Step 4: Build the PDF in memory
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        story = [Paragraph("Teacher Report", styles['Title']), Spacer(1, 12)]

        table = Table(table_data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(table)
        doc.build(story)
        buffer.seek(0)

        # Step 5: Stream the PDF back to the browser as a download
        return StreamingResponse(
            buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=teacher_report.pdf"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report generation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


# --- Modified API Endpoint for Promotional Items ---
@app.get("/{token}", response_class=HTMLResponse)
async def get_promotional_page_with_hero(request: Request, token: str):
    """
    Sets a session variable with the promo token and redirects to the homepage.
    The homepage's JavaScript will then pick up this token and display the promo hero.
    """
    lookup_token = token.lower()
    relative_image_path = PROMO_IMAGE_MAPPING.get(lookup_token)

    if not relative_image_path:
        relative_image_path = PROMO_IMAGE_MAPPING.get("default")
        if not relative_image_path:
            raise HTTPException(status_code=404, detail="Promotional image not found and no default image available in mapping.")

    full_filesystem_path = os.path.join(BASE_STATIC_DIR, relative_image_path)
    if not os.path.exists(full_filesystem_path):
        if token != "default":
            default_relative_path = PROMO_IMAGE_MAPPING.get("default")
            if default_relative_path and os.path.exists(os.path.join(BASE_STATIC_DIR, default_relative_path)):
                relative_image_path = default_relative_path
            else:
                raise HTTPException(status_code=404, detail=f"Image for token '{token}' not found and default image file is also missing.")
        else:
            raise HTTPException(status_code=404, detail="Default promotional image file not found.")

    # Store the actual static URL of the image in the session
    promo_image_url = f"/static/{relative_image_path}"
    request.session["promo_image_url"] = promo_image_url
    request.session["promo_title"] = f"Working together to serve our communities!" # Example title

    # Redirect to the homepage
    return RedirectResponse(url="/pages/homepage.html")

# --- API to get promo info (called by JavaScript) ---
@app.get("/promo/get_promo_info/")
async def get_promo_info(request: Request):
    promo_info = {
        "promo_image_url": request.session.pop("promo_image_url", None), # Pop to clear after use
        "promo_title": request.session.pop("promo_title", None),
    }
    # Clear the session variables after they are fetched
    return JSONResponse(content=promo_info)

@app.post("/forum/create_post")
@limiter.limit("5/minute")
def create_post(request: Request, title: str = Form(...), content: str = Form(...), user: CurrentUser = Depends(require_login), db: Session = Depends(get_db)):
    user_id = user.id
    # 1. Create a new ForumPost instance
    new_post = ForumPost(
        title=bleach.clean(title, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True),
        content=bleach.clean(content, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True),
        user_id=user_id
    )
    try:
        # 2. Add to session and commit
        forum.add(db, new_post)
        db.commit()
        # 3. Refresh to get the auto-generated ID and created_at timestamp
        db.refresh(new_post)
    except Exception as e:
        db.rollback()
        print(f"Database error during post creation: {e}")
        # Return a generic error to the user
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create post due to a server error."
        )
    # 4. Return the new post data
    return new_post

@app.get("/forum/get_posts")
def get_posts(db: Session = Depends(get_db)):
    """
    Retrieves a list of all forum posts.

    The resulting list is ordered by creation date (newest first).
    If you implement an upvote mechanism, you can modify the order_by clause
    to use upvotes first:
    .order_by(ForumPost.upvotes.desc(), ForumPost.created_at.desc())
    """
   
    try:
        # Query all posts and order them by the 'created_at' column descending.
        # This returns the newest posts first, which is a good default for a feed.
        posts = forum.list_posts(db)
        return posts
    except Exception as e:
        print(f"Database error during post retrieval: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve posts due to a server error."
        )

@app.get("/forum/get_post")
def get_post(post_id: int, db: Session = Depends(get_db)):
    """
    Retrieves a single forum post using its unique ID.
    
    Raises HTTPException 404 if the post is not found.
    """
    
    try:
        # Query the database for a single post matching the provided ID
        post = forum.get_post(db, post_id)
        
        # Check if the post was found
        if post is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Post with ID {post_id} not found."
            )
            
        return post
        
    except HTTPException:
        # Re-raise the 404 exception if it was already raised
        raise
    except Exception as e:
        print(f"Database error during single post retrieval (ID: {post_id}): {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve post due to a server error."
        )

@app.post("/forum/posts/{post_id}/vote")
def handle_post_vote(post_id: int, vote_data: VoteInput, user: CurrentUser = Depends(require_login), db: Session = Depends(get_db)):
    user_id = user.id

    vote_type = vote_data.vote_type

    # 1. Input validation
    if vote_type not in (1, -1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid vote type. Must be 1 (upvote) or -1 (downvote)."
        )

    # 2. Check if the post exists
    post = forum.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Post with ID {post_id} not found.")

    # 3. Check for an existing vote by this user
    existing_vote = forum.get_vote(db, post_id, user_id)

    try:
        if existing_vote:
            if existing_vote.vote_type == vote_type:
                # Case 1: Retract vote (User clicks the same button again)
                forum.remove(db, existing_vote)
                # Subtract the existing vote type from the post's count
                post.upvote_count -= vote_type
                
            else:
                # Case 2: Change vote (e.g., upvote to downvote or vice versa)
                old_vote_value = existing_vote.vote_type
                
                # Update the vote record with the new type
                existing_vote.vote_type = vote_type
                
                # Calculate net change and update the post's cached count
                # Net Change = (New Value) - (Old Value). This handles +/-2 changes.
                net_change = vote_type - old_vote_value
                post.upvote_count += net_change

        else:
            # Case 3: New vote
            new_vote = PostVote(post_id=post_id, user_id=user_id, vote_type=vote_type)
            forum.add(db, new_vote)
            # Add the new vote type to the post's cached count
            post.upvote_count += vote_type

        # 4. Commit all changes to PostVote and ForumPost
        db.commit()
        db.refresh(post)

    except Exception as e:
        db.rollback()
        print(f"Database error during voting operation on post {post_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A server error prevented the vote from being recorded."
        )

    # 5. Return the updated post data
    return post

@app.post("/forum/posts/{post_id}/comment", summary="Add a new comment to a specific post")
@limiter.limit("5/minute")
def add_comment_to_post(request: Request, post_id: int, content: str = Form(...), parent_comment_id: Optional[int] = Form(None), user: CurrentUser = Depends(require_login), db: Session = Depends(get_db)):
    user_id = user.id

    # 1. Check if the parent post exists
    post = forum.get_post(db, post_id)
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Post with ID {post_id} not found."
        )

    # 2. Check if a parent comment exists (if parent_comment_id is provided, for nesting)
    if parent_comment_id:
        parent_comment = forum.get_comment(db, parent_comment_id)
        if not parent_comment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail=f"Parent comment with ID {parent_comment_id} not found."
            )

    try:
        # 3. Create a new ForumComment instance
        new_comment = ForumComment(
            post_id=post_id,
            user_id=user_id,
            content=bleach.clean(content, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True),
            parent_comment_id=parent_comment_id
        )
        # 4. Add to session
        forum.add(db, new_comment)
        
        # 5. Update the comment_count on the parent post (Denormalization)
        post.comment_count += 1 
        
        db.commit()
        db.refresh(new_comment)

    except Exception as e:
        db.rollback()
        print(f"Database error during comment creation on post {post_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create comment due to a server error."
        )

    # 6. Return the new comment data
    # Assuming the API returns the comment object, which includes 'user_id' and 'created_at'
    return new_comment


@app.get("/forum/comments/{post_id}/")
def get_comments_for_post(post_id: int = Path(..., gt=0), db: Session = Depends(get_db)) -> List[dict]:
    """
    Fetches all comments associated with a specific post, ordered by creation date (newest first).
    """
    
    # 1. Check if the parent post exists (Optional, but good practice)
    post = forum.get_post(db, post_id)
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"Post with ID {post_id} not found."
        )

    try:
        # 2. Query all comments for that post ID
        comments = forum.list_comments(db, post_id)

        # 3. FIX APPLIED HERE: Convert list of SQLAlchemy model objects to list of dictionaries
        return [model_to_dict(comment) for comment in comments] 

    except Exception as e:
        print(f"Database error during comment retrieval on post {post_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not retrieve comments due to a server error."
        )
@app.delete("/forum/post/{post_id}/delete")
def delete_post(post_id: int, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    """
    Deletes a post. Only allowed for role = 'admin'.
    """
    # 2. Find the post
    post = forum.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")

    # 3. Delete the post
    forum.remove(db, post)
    db.commit()
    
    # Due to CASCADE ON DELETE in the schema, votes and comments are automatically deleted.
    return

@app.delete("/forum/comment/{comment_id}/delete")
def delete_comment(comment_id: int, user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    """
    Deletes a comment. Only allowed for admin OR the comment's author (not yet but can be if you uncomment below)
    """
    # 1. Find the comment
    comment = forum.get_comment(db, comment_id)
    
    if not comment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Comment not found"
        )
    
    # Admins only. To let authors delete their own comments, switch the
    # dependency to require_login and check comment.user_id == user.id.

    # 3. Denormalization: Decrement the parent post's comment count
    post = forum.get_post(db, comment.post_id)
    
    if post and post.comment_count > 0:
        post.comment_count -= 1
        # No need to add the post again: the session tracks it,
        # but calling db.commit() below will save the change.
    
    # 4. Delete the comment
    forum.remove(db, comment)
    db.commit()
    
    # Note on nested comments: If you need to handle deletion of child comments 
    # (i.e., comments that had replies) this would be handled automatically if 
    # you set up CASCADE DELETE on the parent_comment_id foreign key in your DDL.
    
    return {"detail": f"Comment ID {comment_id} successfully deleted."}

@app.patch("/forum/post/{post_id}/update")
async def update_post(post_id: int, post_data: PostUpdate, id: int = Depends(get_current_id), db: Session = Depends(get_db)):
    """
    Allows the author of a post to update its title and content.
    """
    
    
    try:
        # 1. Fetch the existing post
        existing_post = forum.get_post(db, post_id)
        
        if existing_post is None:
            raise HTTPException(status_code=404, detail=f"Post with ID {post_id} not found.")
            
        # 2. Authorization Check: Must be the original author
        # 'user' is the dictionary returned by get_current_active_user, containing the authenticated user's details
        if existing_post.user_id != id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Not authorized to edit this post. You must be the author."
            )
            
        # 3. Update the post data in the SQLAlchemy model
        existing_post.title = bleach.clean(post_data.title, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
        existing_post.content = bleach.clean(post_data.content, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
        
        # 4. Commit the changes to the database
        db.commit()
        
        # 5. Refresh the object to get any auto-updated fields (like a 'last_edited' timestamp if applicable)
        db.refresh(existing_post)
        
        # 6. Return the updated post
        # Note: We use response_model=PostUpdate for simplicity, 
        # but in a real app, you might use your full Post schema if it includes more fields.
        return existing_post

    except HTTPException:
        raise
    except Exception as e:
        db.rollback() # Rollback the transaction on any error
        # In a production environment, log the error 'e' here
        raise HTTPException(status_code=500, detail="Internal server error during post update.")
        

@app.patch("/forum/comment/{comment_id}/update")
async def update_comment(comment_id: int, content: str = Form(...), user: int = Depends(get_current_id), db: Session = Depends(get_db)):
    """
    Allows the author of a comment to update its content.
    """
    
    try:
        # 1. Fetch the existing comment
        existing_comment = forum.get_comment(db, comment_id)
        
        if existing_comment is None:
            raise HTTPException(status_code=404, detail=f"Comment with ID {comment_id} not found.")
            
        # 2. Authorization Check: Must be the original author
        if existing_comment.user_id != user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, 
                detail="Not authorized to edit this comment. You must be the author."
            )
            
        # 3. Update the content
        existing_comment.content = bleach.clean(content, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
        
        
        # 4. Commit and Refresh
        db.commit()
        db.refresh(existing_comment)
        
        # Return the updated object (FastAPI handles JSON conversion)
        return existing_comment

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error during comment update.")
        


@app.post("/profile/delete/")
async def admin_delete_user_account(target_email: str = Form(...), admin_secret_input: str = Form(...), user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)):
    """
    Allows an authenticated 'admin' user to delete *any* user account 
    by providing the target user's email and a secret key via form submission.
    Deletes the associated teacher entry and the registered user account.
    """
    
    # 2. SECRET CHECK: Ensure the provided secret matches the server configuration
    ADMIN_SECRET = settings.admin_secret
    
    if not ADMIN_SECRET or admin_secret_input != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid administrator secret provided.")

    try:
        # 3. FIND THE TARGET USER ID
        # Select the ID of the user to be deleted based on the target email.
        target = users.get_by_email(db, target_email)

        if not target:
            raise HTTPException(status_code=404, detail=f"User account linked to '{target_email}' not found.")

        # 4. Delete their teacher page, then the account itself.
        teachers.delete_for_user(db, target.id)
        users.delete_by_email(db, target_email)
        db.commit()
        return {"message": f"Successfully deleted account and associated data for target user: {target_email}."}

    except HTTPException as h:
        raise h
    except Exception as e:
        db.rollback()
        print(f"Error during administrative account deletion for {target_email}: {str(e)}")
        logger.error(f"Internal Server Error: {str(e)}") 
        raise HTTPException(status_code=500, detail=f"Internal Server Error")


@app.post("/admin/create_admin/")
@limiter.limit("5/minute")
async def create_admin_account(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    admin_secret_input: str = Form(...),
    user: CurrentUser = Depends(require_admin), db: Session = Depends(get_db)
):
    """
    Allows an authenticated 'admin' user, who also supplies the server's admin
    secret, to create a brand new admin account directly in registered_users.
    Only email, password, and role are stored; id is auto-assigned by the DB.
    """

    # 2. SECRET CHECK: Same server secret used for other sensitive admin actions
    ADMIN_SECRET = settings.admin_secret
    if not ADMIN_SECRET or admin_secret_input != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Invalid administrator secret provided.")

    # 3. BASIC VALIDATION
    if password != confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters long.")

    try:
        # 4. Make sure this email isn't already in use, in either table
        if users.email_registered(db, email) or users.email_pending(db, email):
            raise HTTPException(status_code=400, detail="An account with this email already exists.")

        # 5. Create the admin account directly in registered_users (id auto-assigned by the DB)
        hashed_password = sha256_crypt.hash(password)
        users.create_admin(db, email, hashed_password)
        db.commit()
        return {"message": f"Admin account created successfully for {email}."}

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating admin account: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)