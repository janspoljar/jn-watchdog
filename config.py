import os
from dotenv import load_dotenv

# Naloži .env datoteko
load_dotenv()

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
FROM_EMAIL = os.getenv("FROM_EMAIL", "narocila@tvojadomena.si")
DB_PATH = os.getenv("DB_PATH", "narocila.db")
