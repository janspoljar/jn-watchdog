"""
emailer.py — Pošiljanje email alertov prek Resend API
Tedenski pregled novih javnih naročil za naročnike.
"""

import resend
import logging
from config import RESEND_API_KEY, FROM_EMAIL

logger = logging.getLogger(__name__)

# Inicializiraj Resend klient
resend.api_key = RESEND_API_KEY


def sestavi_html_email(narocila, prejemnik_email):
    """
    Sestavi HTML vsebino email alerta.

    Args:
        narocila (list): Seznam naročil kot slovarjev
        prejemnik_email (str): Email prejemnika

    Returns:
        str: HTML vsebina emaila
    """
    vrstice = ""
    for n in narocila:
        url = n.get("url", "#")
        naslov = n.get("naslov", "Brez naslova")
        narocnik = n.get("narocnik", "Neznano")
        datum = n.get("datum_objave", "")

        vrstice += f"""
        <tr>
            <td style="padding: 10px; border-bottom: 1px solid #eee;">
                <a href="{url}" style="color: #1a73e8; font-weight: bold;">{naslov}</a><br>
                <small style="color: #666;">{narocnik} | {datum}</small>
            </td>
        </tr>
        """

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #333;">Tedenski pregled javnih naročil</h2>
        <p>Pozdravljeni,</p>
        <p>Ta teden je bilo objavljenih <strong>{len(narocila)}</strong> novih javnih naročil:</p>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse;">
            {vrstice}
        </table>
        <hr style="margin-top: 30px;">
        <p style="font-size: 12px; color: #999;">
            Prejemate ta email, ker ste naročeni na jn-watchdog.
            Za odjavo nam pišite na {FROM_EMAIL}.
        </p>
    </body>
    </html>
    """
    return html


def posli_alert(prejemnik_email, narocila):
    """
    Pošlje email alert z novimi javnimi naročili.

    Args:
        prejemnik_email (str): Email naslov prejemnika
        narocila (list): Seznam novih naročil

    Returns:
        bool: True če uspešno poslano
    """
    if not narocila:
        logger.info(f"Ni novih naročil za {prejemnik_email}, email preskočen.")
        return False

    html_vsebina = sestavi_html_email(narocila, prejemnik_email)

    try:
        odgovor = resend.Emails.send({
            "from": FROM_EMAIL,
            "to": prejemnik_email,
            "subject": f"Tedenska naročila — {len(narocila)} novih naročil",
            "html": html_vsebina,
        })
        logger.info(f"Email uspešno poslan na {prejemnik_email}: {odgovor}")
        return True
    except Exception as e:
        logger.error(f"Napaka pri pošiljanju emaila na {prejemnik_email}: {e}")
        return False


def posli_vsem_narocnikom(narocniki, narocila):
    """
    Pošlje alert vsem aktivnim naročnikom.

    Args:
        narocniki (list): Seznam aktivnih naročnikov
        narocila (list): Seznam novih naročil
    """
    uspesno = 0
    neuspesno = 0

    for narocnik in narocniki:
        email = narocnik.get("email")
        if posli_alert(email, narocila):
            uspesno += 1
        else:
            neuspesno += 1

    logger.info(f"Alerti poslani: {uspesno} uspešno, {neuspesno} neuspešno.")
