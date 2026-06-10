"""
scraper.py - Scraper za javna narocila z ejn.gov.si
Pobira narocila, jih kategorizira in shrani v SQLite bazo.
"""

import requests
from bs4 import BeautifulSoup
import logging
from datetime import datetime
from collections import Counter

import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

EJN_BASE_URL = "https://ejn.gov.si"
EJN_SEARCH_URL = (
    "https://ejn.gov.si/ponudnik/pages/aktualno/aktualno_javno_narocilo_searching.zul"
)

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
    "Gradbenistvo": [
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
    "Ciscenje & Vzdrzevanje": [
        "ciscenj", "varovanij", "vzdrzevanje objekt", "komunaln",
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

def poberi_narocila(max_strani: int = 10) -> list:
    """
    Scrapa seznam javnih narocil z ejn.gov.si.

    Stolpci v tabeli (0-indeks):
        [0] PJN  [1] Naziv  [2] Narocnik  [3] Vrsta  [4] Datum objave
        [5] Stanje  [6] Tip  [7] Rok za oddajo ponudbe

    Returns:
        Seznam narocil kot slovarjev, ze s poljem 'kategorije'.
    """
    narocila = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    for stran in range(1, max_strani + 1):
        logger.info(f"Scrapam stran {stran}/{max_strani}...")
        try:
            response = requests.get(
                EJN_SEARCH_URL,
                headers=headers,
                params={"page": stran},
                timeout=30,
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.error(f"Napaka pri prenosu strani {stran}: {e}")
            break

        soup = BeautifulSoup(response.text, "lxml")
        # EJN portal uporablja ZK framework - tabela z narocili
        vrstice = soup.select("table.z-listbox-body tr, tr.z-row, tr[data-pjn]")
        if not vrstice:
            vrstice = soup.find_all("tr", class_=lambda c: c and "row" in c.lower())
        if not vrstice:
            logger.info(f"Stran {stran}: ni vrstic, konec paginacije.")
            break

        nova_na_strani = 0
        for vrstica in vrstice:
            narocilo = _razcleni_vrstico(vrstica)
            if narocilo:
                narocila.append(narocilo)
                nova_na_strani += 1

        logger.info(f"Stran {stran}: razclenjenih {nova_na_strani} narocil.")
        if nova_na_strani == 0:
            break

    logger.info(f"Skupaj pobranih narocil: {len(narocila)}")
    return narocila


def _razcleni_vrstico(vrstica) -> dict | None:
    """
    Razcleni eno <tr> vrstico tabele v slovar narocila.

    Vrne None za header vrstice in vrstice z premalo celicami.
    """
    try:
        celice = vrstica.find_all(["td", "th"])
        if len(celice) < 5 or celice[0].name == "th":
            return None

        def cel(i: int) -> str:
            return celice[i].get_text(separator=" ", strip=True) if i < len(celice) else ""

        pjn = cel(0)
        naziv = cel(1)
        if not pjn or not naziv:
            return None

        return {
            "pjn": pjn,
            "naziv": naziv,
            "narocnik": cel(2),
            "vrsta": cel(3),
            "datum_objave": cel(4),
            "stanje": cel(5),
            "rok_oddaje": cel(7),  # stolpec [7] — rok za oddajo ponudbe
            "kategorije": kategorize(naziv),
            "datum_scrape": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.debug(f"Napaka pri razclenjvanju vrstice: {e}")
        return None


def scrape_in_shrani(max_strani: int = 10) -> int:
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
