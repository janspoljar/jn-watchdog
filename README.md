# jn-watchdog

Subscription SaaS za spremljanje javnih naročil na slovenskem trgu.

Orodje vsak dan scrapa javna naročila z [ejn.gov.si](https://ejn.gov.si) in naročnikom pošilja tedenske email alerte po kategorijah. Naročnina znaša 19 €/mesec prek Stripe.

## Tehnologije

- **Python 3.13**
- **Flask** — backend API
- **SQLite** — lokalna baza podatkov
- **Resend** — pošiljanje emailov
- **Stripe** — upravljanje plačil
- **Railway** — hosting v produkciji

## Struktura projekta

```
jn-watchdog/
├── main.py         # Vstopna točka, urnik scraping + alertov
├── scraper.py      # Scraping ejn.gov.si
├── db.py           # SQLite operacije
├── emailer.py      # Pošiljanje alertov prek Resend
├── server.py       # Flask API (registracija, Stripe webhook)
├── config.py       # Environment spremenljivke
├── requirements.txt
├── .env.example
└── .gitignore
```

## Namestitev

```bash
# Kloniraj repozitorij
git clone https://github.com/tvoj-username/jn-watchdog.git
cd jn-watchdog

# Namesti odvisnosti
pip install -r requirements.txt

# Ustvari .env datoteko
cp .env.example .env
# Uredi .env in dodaj svoje API ključe
```

## Konfiguracija

Kopiraj `.env.example` v `.env` in izpolni vrednosti:

```
RESEND_API_KEY=       # API ključ za Resend
STRIPE_SECRET_KEY=    # Stripe secret key
STRIPE_WEBHOOK_SECRET=# Stripe webhook signing secret
FROM_EMAIL=           # Email pošiljatelja
DB_PATH=narocila.db   # Pot do SQLite baze
```

## Zagon

```bash
# Zaženi scraper + urnik
python main.py

# Zaženi Flask API strežnik (v ločenem terminalu)
python server.py
```

## API endpointsi

| Metoda | Pot | Opis |
|--------|-----|------|
| GET | `/health` | Preverba delovanja |
| POST | `/register` | Registracija novega naročnika |
| POST | `/checkout` | Ustvari Stripe Checkout sejo |
| POST | `/webhook` | Stripe webhook handler |
