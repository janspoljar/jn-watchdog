"""
config.py — Centralne nastavitve iz environment spremenljivk.
Vse skrivnosti so v .env datoteki, nikoli hardcoded v kodi.
"""

import os
from dotenv import load_dotenv

# Naloži .env datoteko
load_dotenv()

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
FROM_EMAIL = os.getenv("FROM_EMAIL", "narocila@javna-narocila.si")
DB_PATH = os.getenv("DB_PATH", "narocila.db")
PORT = int(os.getenv("PORT", 5000))

# Javni naslov aplikacije — za gradnjo linkov v emailih (potrditev, odjava)
# in Stripe success/cancel URL. Brez končne poševnice.
BASE_URL = os.getenv("BASE_URL", "https://javna-narocila.si").rstrip("/")

# Admin email — prejema alerte ob napakah in dnevni povzetek joba
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "jan.spoljar@gmail.com")

# S3-kompatibilen storage za nočne backupe baze
# (Hetzner Object Storage ali Backblaze B2)
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")        # npr. https://fsn1.your-objectstorage.com
S3_BUCKET = os.getenv("S3_BUCKET")                    # npr. lovec-backups
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY")
S3_REGION = os.getenv("S3_REGION", "eu-central-1")
BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", 30))

# --- AI matching (Faza 3) ---
# Anthropic API ključ in model za ocenjevanje ustreznosti naročil.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# Pragova zaupanja (confidence) za uvrstitev naročila v email:
#   >= MATCH_PRAG_GLAVNI  -> glavna sekcija
#   >= MATCH_PRAG_MORDA   -> sekcija "Morda zanimivo"
#   pod tem              -> izpustimo
MATCH_PRAG_GLAVNI = float(os.getenv("MATCH_PRAG_GLAVNI", "0.7"))
MATCH_PRAG_MORDA = float(os.getenv("MATCH_PRAG_MORDA", "0.5"))

# Največ naročil v enem batch klicu na model (velikost/strošek).
MATCH_BATCH = int(os.getenv("MATCH_BATCH", "15"))

# Varovalka stroškov: največ ocen (naročilo×profil) na en zagon matchinga.
MATCH_MAX_NA_ZAGON = int(os.getenv("MATCH_MAX_NA_ZAGON", "2000"))

# Časovna cona za urnik pošiljanja (Osnovni/Pro/Business).
TIMEZONE = os.getenv("TZ", "Europe/Ljubljana")
