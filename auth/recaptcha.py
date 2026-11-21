"""Google reCAPTCHA check for the register and contact forms."""

import requests

from config import settings

#####################################################



def verify_recaptcha(recaptcha_response: str):
    """Verifies the reCAPTCHA response with Google's servers."""
    url = "https://www.google.com/recaptcha/api/siteverify"
    params = {"secret": settings.server_key_captcha, "response": recaptcha_response}
    response = requests.post(url, params=params)
    data = response.json()
    return data["success"]
