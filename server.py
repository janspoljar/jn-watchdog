"""
server.py — Flask API strežnik
Upravljanje naročnin, Stripe webhookov in registracije naročnikov.
"""

import stripe
import logging
from flask import Flask, request, jsonify
from config import STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
from db import inicializiraj_bazo, dodaj_narocnika, posodobi_stripe_podatke

# Nastavi logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inicializiraj Flask aplikacijo
app = Flask(__name__)

# Nastavi Stripe
stripe.api_key = STRIPE_SECRET_KEY

# Cena naročnine v centih (19 EUR)
CENA_MESECNO = 1900


@app.route("/health", methods=["GET"])
def zdravje():
    """Preverba, da strežnik deluje."""
    return jsonify({"status": "ok"}), 200


@app.route("/register", methods=["POST"])
def registracija():
    """
    Registracija novega naročnika.
    Pričakuje JSON: { "email": "..." }
    """
    podatki = request.get_json()
    email = podatki.get("email")

    if not email:
        return jsonify({"napaka": "Email je obvezen."}), 400

    # Dodaj v bazo
    dodan = dodaj_narocnika(email)
    if not dodan:
        return jsonify({"sporocilo": "Email že obstaja."}), 200

    logger.info(f"Nov naročnik registriran: {email}")
    return jsonify({"sporocilo": "Registracija uspešna."}), 201


@app.route("/checkout", methods=["POST"])
def checkout():
    """
    Ustvari Stripe Checkout sejo za plačilo naročnine.
    Pričakuje JSON: { "email": "..." }
    """
    podatki = request.get_json()
    email = podatki.get("email")

    if not email:
        return jsonify({"napaka": "Email je obvezen."}), 400

    try:
        seja = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            customer_email=email,
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": "jn-watchdog — Mesečna naročnina"},
                    "unit_amount": CENA_MESECNO,
                    "recurring": {"interval": "month"},
                },
                "quantity": 1,
            }],
            success_url="https://tvojadomena.si/uspeh?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="https://tvojadomena.si/preklicano",
        )
        return jsonify({"checkout_url": seja.url}), 200
    except stripe.error.StripeError as e:
        logger.error(f"Stripe napaka: {e}")
        return jsonify({"napaka": str(e)}), 500


@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    """
    Stripe webhook za obdelavo plačilnih dogodkov.
    Aktivira ali deaktivira naročnino ob plačilu/odpovedi.
    """
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.error(f"Webhook napaka: {e}")
        return jsonify({"napaka": "Neveljaven webhook"}), 400

    # Obdelaj relevantne dogodke
    if event["type"] == "checkout.session.completed":
        seja = event["data"]["object"]
        email = seja.get("customer_email")
        customer_id = seja.get("customer")
        subscription_id = seja.get("subscription")
        posodobi_stripe_podatke(email, customer_id, subscription_id, aktivno=1)
        logger.info(f"Naročnina aktivirana za: {email}")

    elif event["type"] == "customer.subscription.deleted":
        narocnina = event["data"]["object"]
        customer_id = narocnina.get("customer")
        # TODO: poišči email po customer_id in deaktiviraj
        logger.info(f"Naročnina prekinjena za customer: {customer_id}")

    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    inicializiraj_bazo()
    app.run(debug=True, port=5000)
