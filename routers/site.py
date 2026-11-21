"""Site pages: homepage redirect, ads.txt, sitemap, contact form and promo links.

Include this router last: GET /{token} matches every one-segment path."""

import os

import bleach
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from auth import recaptcha
from config import settings
from emails import render_email_template, send_email

router = APIRouter()


BASE_STATIC_DIR = "static"

ADS_TXT_PATH = f"{BASE_STATIC_DIR}/ads.txt"
SITEMAP_XML_PATH = f"{BASE_STATIC_DIR}/sitemap.xml"

# 1. Route for ads.txt (media_type='text/plain')
@router.get("/ads.txt", include_in_schema=False)
async def get_ads_txt():
    """Serves ads.txt from the static folder at the root URL."""
    return FileResponse(ADS_TXT_PATH, media_type='text/plain')

# 2. Route for sitemap.xml (media_type='application/xml')
@router.get("/sitemap.xml", include_in_schema=False)
async def get_sitemap_xml():
    """Serves sitemap.xml from the static folder at the root URL."""
    return FileResponse(SITEMAP_XML_PATH, media_type='application/xml')

# --- Configuration for Promotional Images Mapping ---
PROMO_IMAGE_MAPPING = settings.promo_images


## api used to send contact us email from /contact.html
@router.post('/api/contact_us/')
async def contact_us(name: str = Form(...), email: str = Form(...), subject: str = Form(...), message: str = Form(...), recaptcha_response: str = Form(...)):

    # reCAPTCHA verification
    is_valid = recaptcha.verify_recaptcha(recaptcha_response)
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
    send_email(recipient_email, clean_subject, html_message, plain_message)
    return {"message": "Email sent successfully!"}

#homepage get
@router.get("/")
def read_root():
    return RedirectResponse("/pages/homepage.html")


# --- Modified API Endpoint for Promotional Items ---
@router.get("/{token}", response_class=HTMLResponse)
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
@router.get("/promo/get_promo_info/")
async def get_promo_info(request: Request):
    promo_info = {
        "promo_image_url": request.session.pop("promo_image_url", None), # Pop to clear after use
        "promo_title": request.session.pop("promo_title", None),
    }
    # Clear the session variables after they are fetched
    return JSONResponse(content=promo_info)
