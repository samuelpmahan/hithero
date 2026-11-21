"""All app settings, read once at startup (BE2-3).

Values come from environment variables, or from a .env file in the
working directory for local runs. Names are case-insensitive, so
SECRET_KEY and secret_key are the same setting. A missing required
setting stops the app at startup and names the variable.
"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Sessions
    secret_key: str

    # Database
    database_server: str
    database_name: str
    database_uid: str
    database_password: str
    database_port: int = 1433
    database_driver: str = "ODBC Driver 18 for SQL Server"
    # Extra ODBC connection options, as JSON, e.g. {"TrustServerCertificate": "yes"}
    database_options: dict[str, str] = {}

    # Azure Communication Services email
    azure_email_connection_string: str | None = None
    azure_email_sender: str | None = None

    # reCAPTCHA server key
    server_key_captcha: str | None = None

    # Shared secrets for the cron job endpoints and admin-only actions
    internal_job_secret: str | None = None
    admin_secret: str | None = None

    # Public site
    base_url: str = "https://www.helpteachers.net"
    # How the site's address is written in email and share-link text.
    display_host: str = "www.HelpTeachers.net"
    cors_origins: list[str] = ["https://www.helpteachers.net", "https://helpteachers.net"]

    # Partner promo pages: /{slug} shows that partner's image on the homepage.
    promo_images: dict[str, str] = Field(default_factory=lambda: {
        "seattlewolf": "images/partners/1007TheWolf.png",
        "livefree": "images/partners/965CountryColor.png",
        "basecamp": "images/partners/BaseCamp.png",
        "coastal": "images/partners/Coastal.png",
    })


settings = Settings()
