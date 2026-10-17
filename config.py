import os

BASE = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me-in-production")
    DATABASE = os.path.join(BASE, "instance", "hospital.db")
    UPLOAD_FOLDER = os.path.join(BASE, "uploads")
    MODEL_FOLDER = os.path.join(BASE, "models")
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    ALLOWED_EXTENSIONS = {"csv"}
    MAX_UPLOAD_ROWS = 20_000
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    RISK_HIGH = 0.60          # score >= RISK_HIGH  -> High
    RISK_MEDIUM = 0.35        # score >= RISK_MEDIUM -> Medium, else Low
    DEPARTMENTS = ["Cardiology", "Pulmonology", "Endocrinology", "Orthopedics",
                   "General Medicine", "Neurology", "Nephrology"]
