# ============================================================
# config.py  –  Central configuration loader
# ============================================================
import os
from dotenv import load_dotenv

load_dotenv()

# ---------------------------
# DATABASE
# ---------------------------
DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", 5432))
DB_NAME     = os.getenv("DB_NAME", "tally_erp")
DB_USER     = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# ---------------------------
# TALLY
# ---------------------------
TALLY_URL = f"http://{os.getenv('TALLY_HOST','localhost')}:{os.getenv('TALLY_PORT','9000')}"

# ---------------------------
# EMAIL
# ---------------------------
SMTP_HOST      = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT      = int(os.getenv("SMTP_PORT", 587))
SMTP_USER      = os.getenv("SMTP_USER", "")
SMTP_PASSWORD  = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Tally Recovery ERP")

# ---------------------------
# WHATSAPP
# ---------------------------
WA_PROVIDER   = os.getenv("WHATSAPP_PROVIDER", "wati")
WA_API_URL    = os.getenv("WHATSAPP_API_URL", "")
WA_API_TOKEN  = os.getenv("WHATSAPP_API_TOKEN", "")
WA_FROM_NUMBER= os.getenv("WHATSAPP_FROM_NUMBER", "")

# ---------------------------
# APP
# ---------------------------
SECRET_KEY = os.getenv("APP_SECRET_KEY", "dev-secret-key")
