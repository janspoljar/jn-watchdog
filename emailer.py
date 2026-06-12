"""
emailer.py — Pošiljanje email alertov prek Resend API.
Grupira naročila po kategorijah in pošlje HTML email naročniku.
"""

import os
import logging
from datetime import datetime
from collections import defaultdict

import resend

import config

logger = logging.getLogger(__name__)

# Inicializiraj Resend klient
resend.api_key = config.RESEND_API_KEY

# Dry-run mode: emaili se NE pošljejo prek Resend, ampak zapišejo v datoteko.
# Vklop: main.py --dry-run (nastavi emailer.DRY_RUN = True).
DRY_RUN = False
DRY_RUN_FILE = os.getenv("DRY_RUN_FILE", "dry_run_emaili.txt")


def _zapisi_dry_run(prejemnik: str, zadeva: str, html: str):
    """Zapiše email v dry-run datoteko namesto pošiljanja."""
    with open(DRY_RUN_FILE, "a", encoding="utf-8") as f:
        f.write(
            f"\n{'=' * 70}\n"
            f"DRY-RUN | {datetime.now().isoformat()}\n"
            f"TO:      {prejemnik}\n"
            f"SUBJECT: {zadeva}\n"
            f"{'=' * 70}\n"
            f"{html}\n"
        )
    logger.info(f"[DRY-RUN] Email za {prejemnik} zapisan v {DRY_RUN_FILE}")

# Ikone za posamezne kategorije (za prikaz v emailu)
KATEGORIJE_IKONE = {
    "IT & Software": "💻",
    "Gradbeništvo": "🏗️",
    "Zdravstvo & Farmacija": "🏥",
    "Čiščenje & Vzdrževanje": "🧹",
    "Transport & Vozila": "🚌",
    "Energetika": "⚡",
    "Hrana & Catering": "🍎",
    "Okolje & Voda": "💧",
    "Obramba & Varnost": "🛡️",
    "Drugo": "📌",
}

# Bazni URL za direktne linke na naročila
EJN_URL = "https://ejn.gov.si"


def _grupiraj_po_kategorijah(narocila: list) -> dict:
    """
    Grupira seznam naročil po kategorijah.
    Naročilo z več kategorijami se pojavi v vsaki od njih.
    """
    import json

    skupine = defaultdict(list)
    for n in narocila:
        kategorije = n.get("kategorije", [])
        # Kategorije so lahko JSON string (iz baze) ali že list
        if isinstance(kategorije, str):
            try:
                kategorije = json.loads(kategorije or "[]")
            except json.JSONDecodeError:
                kategorije = []
        if not kategorije:
            kategorije = ["Drugo"]
        for kat in kategorije:
            skupine[kat].append(n)
    return dict(skupine)


