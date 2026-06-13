"""
server.py — Flask strežnik za javna-narocila.si (jn-watchdog).

Faza 4 doda javne strani (landing, brezplačni pregled, registracija z double
opt-in, politika zasebnosti) ob obstoječih API endpointih (Stripe webhook,
odjava, zdravje).

Uporabniško vidni teksti so v slovenščini, koda v angleščini.
"""

import re
import secrets
import sqlite3
import logging

import stripe
from datetime import timedelta

from flask import Flask, request, jsonify, render_template, redirect, session
from flask_cors import CORS

import config
import db
import panoge
import pregled
import emailer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.permanent_session_lifetime = timedelta(days=30)
CORS(app)  # Omogoči CORS za vse origine

# Inicializiraj bazo ob importu — gunicorn ne izvede __main__ bloka,
# init_db je idempotenten (CREATE TABLE IF NOT EXISTS), zato je klic varen.
db.init_db()

stripe.api_key = config.STRIPE_SECRET_KEY

# Preprost regex za validacijo email naslova
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Paketi (prikaz na strani; plačila pridejo v Fazi 5 — zdaj brezplačna beta)
PAKETI = [
    {
        "key": "osnovni", "ime": "Osnovni", "cena": "14 €", "obdobje": "/mesec",
        "frekvenca": "Tedenski email (ob ponedeljkih)",
        "profili": "1 profil dejavnosti",
        "znacilnosti": [
            "Tedenski pregled novih naročil",
            "1 profil dejavnosti",
            "Obvestila na email",
        ],
    },
    {
        "key": "pro", "ime": "Pro", "cena": "29 €", "obdobje": "/mesec",
        "frekvenca": "Dnevni alerti",
        "profili": "3 profili dejavnosti",
        "izpostavljen": True,
        "znacilnosti": [
            "Dnevni alerti novih naročil",
            "Do 3 profili dejavnosti",
            "Prednostna podpora",
        ],
    },
    {
        "key": "business", "ime": "Business", "cena": "59 €", "obdobje": "/mesec",
        "frekvenca": "Sprotno obveščanje (v realnem času)",
        "profili": "Neomejeno profilov",
        "znacilnosti": [
            "Obvestilo takoj, ko razpis izide",
            "Neomejeno profilov dejavnosti",
            "Prednostna podpora",
        ],
    },
]


# ---------------------------------------------------------------------------
# Javne strani (Faza 4)
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def landing():
    """Vstopna (landing) stran."""
    return render_template("landing.html", paketi=PAKETI)


@app.route("/pregled", methods=["GET", "POST"])
def pregled_strani():
    """
    Brezplačni pregled (lead magnet): forma + obdelava.
    Najde naročila zadnjih 30 dni za vpisano dejavnost, pošlje poročilo na
    email in shrani lead.
    """
    if request.method == "GET":
        return render_template("pregled_form.html", panoge=panoge.PANOGE)

    # POST — obdelaj formo
    email = (request.form.get("email") or "").strip().lower()
    panoga_key = (request.form.get("panoga") or "").strip()
    izbrani = request.form.getlist("izbrani")
    opis = (request.form.get("opis") or "").strip()

    napaka = None
    if not email or not EMAIL_REGEX.match(email):
        napaka = "Vpišite veljaven email naslov."
    elif panoga_key not in panoge.PANOGE:
        napaka = "Izberite svojo panogo."
    if napaka:
        return render_template(
            "pregled_form.html", panoge=panoge.PANOGE,
            napaka=napaka, email=email, panoga=panoga_key, opis=opis,
        ), 400

    panoga_ime = panoge.PANOGE[panoga_key]["ime"]
    narocila = pregled.najdi_zamujena(panoga_key, izbrani, opis)
    html = pregled.sestavi_html_pregled(panoga_ime, narocila)

    emailer.pošlji_pregled(email, html, len(narocila))
    db.shrani_lead(email, panoga_key, opis, izbrani)
    logger.info(f"Brezplačni pregled poslan: {email} ({len(narocila)} naročil).")

    return render_template(
        "pregled_oddano.html", email=email, stevilo=len(narocila),
    )


