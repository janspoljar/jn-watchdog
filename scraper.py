"""
scraper.py - Scraper za javna narocila z ejn.gov.si
Pobira narocila, jih kategorizira in shrani v SQLite bazo.
"""

import re
import time
import requests
from bs4 import BeautifulSoup
import logging
from datetime import datetime
from collections import Counter

import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

EJN_BASE_URL = "https://ejn.gov.si"

# JSF stran z aktualnimi javnimi naročili in ID-ji form/table komponent
BASE_URL = "https://ejn.gov.si/ponudba/pages/aktualno/aktualna_javna_narocila.xhtml"
FORM_ID = "iskalnik_aktualnih_jn_data_table_form"
TABLE_ID = f"{FORM_ID}:iskalnik_aktualnih_jn_data_table:iskalnik_aktualnih_jn_data_table"

HEADERS_GET = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "sl,en-US;q=0.7,en;q=0.3",
}

HEADERS_POST = {
    **HEADERS_GET,
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": BASE_URL,
}

# ---------------------------------------------------------------------------
# Keyword kategorizer
# ---------------------------------------------------------------------------

# Kljucne besede so krajse (stemi) da ujamejo razlicne sklone in oblike.
# Npr. "zdravil" ujame "zdravila", "zdravil", "zdravilih" itd.
KATEGORIJE_KLJUCNE_BESEDE = {
    "IT & Software": [
        "programsk", "informacijski sistem", "aplikacij", "spletna stran",
        "razvoj", "streznik", "licenc", " it ", "digitalizacij",
        "vzdrzevanje sistem", "podatkovna", "kibernetsk", "omrezj",
        "racunalnik", "tiskalnik", "kartus", "toner",
    ],
    "Gradbeništvo": [
        "gradnj", "rekonstrukcij", "sanacij", "obnov", "asfalt",
        "kanalizacij", "vodovod", "most", "cest", "fasad", "streh",
        "komunaln", "zemeljsk", "tlakovana", "betonsk", "armatur",
        "gradbeni nadzor",
    ],
    "Zdravstvo & Farmacija": [
        "zdravil", "medicinsk", "ultrazvok", "sterilizacij",
        "farmacevtsk", "laboratorij", "resevalno vozil", "bolnisnic",
        "ortopedsk", "implantat", "kirursk",
    ],
    "Čiščenje & Vzdrževanje": [
        "ciscenj", "varovanj", "vzdrzevanje objekt", "komunaln",
        "odpadk", "snaga", "dezinfekcij", "razkuzevanj",
    ],
    "Transport & Vozila": [
        "vozil", "avtobus", "prevoz", "solski prevoz", "tovornjak",
        "dostavno", "resevalno", "goriv", "bencin", "dizel",
    ],
    "Energetika": [
        "elektricn", "plin", "toplota", "soncn", "obnovljiv",
        "transformator", "elektro", "razsvetljav", "fotovoltaik",
    ],
    "Hrana & Catering": [
        "zivil", "hrana", "catering", "prehrana", "ekolosk", "mlecn",
        "meso", "zelenjav", "sadj", "kruh", "pekarni",
    ],
    "Okolje & Voda": [
        "cistilna naprav", "monitoring", "pitna voda", "odpadne vode",
        "okolj", "emisij", "ekolosk",
    ],
    "Obramba & Varnost": [
        "ministrstvo za obrambo", "vojsk", "orozj", "varnostna oprema",
        "gasilsk", "zascit",
    ],
}

# Imena kategorij za prikaz (kljuc = interni kljuc, vrednost = prikaz ime)
KATEGORIJE_PRIKAZ = {k: k for k in KATEGORIJE_KLJUCNE_BESEDE}


def _normaliziraj(besedilo: str) -> str:
    """
    Pretvori besedilo v lowercase in zamenja slovenske posebne znake z ASCII,
    da kljucne besede delajo ne glede na kodiranje vira.
    """
    # Eksplicitna mapa: slovenika -> ASCII
    prevod = str.maketrans(
        "šžčŠŽČćđ",
        "szczSZCcd"[:8]
    )
    return besedilo.lower().translate(prevod)