def _sestavi_html(uporabnik_email: str, narocila: list) -> str:
    """
    Sestavi HTML vsebino emaila: glava, kategorije z naročili, footer.
    """
    danes = datetime.now().strftime("%d. %m. %Y")
    skupine = _grupiraj_po_kategorijah(narocila)

    # Glava emaila
    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 640px; margin: 0 auto; padding: 20px; color: #333;">
        <h2 style="color: #1a1a2e; border-bottom: 2px solid #1a73e8; padding-bottom: 8px;">
            Nova javna naročila — {danes}
        </h2>
        <p>Skupno število novih naročil: <strong>{len(narocila)}</strong></p>
    """

    # Sekcija za vsako kategorijo
    for kategorija, seznam in sorted(skupine.items()):
        ikona = KATEGORIJE_IKONE.get(kategorija, "📌")
        html += f"""
        <h3 style="background: #f0f4ff; padding: 8px 12px; border-radius: 6px; margin-top: 24px;">
            {ikona} {kategorija} ({len(seznam)})
        </h3>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse;">
        """
        for n in seznam:
            # Naziv omejimo na 100 znakov
            naziv = (n.get("naziv") or "Brez naziva")[:100]
            narocnik = n.get("narocnik") or "Neznan naročnik"
            rok = n.get("rok_oddaje") or "ni podan"
            html += f"""
            <tr>
                <td style="padding: 10px 12px; border-bottom: 1px solid #eee;">
                    <a href="{EJN_URL}" style="color: #1a73e8; font-weight: bold; text-decoration: none;">{naziv}</a><br>
                    <small style="color: #666;">{narocnik}</small><br>
                    <small>Rok oddaje: <span style="color: #d93025; font-weight: bold;">{rok}</span></small>
                </td>
            </tr>
            """
        html += "</table>"

    # Footer z odjava linkom
    html += f"""
        <hr style="margin-top: 32px; border: none; border-top: 1px solid #ddd;">
        <p style="font-size: 12px; color: #999;">
            Prejemate ta email, ker ste naročeni na JN Watchdog.<br>
            <a href="https://tvojadomena.si/odjava?email={uporabnik_email}" style="color: #999;">Odjava od obvestil</a>
        </p>
    </body>
    </html>
    """
    return html


def pošlji_email(uporabnik_email: str, narocila: list) -> bool:
    """
    Pošlje email alert z novimi naročili prek Resend.

    Args:
        uporabnik_email: Email naslov prejemnika.
        narocila:        Seznam naročil (slovarji iz baze ali scraperja).

    Returns:
        True če uspešno poslano, False sicer.
    """
    if not narocila:
        logger.info(f"Ni naročil za {uporabnik_email}, email preskočen.")
        return False

    danes = datetime.now().strftime("%d. %m. %Y")
    html = _sestavi_html(uporabnik_email, narocila)

    if DRY_RUN:
        _zapisi_dry_run(uporabnik_email, f"📋 {len(narocila)} novih javnih naročil — {danes}", html)
        return True

    try:
        odgovor = resend.Emails.send({
            "from": config.FROM_EMAIL,
            "to": uporabnik_email,
            "subject": f"📋 {len(narocila)} novih javnih naročil — {danes}",
            "html": html,
        })
        logger.info(f"Email poslan na {uporabnik_email}: {odgovor}")
        return True
    except Exception as e:
        logger.error(f"Napaka pri pošiljanju emaila na {uporabnik_email}: {e}")
        return False


def _pošlji_admin(zadeva: str, html: str) -> bool:
    """Pošlje email adminu (config.ADMIN_EMAIL). Vrne True ob uspehu."""
    if DRY_RUN:
        _zapisi_dry_run(config.ADMIN_EMAIL, zadeva, html)
        return True

    try:
        resend.Emails.send({
            "from": config.FROM_EMAIL,
            "to": config.ADMIN_EMAIL,
            "subject": zadeva,
            "html": html,
        })
        return True
    except Exception as e:
        logger.error(f"Napaka pri pošiljanju admin emaila: {e}")
        return False


def pošlji_alert_adminu(naslov: str, podrobnosti: str) -> bool:
    """
    Alert adminu ob kritični napaki (npr. popoln fail scraperja).
    """
    html = (
        "<html><body style='font-family: Arial; color: #333;'>"
        f"<h2 style='color: #d93025;'>⚠️ {naslov}</h2>"
        f"<pre style='background: #f5f5f5; padding: 12px; white-space: pre-wrap;'>{podrobnosti}</pre>"
        f"<p><small>Lovec — {datetime.now().strftime('%d. %m. %Y %H:%M')}</small></p>"
        "</body></html>"
    )
    return _pošlji_admin(f"⚠️ Lovec ALERT: {naslov}", html)


def pošlji_dnevni_povzetek(stats: dict) -> bool:
    """
    Dnevni povzetek joba adminu.

    Args:
        stats: {"scraped": int, "novih": int, "poslanih_emailov": int,
                "preskocenih": int, "napake": list[str]}
    """
    danes = datetime.now().strftime("%d. %m. %Y")
    napake = stats.get("napake") or []
    napake_html = (
        "<ul>" + "".join(f"<li>{n}</li>" for n in napake) + "</ul>"
        if napake else "<p>Brez napak. ✓</p>"
    )
    html = (
        "<html><body style='font-family: Arial; color: #333;'>"
        f"<h2>Lovec — dnevni povzetek {danes}</h2>"
        "<table cellpadding='6' style='border-collapse: collapse;'>"
        f"<tr><td>Pobranih naročil (scrape):</td><td><strong>{stats.get('scraped', 0)}</strong></td></tr>"
        f"<tr><td>Novih v bazi:</td><td><strong>{stats.get('novih', 0)}</strong></td></tr>"
        f"<tr><td>Poslanih emailov:</td><td><strong>{stats.get('poslanih_emailov', 0)}</strong></td></tr>"
        f"<tr><td>Preskočenih (že poslano danes):</td><td><strong>{stats.get('preskocenih', 0)}</strong></td></tr>"
        f"<tr><td>Napak:</td><td><strong>{len(napake)}</strong></td></tr>"
        "</table>"
        f"<h3>Napake</h3>{napake_html}"
        "</body></html>"
    )
    return _pošlji_admin(f"Lovec povzetek {danes}: {stats.get('poslanih_emailov', 0)} emailov, {len(napake)} napak", html)


def pošlji_test_email(email: str) -> bool:
    """
    Pošlje testni email s 3 dummy naročili — za preverbo Resend integracije.
    """
    dummy_narocila = [
        {
            "pjn": "JN-DUMMY-001",
            "naziv": "Razvoj spletne aplikacije za upravljanje dokumentov",
            "narocnik": "Ministrstvo za javno upravo",
            "rok_oddaje": "15. 07. 2026",
            "kategorije": ["IT & Software"],
        },
        {
            "pjn": "JN-DUMMY-002",
            "naziv": "Rekonstrukcija ceste in obnova kanalizacije",
            "narocnik": "Občina Maribor",
            "rok_oddaje": "20. 07. 2026",
            "kategorije": ["Gradbeništvo"],
        },
        {
            "pjn": "JN-DUMMY-003",
            "naziv": "Dobava zdravil za bolnišnično lekarno",
            "narocnik": "UKC Ljubljana",
            "rok_oddaje": "10. 07. 2026",
            "kategorije": ["Zdravstvo & Farmacija"],
        },
    ]
    return pošlji_email(email, dummy_narocila)


# ---------------------------------------------------------------------------
# Test ob direktnem zagonu — pošlje test email
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not config.RESEND_API_KEY:
        print("OPOZORILO: RESEND_API_KEY ni nastavljen v .env — email ne bo poslan.")
    else:
        uspeh = pošlji_test_email("jan.spoljar@gmail.com")
        print(f"Test email poslan: {uspeh}")