@app.route("/registracija", methods=["GET", "POST"])
def registracija():
    """
    Beta registracija z double opt-in. Plačilo (Stripe) pride v Fazi 5 —
    zdaj je beta brezplačna. Uporabnik se aktivira šele po potrditvi emaila.
    """
    if request.method == "GET":
        izbran_paket = (request.args.get("paket") or "pro").strip()
        return render_template(
            "registracija_form.html", panoge=panoge.PANOGE, paketi=PAKETI,
            paket=izbran_paket,
        )

    # POST — obdelaj prijavo
    email = (request.form.get("email") or "").strip().lower()
    panoga_key = (request.form.get("panoga") or "").strip()
    izbrani = request.form.getlist("izbrani")
    opis = (request.form.get("opis") or "").strip()
    paket = (request.form.get("paket") or "osnovni").strip()

    napaka = None
    if not email or not EMAIL_REGEX.match(email):
        napaka = "Vpišite veljaven email naslov."
    elif panoga_key not in panoge.PANOGE:
        napaka = "Izberite svojo panogo."
    elif paket not in {p["key"] for p in PAKETI}:
        napaka = "Izberite paket."
    if napaka:
        return render_template(
            "registracija_form.html", panoge=panoge.PANOGE, paketi=PAKETI,
            napaka=napaka, email=email, panoga=panoga_key, opis=opis, paket=paket,
        ), 400

    # Varovalo: že registriran in potrjen uporabnik naj se raje prijavi.
    obstojec = db.poberi_uporabnik_po_emailu(email)
    if obstojec and obstojec.get("aktiven"):
        return render_template(
            "registracija_form.html", panoge=panoge.PANOGE, paketi=PAKETI,
            napaka="Ta email je že registriran. Prijavite se v svoj račun.",
            ze_registriran=True, email=email, panoga=panoga_key, opis=opis, paket=paket,
        ), 400

    # Kategorije za dnevni job (beta — keyword filter; AI matching v Fazi 3)
    kategorije = panoge.kategorije_za_panogo(panoga_key)
    token = secrets.token_urlsafe(32)

    db.registriraj_uporabnika(email, panoga_key, opis, paket, kategorije, token, izbrani=izbrani)

    potrditveni_url = f"{config.BASE_URL}/potrditev?token={token}"
    emailer.pošlji_potrditev(email, potrditveni_url)
    logger.info(f"Beta registracija (čaka potrditev): {email} / paket={paket}")

    return render_template("registracija_oddano.html", email=email)


@app.route("/potrditev", methods=["GET"])
def potrditev():
    """Double opt-in potrditev prek tokena iz emaila."""
    token = (request.args.get("token") or "").strip()
    email = db.potrdi_uporabnika(token)
    uspeh = email is not None
    return render_template("potrditev.html", uspeh=uspeh), (200 if uspeh else 400)


@app.route("/zasebnost", methods=["GET"])
def zasebnost():
    """Politika zasebnosti (GDPR)."""
    return render_template("zasebnost.html")


# ---------------------------------------------------------------------------
# Prijava brez gesla (magic link) + nadzorna plošča (Faza 4.5)
# ---------------------------------------------------------------------------

@app.route("/prijava", methods=["GET", "POST"])
def prijava():
    """Vpis emaila -> pošlje prijavno povezavo (če račun obstaja)."""
    if request.method == "GET":
        return render_template("prijava.html")

    email = (request.form.get("email") or "").strip().lower()
    if email and EMAIL_REGEX.match(email):
        u = db.poberi_uporabnik_po_emailu(email)
        if u:
            token = db.ustvari_prijavni_zeton(u["id"])
            emailer.pošlji_prijavni_link(email, f"{config.BASE_URL}/racun?token={token}")
            logger.info(f"Prijavna povezava poslana: {email}")
    # Vedno enak odgovor — ne razkrivamo, ali email obstaja.
    return render_template("prijava_oddano.html", email=email)


@app.route("/racun", methods=["GET"])
def racun():
    """Nadzorna plošča. Token v URL prijavi; sicer zahteva sejo."""
    token = (request.args.get("token") or "").strip()
    if token:
        uid = db.unovci_prijavni_zeton(token)
        if uid:
            session.permanent = True
            session["uid"] = uid
            return redirect("/racun")
        return render_template(
            "prijava.html",
            napaka="Povezava ni veljavna ali je potekla. Vpišite email za novo.",
        ), 400

    uid = session.get("uid")
    if not uid:
        return redirect("/prijava")
    uporabnik = db.poberi_uporabnika(uid)
    if not uporabnik:
        session.clear()
        return redirect("/prijava")

    profili = db.poberi_profile_uporabnika(uid)
    meja = config.PAKET_MEJA_PROFILOV.get(uporabnik.get("paket") or "osnovni", 1)
    lahko_doda = (meja is None) or (len(profili) < meja)
    return render_template(
        "racun.html", uporabnik=uporabnik, profili=profili,
        panoge=panoge.PANOGE, meja=meja, lahko_doda=lahko_doda,
    )


