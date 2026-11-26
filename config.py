import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    SECRET_KEY = os.getenv("SECRET_KEY")
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    MONGO_DB = os.getenv("MONGO_DB", "smart_voting")
    APP_ENV = os.getenv("APP_ENV", "development")
    # TwoFactor Voice OTP Settings
    TWOFACTOR_API_KEY = os.getenv("TWOFACTOR_API_KEY")

    OTP_EXPIRY_MINUTES = int(os.getenv("OTP_EXPIRY_MINUTES", "5"))
    OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "3"))
    OTP_RESEND_SECONDS = int(os.getenv("OTP_RESEND_SECONDS", "60"))

    # Private voter document storage
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "private_uploads")
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024

    ALLOWED_DOCUMENT_EXTENSIONS = {"jpg", "jpeg", "png"}
