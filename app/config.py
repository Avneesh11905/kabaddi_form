from pydantic_settings import BaseSettings 
from typing import Optional

class Settings(BaseSettings):
    MONGO_URI: str = ""  # Required, but default empty for mypy
    DB_NAME: str = "kabaddi_db"
    COLLECTION_NAME: str = "submissions"
    INPUT_FILE: str = "kabbadi  (Responses).xlsx"
    ADMIN_USER: str = "admin"
    ADMIN_PASS: str = "admin123"
    SESSION_COOKIE: str = "admin_session"
    SESSION_EXPIRY: int = 1800  # Cookie expiry in seconds (30 minutes)
    RESEND_API_KEY: Optional[str] = None
    APP_URL: str = "http://localhost:8000"
    VERCEL_URL: Optional[str] = None

    class Config:
        env_file = ".env"

    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    # Use model_validator to compute APP_URL from VERCEL_URL if detected
    def model_post_init(self, __context):
        if self.VERCEL_URL and self.APP_URL == "http://localhost:8000":
             self.APP_URL = f"https://{self.VERCEL_URL}"
             
settings = Settings()