@app.route("/racun/profil", methods=["POST"])
def racun_dodaj_profil():
    """Doda nov profil (do meje paketa)."""
    uid = session.get("uid")
    if not uid:
        return redirect("/prijava")
    uporabnik = db.poberi_uporabnika(uid)
    meja = config.PAKET_MEJA_PROFILOV.get(uporabnik.get("paket") or "osnovni", 1)
    if meja is not None and db.aktivnih_profilov(uid) >= meja:
        return redirect("/racun")  # meja dosežena — tiho ignoriraj

    panoga_key = (request.form.get("panoga") or "").strip()
    izbrani = request.form.getlist("izbrani")
    opis = (request.form.get("opis") or "").strip()
    if panoga_key in panoge.PANOGE:
        db.dodaj_profil(uid, panoga_key, opis, izbrani)
    return redirect("/racun")


@app.route("/racun/izbrisi", methods=["POST"])
def racun_izbrisi_profil():
    """Soft-izbris (deaktivacija) profila uporabnika."""
    uid = session.get("uid")
    if not uid:
        return redirect("/prijava")
    try:
        pid = int(request.form.get("profil_id") or 0)
    except ValueError:
        pid = 0
    if pid:
        db.izbrisi_profil(pid, uid)
    return redirect("/racun")


@app.route("/odjava-seje", methods=["GET"])
def odjava_seje():
    """Odjava iz seje (logout)."""
    session.clear()
    return redirect("/")


# ---------------------------------------------------------------------------
# Odjava (unsubscribe) — link v vsakem emailu (GDPR)
# ---------------------------------------------------------------------------

@app.route("/odjava", methods=["GET"])
def odjava():
    """Odjava uporabnika prek linka v emailu."""
    email = (request.args.get("email") or "").strip().lower()
    if email:
        db.deaktiviraj_uporabnika(email)
    return render_template("odjava.html", email=email)


# ---------------------------------------------------------------------------
# Stripe (Faza 5) — webhook obstaja; checkout je parkiran do ključev
# ---------------------------------------------------------------------------

def _ustvari_stripe_checkout(email: str):
    """
    PARKIRANO ZA FAZO 5: ustvari Stripe customer + checkout session.
    Med beta fazo se ne uporablja (registracija je brezplačna, brez plačila).
    Ko bodo ključi na voljo, se to poveže z registracijskim flowom in
    success/cancel stranema (/uspeh, /preklicano).
    """
    customer = stripe.Customer.create(email=email)
    db.nastavi_stripe_customer(email, customer.id)
    seja = stripe.checkout.Session.create(
        customer=customer.id,
        mode="subscription",
        line_items=[{"price": config.STRIPE_PRICE_ID, "quantity": 1}],
        success_url=f"{config.BASE_URL}/uspeh?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{config.BASE_URL}/preklicano",
    )
    return seja


@app.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():
    """
    Stripe webhook — aktivira uporabnika ob plačilu,
    deaktivira ob preklicu naročnine.
    """
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, config.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.error(f"Neveljaven webhook: {e}")
        return jsonify({"napaka": "Neveljaven webhook podpis."}), 400

    if event["type"] == "checkout.session.completed":
        seja = event["data"]["object"]
        email = (seja.get("customer_details") or {}).get("email") or seja.get("customer_email")
        if email:
            db.aktiviraj_uporabnika(email.lower())
            logger.info(f"Naročnina aktivirana: {email}")

    elif event["type"] == "customer.subscription.deleted":
        narocnina = event["data"]["object"]
        customer_id = narocnina.get("customer")
        email = _email_po_customer_id(customer_id)
        if email:
            db.deaktiviraj_uporabnika(email)
            logger.info(f"Naročnina prekinjena: {email}")
        else:
            logger.warning(f"Ni uporabnika za customer_id: {customer_id}")

    return jsonify({"status": "ok"}), 200


def _email_po_customer_id(customer_id: str) -> str | None:
    """Vrne email uporabnika glede na Stripe customer ID, ali None."""
    if not customer_id:
        return None
    conn = sqlite3.connect(config.DB_PATH)
    vrstica = conn.execute(
        "SELECT email FROM uporabniki WHERE stripe_customer_id = ?", (customer_id,)
    ).fetchone()
    conn.close()
    return vrstica[0] if vrstica else None


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.route("/zdravje", methods=["GET"])
def zdravje():
    """Health check — vrne stanje baze."""
    conn = sqlite3.connect(config.DB_PATH)
    narocila = conn.execute("SELECT COUNT(*) FROM narocila").fetchone()[0]
    aktivni = conn.execute("SELECT COUNT(*) FROM uporabniki WHERE aktiven = 1").fetchone()[0]
    conn.close()
    return jsonify({
        "status": "ok",
        "narocila_v_bazi": narocila,
        "aktivni_uporabniki": aktivni,
    }), 200


if __name__ == "__main__":
    db.init_db()
    app.run(host="0.0.0.0", port=config.PORT)
