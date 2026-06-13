"""
matching.py — AI matching naročil proti profilom strank (Faza 3).

Za vsako NOVO naročilo × aktiven profil pokličemo Claude (Haiku), ki vrne
strukturirano oceno {relevant, confidence, reason}. Odločitve shranimo v
tabelo `matching`, ki hkrati deluje kot cache: istega para (naročilo, profil)
nikoli ne ocenimo (in plačamo) dvakrat.

Optimizacije stroškov:
- samo nova naročila (cache prek matching tabele),
- batch obdelava (več naročil v enem klicu),
- prompt caching sistemskih navodil,
- varovalka MATCH_MAX_NA_ZAGON proti nepričakovanim stroškom.

API ključ in model prideta iz config (.env): ANTHROPIC_API_KEY, ANTHROPIC_MODEL.
"""

import json
import logging

import config
import db

logger = logging.getLogger(__name__)

SISTEM = (
    "Si pomočnik, ki za slovensko podjetje ocenjuje ustreznost javnih naročil. "
    "Za vsako naročilo presodi, ali je relevantno za podjetje glede na opis "
    "njegove dejavnosti. Bodi strog: če naročilo ni z njihovega področja, "
    "relevant=false in nizek confidence. "
    "Vrni IZKLJUČNO veljaven JSON seznam, brez kakršnegakoli dodatnega besedila. "
    "Vsak element naj ima ključe: "
    '"pjn" (oznaka naročila), "relevant" (true/false), '
    '"confidence" (število med 0.0 in 1.0), '
    '"reason" (en kratek stavek v slovenščini, zakaj je oz. ni za to podjetje). '
    "confidence naj odraža, kako gotovo je naročilo za to podjetje."
)


def _opis_profila(profil: dict) -> str:
    """Sestavi berljiv opis profila za model."""
    deli = []
    if profil.get("panoga"):
        deli.append(f"Panoga: {profil['panoga']}.")
    izbrani = profil.get("izbrani") or []
    if izbrani:
        deli.append("Dejavnosti: " + ", ".join(izbrani) + ".")
    if profil.get("opis"):
        deli.append(f"Dodaten opis: {profil['opis']}.")
    regije = profil.get("regije")
    if regije:
        if isinstance(regije, str):
            try:
                regije = json.loads(regije)
            except json.JSONDecodeError:
                regije = [regije]
        if regije:
            deli.append("Regije: " + ", ".join(regije) + ".")
    return " ".join(deli) or "Splošna dejavnost (brez podrobnega opisa)."


def _vrstica_narocila(n: dict) -> str:
    """Ena vrstica naročila za prompt."""
    return (
        f"- PJN: {n.get('pjn')} | Naziv: {n.get('naziv', '')} | "
        f"Naročnik: {n.get('narocnik', '')} | Vrsta: {n.get('vrsta', '')}"
    )


def _razcleni_json(besedilo: str) -> list:
    """
    Robustno izlušči JSON seznam iz odgovora modela. Vrne list ali [].
    """
    if not besedilo:
        return []
    zac = besedilo.find("[")
    kon = besedilo.rfind("]")
    if zac == -1 or kon == -1 or kon < zac:
        return []
    try:
        podatki = json.loads(besedilo[zac:kon + 1])
        return podatki if isinstance(podatki, list) else []
    except json.JSONDecodeError:
        logger.warning("Matching: odgovora modela ni bilo mogoče razčleniti kot JSON.")
        return []


def _klici_model(opis_profila: str, narocila: list) -> list:
    """
    En klic na model za batch naročil. Vrne seznam ocen (dict).
    Ob napaki vrne prazen seznam (naročila se ponovno poskusijo naslednjič).
    """
    import anthropic

    if not config.ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY ni nastavljen — AI matching preskočen.")
        return []

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    seznam = "\n".join(_vrstica_narocila(n) for n in narocila)
    uporabnik = (
        f"Podjetje:\n{opis_profila}\n\n"
        f"Naročila za oceno ({len(narocila)}):\n{seznam}\n\n"
        "Vrni JSON seznam ocen za vsa našteta naročila."
    )
    try:
        odgovor = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=2000,
            system=[{
                "type": "text",
                "text": SISTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": uporabnik}],
        )
        besedilo = "".join(
            blok.text for blok in odgovor.content if getattr(blok, "type", "") == "text"
        )
        return _razcleni_json(besedilo)
    except Exception as e:
        logger.error(f"Matching: napaka pri klicu modela: {e}")
        return []


def oceni_profil(profil: dict, narocila: list) -> int:
    """
    Oceni podana (nova) naročila za en profil in shrani odločitve v bazo.
    Naročila razdeli v batche po config.MATCH_BATCH.

    Returns:
        Število shranjenih ocen.
    """
    if not narocila:
        return 0
    opis = _opis_profila(profil)
    po_pjn = {n.get("pjn"): n for n in narocila}
    shranjenih = 0

    for i in range(0, len(narocila), config.MATCH_BATCH):
        batch = narocila[i:i + config.MATCH_BATCH]
        ocene = _klici_model(opis, batch)
        for ocena in ocene:
            pjn = ocena.get("pjn")
            if pjn not in po_pjn:
                continue
            try:
                conf = float(ocena.get("confidence", 0.0))
            except (TypeError, ValueError):
                conf = 0.0
            conf = max(0.0, min(1.0, conf))
            db.shrani_matching(
                pjn=pjn,
                profil_id=profil["id"],
                relevant=bool(ocena.get("relevant", False)),
                confidence=conf,
                reason=(ocena.get("reason") or "").strip()[:300],
            )
            shranjenih += 1

    logger.info(f"Profil {profil['id']}: shranjenih {shranjenih} ocen.")
    return shranjenih


def pozeni_matching(narocila: list) -> dict:
    """
    Glavni vstop: za vsa aktivna profila oceni tista podana naročila, ki za
    profil še niso ocenjena (cache). Spoštuje varovalko MATCH_MAX_NA_ZAGON.

    Args:
        narocila: seznam naročil (dict s ključi pjn, naziv, narocnik, vrsta).

    Returns:
        Statistika: {"profilov": int, "ocen": int, "preskoceno_limit": bool}.
    """
    profili = db.poberi_aktivne_profile()
    if not profili:
        logger.info("Matching: ni aktivnih profilov.")
        return {"profilov": 0, "ocen": 0, "preskoceno_limit": False}

    skupaj_ocen = 0
    limit = config.MATCH_MAX_NA_ZAGON
    presezen = False

    for profil in profili:
        ze = db.ze_ocenjeni_pjn_za_profil(profil["id"])
        nova = [n for n in narocila if n.get("pjn") not in ze]
        if not nova:
            continue
        # Varovalka stroškov — ne presezi limita ocen na zagon
        if skupaj_ocen + len(nova) > limit:
            nova = nova[: max(0, limit - skupaj_ocen)]
            presezen = True
        if not nova:
            break
        skupaj_ocen += oceni_profil(profil, nova)
        if presezen:
            logger.warning(f"Matching: dosežen limit {limit} ocen na zagon — ustavljam.")
            break

    logger.info(f"Matching končan: {len(profili)} profilov, {skupaj_ocen} ocen.")
    return {"profilov": len(profili), "ocen": skupaj_ocen, "preskoceno_limit": presezen}
