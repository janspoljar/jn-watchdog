"""
pregled.py — Logika brezplačnega pregleda (lead magnet, Faza 4).

Uporabnik izbere panogo, odkljuka podpodročja in/ali dopiše prosto besedilo.
Iz tega sestavimo nabor ključnih besed, jih primerjamo z nazivi naročil
zadnjih 30 dni (keyword matching, brez AI — AI pride v Fazi 3) in vrnemo
seznam "zamujenih" naročil ter HTML poročilo za email.
"""

import re
import logging
from datetime import datetime

import db
import panoge
from scraper import _normaliziraj

logger = logging.getLogger(__name__)

# Minimalna dolžina besede iz prostega besedila (da "in", "za" ne ujamejo vsega)
MIN_DOLZINA_BESEDE = 4

# Pogoste slovenske vezne/nepomembne besede — izločimo iz prostega besedila
STOP_BESEDE = {
    "ter", "tudi", "samo", "vse", "vsa", "kar", "tega", "tako", "lahko",
    "delamo", "delam", "izvajamo", "izvajam", "podjetje", "smo", "sem",
    "nasa", "nase", "nasi", "dejavnost", "storitve", "storitev", "izvajanje",
}


def _besede_iz_prostega(besedilo: str) -> list:
    """
    Iz prostega besedila izlušči smiselne ASCII-normalizirane stemme.
    Obdrži besede >= MIN_DOLZINA_BESEDE, brez stop-besed.
    """
    if not besedilo:
        return []
    normiran = _normaliziraj(besedilo)
    surove = re.findall(r"[a-z0-9]+", normiran)
    besede = [
        b for b in surove
        if len(b) >= MIN_DOLZINA_BESEDE and b not in STOP_BESEDE
    ]
    return list(dict.fromkeys(besede))


def sestavi_iskalne_besede(panoga_key: str, izbrani_labeli: list, prosto_besedilo: str) -> list:
    """
    Združi ključne besede iz izbranih podpodročij panoge + prostega besedila.

    Če uporabnik ni izbral nobenega podpodročja, vzamemo VSE besede panoge
    (širok zajem — raje pokažemo več kot premalo).
    """
    if izbrani_labeli:
        besede = panoge.vse_besede_za_panogo(panoga_key, izbrani_labeli)
    else:
        besede = panoge.vse_besede_za_panogo(panoga_key, None)

    besede = list(besede) + _besede_iz_prostega(prosto_besedilo)
    return list(dict.fromkeys(besede))


def najdi_zamujena(panoga_key: str, izbrani_labeli: list, prosto_besedilo: str,
                   dni: int = 30, limit: int = 30) -> list:
    """
    Vrne naročila zadnjih `dni` dni, katerih naziv ali naročnik vsebuje
    katero od iskalnih besed. Vsako naročilo dobi 'zadetki' — seznam besed,
    ki so se ujele (za morebiten prikaz). Sortirano po številu zadetkov.

    Args:
        panoga_key:      ključ panoge.
        izbrani_labeli:  izbrana podpodročja (labeli).
        prosto_besedilo: prosto besedilo uporabnika.
        dni:             časovno okno (privzeto 30).
        limit:           največ vrnjenih naročil.

    Returns:
        Seznam slovarjev naročil (z dodanim poljem 'zadetki').
    """
    iskalne = sestavi_iskalne_besede(panoga_key, izbrani_labeli, prosto_besedilo)
    if not iskalne:
        return []

    narocila = db.poberi_narocila_zadnjih_dni(dni)
    rezultati = []
    for n in narocila:
        besedilo = _normaliziraj(f"{n.get('naziv', '')} {n.get('narocnik', '')}")
        zadetki = [b for b in iskalne if b in besedilo]
        if zadetki:
            n = dict(n)
            n["zadetki"] = zadetki
            rezultati.append(n)

    # Več ujemanj = bolj relevantno
    rezultati.sort(key=lambda x: len(x["zadetki"]), reverse=True)
    return rezultati[:limit]


def sestavi_html_pregled(panoga_ime: str, narocila: list, dni: int = 30) -> str:
    """
    Sestavi HTML poročilo brezplačnega pregleda za email.
    """
    danes = datetime.now().strftime("%d. %m. %Y")
    stevilo = len(narocila)

    if stevilo == 0:
        vsebina = """
        <p>V zadnjih 30 dneh nismo našli javnih naročil, ki bi se ujemala z
        vašim opisom. To se zgodi pri zelo specifičnih dejavnostih — pišite nam
        in skupaj nastaviva profil, da ne zamudite ničesar.</p>
        """
    else:
        vrstice = ""
        for n in narocila:
            naziv = (n.get("naziv") or "Brez naziva")[:140]
            narocnik = n.get("narocnik") or "Neznan naročnik"
            rok = n.get("rok_oddaje") or "ni podan"
            vrstice += f"""
            <tr>
                <td style="padding: 12px; border-bottom: 1px solid #eee;">
                    <strong style="color: #1a1a2e;">{naziv}</strong><br>
                    <small style="color: #666;">{narocnik}</small><br>
                    <small>Rok oddaje: <span style="color: #d93025; font-weight: bold;">{rok}</span></small>
                </td>
            </tr>
            """
        vsebina = f"""
        <p>V zadnjih 30 dneh smo našli <strong>{stevilo}</strong> javnih naročil,
        ki se ujemajo z vašo dejavnostjo <strong>{panoga_ime}</strong>:</p>
        <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse: collapse; margin-top: 16px;">
            {vrstice}
        </table>
        <p style="margin-top: 24px; padding: 16px; background: #f0f4ff; border-radius: 8px;">
            To je le pregled zadnjega meseca. Z naročnino <strong>Lovec</strong> jih
            prejemate samodejno na email, takoj ko izidejo — nikoli več zamujenega razpisa.
        </p>
        """

    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 640px; margin: 0 auto; padding: 20px; color: #333;">
        <h2 style="color: #1a1a2e; border-bottom: 2px solid #1a73e8; padding-bottom: 8px;">
            Vaš brezplačni pregled javnih naročil
        </h2>
        <p style="color: #666;">Pripravljeno {danes} za panogo: <strong>{panoga_ime}</strong></p>
        {vsebina}
        <hr style="margin-top: 32px; border: none; border-top: 1px solid #ddd;">
        <p style="font-size: 12px; color: #999;">
            Pregled vam je poslal Lovec — alerti o javnih naročilih.<br>
            Prejeli ste ga, ker ste oddali zahtevo za brezplačni pregled na javna-narocila.si.
        </p>
    </body>
    </html>
    """