def kategorize(naziv: str) -> list:
    """
    Sprejme naziv narocila in vrne seznam ujemajocih se kategorij.
    Ce ne ustreza nobeni, vrne ["Drugo"]. Primerjava je case-insensitive.

    Args:
        naziv: Naziv narocila.

    Returns:
        Seznam imen kategorij, npr. ["IT & Software"] ali ["Drugo"].
    """
    normiran = _normaliziraj(naziv)
    ujemanja = []

    for kljuc, kljucne_besede in KATEGORIJE_KLJUCNE_BESEDE.items():
        for kw in kljucne_besede:
            if kw in normiran:
                prikaz = KATEGORIJE_PRIKAZ.get(kljuc, kljuc)
                if prikaz not in ujemanja:
                    ujemanja.append(prikaz)
                break  # Ze nasli za to kategorijo

    return ujemanja if ujemanja else ["Drugo"]


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def poberi_narocila(max_strani: int = 33) -> list:
    """
    Scrapa seznam javnih narocil z ejn.gov.si.
    Prva stran gre prek GET, naslednje prek JSF AJAX POST paginacije
    (javax.faces partial requests z ViewState).

    Returns:
        Seznam narocil kot slovarjev, ze s poljem 'kategorije'.
    """
    session = requests.Session()

    # Prva stran GET — iz nje poberemo tudi ViewState za paginacijo
    r = session.get(BASE_URL, headers=HEADERS_GET)
    soup = BeautifulSoup(r.text, "html.parser")
    viewstate = soup.find("input", {"name": "javax.faces.ViewState"})["value"]

    narocila = []
    videni_pjn = set()

    # Poberi prvo stran
    for n in _razcleni_tabelo(r.text):
        if n["pjn"] not in videni_pjn:
            narocila.append(n)
            videni_pjn.add(n["pjn"])

    logger.info(f"Stran 1: {len(narocila)} naročil")

    # Paginacija POST — JSF partial AJAX request za vsako naslednjo stran
    for stran in range(1, max_strani):
        post_data = {
            "javax.faces.partial.ajax": "true",
            "javax.faces.source": TABLE_ID,
            "javax.faces.partial.execute": TABLE_ID,
            "javax.faces.partial.render": TABLE_ID,
            "javax.faces.behavior.event": "page",
            "javax.faces.partial.event": "page",
            f"{TABLE_ID}_pagination": "true",
            f"{TABLE_ID}_first": str(stran * 50),
            f"{TABLE_ID}_rows": "50",
            f"{TABLE_ID}_skipChildren": "true",
            f"{TABLE_ID}_encodeFeature": "true",
            FORM_ID: FORM_ID,
            f"{TABLE_ID}_rppDD": "50",
            "javax.faces.ViewState": viewstate,
        }

        r = session.post(BASE_URL, headers=HEADERS_POST, data=post_data)

        # Posodobi ViewState iz XML odgovora
        xml_soup = BeautifulSoup(r.text, "lxml-xml")
        new_vs = xml_soup.find("update", {"id": re.compile("ViewState")})
        if new_vs:
            viewstate = new_vs.text.strip()

        # Izvleči HTML chunk s tabelo
        html_chunk = xml_soup.find("update", {"id": TABLE_ID})
        if not html_chunk:
            break

        nova = _razcleni_tabelo(html_chunk.text)
        novi = [n for n in nova if n["pjn"] not in videni_pjn]

        if not novi:
            break

        for n in novi:
            narocila.append(n)
            videni_pjn.add(n["pjn"])

        logger.info(f"Stran {stran+1}: {len(novi)} novih (skupaj: {len(narocila)})")
        time.sleep(0.3)  # Bodi prijazen do strežnika

    return narocila


def _razcleni_tabelo(html_text: str) -> list:
    """
    Razcleni HTML tabelo naročil (vrstice z atributom data-ri) v seznam slovarjev.

    Stolpci (0-indeks): [0] Naročnik [1] Naziv [3] Vrsta [5] PJN
                        [6] Datum objave [7] Rok oddaje [9] Stanje
    """
    soup = BeautifulSoup(html_text, "html.parser")
    rows = soup.select("tr[data-ri]")
    narocila = []
    for row in rows:
        cols = row.find_all("td")
        if len(cols) == 10:
            naziv = cols[1].get_text(strip=True)
            narocila.append({
                "pjn":          cols[5].get_text(strip=True),
                "narocnik":     cols[0].get_text(strip=True),
                "naziv":        naziv,
                "vrsta":        cols[3].get_text(strip=True),
                "datum_objave": cols[6].get_text(strip=True),
                "rok_oddaje":   cols[7].get_text(strip=True),
                "stanje":       cols[9].get_text(strip=True),
                "kategorije":   kategorize(naziv),
                "datum_scrape": datetime.now().isoformat(),
            })
    return narocila


def scrape_in_shrani(max_strani: int = 33) -> int:
    """Pozeni scraping in shrani v bazo. Vrne stevilo novih narocil."""
    narocila = poberi_narocila(max_strani=max_strani)
    if not narocila:
        logger.warning("Scraper ni vrnil nobenega narocila.")
        return 0
    novo = db.shrani_narocila(narocila)
    logger.info(f"Novih v bazi: {novo} (od {len(narocila)} pobranih).")
    return novo


# ---------------------------------------------------------------------------
# Testni zagon
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sqlite3
    import json
    from config import DB_PATH

    db.init_db()

    print("=" * 60)
    print("Pozivam scraper (max 3 strani za test)...")
    print("=" * 60)

    narocila = poberi_narocila(max_strani=3)
    print(f"\nPobranih narocil: {len(narocila)}")

    if narocila:
        novo = db.shrani_narocila(narocila)
        print(f"Novih v bazi: {novo}")
    else:
        print("Scraper ni vrnil narocil — ustvarjam vzorcna narocila za test...")
        narocila = [
            {"pjn": "JN-TEST-001", "naziv": "Razvoj informacijskega sistema za e-upravo",
             "narocnik": "MJU", "vrsta": "Storitve", "datum_objave": "2024-06-01",
             "rok_oddaje": "2024-07-01", "stanje": "Objavljeno", "kategorije": [],
             "datum_scrape": datetime.now().isoformat()},
            {"pjn": "JN-TEST-002", "naziv": "Rekonstrukcija lokalne ceste v Kopru",
             "narocnik": "Obcina Koper", "vrsta": "Gradnja", "datum_objave": "2024-06-02",
             "rok_oddaje": "2024-07-15", "stanje": "Objavljeno", "kategorije": [],
             "datum_scrape": datetime.now().isoformat()},
            {"pjn": "JN-TEST-003", "naziv": "Dobava zdravil in medicinskih pripomockov",
             "narocnik": "UKC Ljubljana", "vrsta": "Blago", "datum_objave": "2024-06-03",
             "rok_oddaje": "2024-07-10", "stanje": "Objavljeno", "kategorije": [],
             "datum_scrape": datetime.now().isoformat()},
            {"pjn": "JN-TEST-004", "naziv": "Ciscenje poslovnih prostorov",
             "narocnik": "FURS", "vrsta": "Storitve", "datum_objave": "2024-06-04",
             "rok_oddaje": "2024-07-20", "stanje": "Objavljeno", "kategorije": [],
             "datum_scrape": datetime.now().isoformat()},
            {"pjn": "JN-TEST-005", "naziv": "Dobava pisarniskega materiala in tonerjev",
             "narocnik": "RS - MF", "vrsta": "Blago", "datum_objave": "2024-06-05",
             "rok_oddaje": "2024-07-05", "stanje": "Objavljeno", "kategorije": [],
             "datum_scrape": datetime.now().isoformat()},
            {"pjn": "JN-TEST-006", "naziv": "Solski prevoz otrok",
             "narocnik": "OE Novo Mesto", "vrsta": "Storitve", "datum_objave": "2024-06-05",
             "rok_oddaje": "2024-07-25", "stanje": "Objavljeno", "kategorije": [],
             "datum_scrape": datetime.now().isoformat()},
            {"pjn": "JN-TEST-007", "naziv": "Dobava elektricne energije za javne objekte",
             "narocnik": "ZD Celje", "vrsta": "Blago", "datum_objave": "2024-06-06",
             "rok_oddaje": "2024-08-01", "stanje": "Objavljeno", "kategorije": [],
             "datum_scrape": datetime.now().isoformat()},
        ]
        for n in narocila:
            n["kategorije"] = kategorize(n["naziv"])
        novo = db.shrani_narocila(narocila)
        print(f"Vzorcnih narocil v bazi: {novo}")

    # Top 5 kategorij
    print("\n--- Top 5 kategorij ---")
    conn = sqlite3.connect(DB_PATH)
    vrstice_db = conn.execute("SELECT kategorije FROM narocila").fetchall()
    conn.close()

    stevec = Counter()
    for (kat_json,) in vrstice_db:
        try:
            kats = json.loads(kat_json or "[]")
        except Exception:
            kats = ["Drugo"]
        for k in kats:
            stevec[k] += 1

    for i, (kat, stevilo) in enumerate(stevec.most_common(5), 1):
        print(f"  {i}. {kat}: {stevilo}")

    # 3 nakljucna narocila
    print("\n--- 3 nakljucna narocila ---")
    conn = sqlite3.connect(DB_PATH)
    vzorec = conn.execute(
        "SELECT pjn, naziv, narocnik, kategorije FROM narocila ORDER BY RANDOM() LIMIT 3"
    ).fetchall()
    conn.close()

    for pjn, naziv, narocnik, kat_json in vzorec:
        try:
            kats = json.loads(kat_json or "[]")
        except Exception:
            kats = ["Drugo"]
        print(f"  PJN:        {pjn}")
        print(f"  Naziv:      {naziv}")
        print(f"  Narocnik:   {narocnik}")
        print(f"  Kategorije: {', '.join(kats)}")
        print()
