"""
db.py — Upravljanje SQLite baze podatkov za jn-watchdog
Vse operacije z naročili, uporabniki in email logi.
"""

import sqlite3
import json
import logging
from datetime import datetime
from config import DB_PATH

logger = logging.getLogger(__name__)


def _poveži():
    """Vrne novo SQLite povezavo z row_factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Inicializacija baze
# ---------------------------------------------------------------------------

def init_db():
    """
    Ustvari tabele narocila, uporabniki in email_logi, če še ne obstajajo.
    Varno za večkratni klic.
    """
    conn = _poveži()
    cur = conn.cursor()

    # Tabela javnih naročil
    cur.execute("""
        CREATE TABLE IF NOT EXISTS narocila (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            pjn           TEXT    UNIQUE NOT NULL,
            narocnik      TEXT,
            naziv         TEXT,
            vrsta         TEXT,
            datum_objave  TEXT,
            rok_oddaje    TEXT,
            stanje        TEXT,
            kategorije    TEXT,
            datum_scrape  TEXT,
            poslano       INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Tabela naročnikov
    cur.execute("""
        CREATE TABLE IF NOT EXISTS uporabniki (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            email              TEXT    UNIQUE NOT NULL,
            kategorije         TEXT,
            aktiven            INTEGER NOT NULL DEFAULT 0,
            datum_registracije TEXT,
            stripe_customer_id TEXT
        )
    """)

    # Tabela za beleženje poslanih emailov
    cur.execute("""
        CREATE TABLE IF NOT EXISTS email_logi (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            uporabnik_id     INTEGER NOT NULL,
            datum_poslanega  TEXT,
            stevilo_narocil  INTEGER,
            FOREIGN KEY (uporabnik_id) REFERENCES uporabniki(id)
        )
    """)

    conn.commit()
    conn.close()
    logger.info("Baza inicializirana.")


# ---------------------------------------------------------------------------
# Operacije z naročili
# ---------------------------------------------------------------------------

def shrani_narocila(narocila: list) -> int:
    """
    Vstavi nova naročila v bazo. Duplikate (po pjn) preskoči.

    Args:
        narocila: Seznam slovarjev iz scraperja.

    Returns:
        Število dejansko novih vnosov.
    """
    if not narocila:
        return 0

    conn = _poveži()
    cur = conn.cursor()
    novo = 0

    for n in narocila:
        # Kategorije shranimo kot JSON string
        kategorije_json = json.dumps(n.get("kategorije", []), ensure_ascii=False)

        cur.execute("""
            INSERT OR IGNORE INTO narocila
                (pjn, narocnik, naziv, vrsta, datum_objave, rok_oddaje,
                 stanje, kategorije, datum_scrape)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            n.get("pjn"),
            n.get("narocnik"),
            n.get("naziv"),
            n.get("vrsta"),
            n.get("datum_objave"),
            n.get("rok_oddaje"),
            n.get("stanje"),
            kategorije_json,
            n.get("datum_scrape", datetime.now().isoformat()),
        ))

        if cur.rowcount > 0:
            novo += 1

    conn.commit()
    conn.close()
    logger.info(f"Shranjenih {novo} novih naročil od {len(narocila)} prejetih.")
    return novo


def poberi_nova_narocila(kategorije_filter: list) -> list:
    """
    Vrne naročila, ki še niso bila poslana in se ujemajo s filtrom kategorij.

    Args:
        kategorije_filter: Seznam kategorij ki nas zanimajo,
                           npr. ["IT & Software", "Gradbeništvo"].
                           Prazna lista vrne vsa nepozvana naročila.

    Returns:
        Seznam slovarjev z naročili.
    """
    conn = _poveži()
    cur = conn.cursor()
    cur.execute("SELECT * FROM narocila WHERE poslano = 0")
    vrstice = [dict(row) for row in cur.fetchall()]
    conn.close()

    if not kategorije_filter:
        return vrstice

    # Filtriraj po kategorijah — naročilo se ujema, če ima vsaj eno skupno kategorijo
    ujemanja = []
    filter_set = set(kategorije_filter)
    for n in vrstice:
        try:
            kat = json.loads(n.get("kategorije") or "[]")
        except json.JSONDecodeError:
            kat = []
        if filter_set & set(kat):
            ujemanja.append(n)

    return ujemanja


def oznaci_kot_poslano(pjn_lista: list):
    """
    Nastavi poslano = 1 za vse naročila v podanem seznamu PJN oznak.

    Args:
        pjn_lista: Seznam PJN oznak (npr. ["JN001/2024", "JN002/2024"]).
    """
    if not pjn_lista:
        return

    conn = _poveži()
    cur = conn.cursor()
    # Uporabi placeholderje za varno SQL parametrizacijo
    placeholders = ",".join("?" for _ in pjn_lista)
    cur.execute(
        f"UPDATE narocila SET poslano = 1 WHERE pjn IN ({placeholders})",
        pjn_lista
    )
    conn.commit()
    conn.close()
    logger.info(f"Označenih {len(pjn_lista)} naročil kot poslano.")


# ---------------------------------------------------------------------------
# Operacije z uporabniki
# ---------------------------------------------------------------------------

def dodaj_uporabnika(email: str, kategorije: list) -> bool:
    """
    Vstavi novega uporabnika z aktiven = 0.

    Args:
        email:      Email naslov novega uporabnika.
        kategorije: Seznam kategorij ki jih želi prejemati.

    Returns:
        True če uspešno dodan, False če email že obstaja.
    """
    conn = _poveži()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT OR IGNORE INTO uporabniki (email, kategorije, datum_registracije)
            VALUES (?, ?, ?)
        """, (
            email,
            json.dumps(kategorije, ensure_ascii=False),
            datetime.now().isoformat(),
        ))
        conn.commit()
        uspelo = cur.rowcount > 0
    except sqlite3.Error as e:
        logger.error(f"Napaka pri dodajanju uporabnika {email}: {e}")
        uspelo = False
    finally:
        conn.close()

    if uspelo:
        logger.info(f"Dodan nov uporabnik: {email}")
    else:
        logger.warning(f"Uporabnik že obstaja: {email}")
    return uspelo


def aktiviraj_uporabnika(email: str):
    """Nastavi aktiven = 1 za podanega uporabnika."""
    conn = _poveži()
    cur = conn.cursor()
    cur.execute("UPDATE uporabniki SET aktiven = 1 WHERE email = ?", (email,))
    conn.commit()
    conn.close()
    logger.info(f"Uporabnik aktiviran: {email}")


def deaktiviraj_uporabnika(email: str):
    """Nastavi aktiven = 0 za podanega uporabnika."""
    conn = _poveži()
    cur = conn.cursor()
    cur.execute("UPDATE uporabniki SET aktiven = 0 WHERE email = ?", (email,))
    conn.commit()
    conn.close()
    logger.info(f"Uporabnik deaktiviran: {email}")


def poberi_aktivne_uporabnike() -> list:
    """
    Vrne vse uporabnike z aktiven = 1.

    Returns:
        Seznam slovarjev. Polje 'kategorije' je že deserializirano v list.
    """
    conn = _poveži()
    cur = conn.cursor()
    cur.execute("SELECT * FROM uporabniki WHERE aktiven = 1")
    vrstice = [dict(row) for row in cur.fetchall()]
    conn.close()

    # Deserializiraj kategorije iz JSON stringa v Python list
    for u in vrstice:
        try:
            u["kategorije"] = json.loads(u.get("kategorije") or "[]")
        except json.JSONDecodeError:
            u["kategorije"] = []

    return vrstice


# ---------------------------------------------------------------------------
# Email logi
# ---------------------------------------------------------------------------

def shrani_email_log(uporabnik_id: int, stevilo: int):
    """
    Vstavi zapis o poslanem email alerta.

    Args:
        uporabnik_id: ID uporabnika iz tabele uporabniki.
        stevilo:      Število naročil v tem alerta.
    """
    conn = _poveži()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO email_logi (uporabnik_id, datum_poslanega, stevilo_narocil)
        VALUES (?, ?, ?)
    """, (uporabnik_id, datetime.now().isoformat(), stevilo))
    conn.commit()
    conn.close()
    logger.info(f"Email log shranjen za uporabnik_id={uporabnik_id}, naročil={stevilo}.")


# ---------------------------------------------------------------------------
# Test ob direktnem zagonu
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # 1. Inicializiraj bazo
    init_db()

    # 2. Dodaj testnega uporabnika
    dodan = dodaj_uporabnika("test@test.com", ["IT & Software", "Gradbeništvo"])
    print(f"Uporabnik dodan: {dodan}")

    # Poskusi dodati istega — mora vrniti False
    duplikat = dodaj_uporabnika("test@test.com", ["IT & Software"])
    print(f"Duplikat zavrnjen (pričakovano False): {duplikat}")

    # 3. Izpiši aktivne uporabnike (test@test.com ima aktiven=0, seznam mora biti prazen)
    aktivni = poberi_aktivne_uporabnike()
    print(f"Aktivnih uporabnikov (pred aktivacijo): {len(aktivni)}")

    # 4. Vstavi testna naročila
    testna_narocila = [
        {
            "pjn": "JN001/2024",
            "narocnik": "Ministrstvo za finance",
            "naziv": "Dobava računalniške opreme",
            "vrsta": "Blago",
            "datum_objave": "2024-01-10",
            "rok_oddaje": "2024-02-10",
            "stanje": "Objavljeno",
            "kategorije": ["IT & Software"],
        },
        {
            "pjn": "JN002/2024",
            "narocnik": "Mestna občina Ljubljana",
            "naziv": "Izgradnja kolesarske steze",
            "vrsta": "Gradnja",
            "datum_objave": "2024-01-12",
            "rok_oddaje": "2024-03-01",
            "stanje": "Objavljeno",
            "kategorije": ["Gradbeništvo"],
        },
        {
            "pjn": "JN001/2024",  # Duplikat — mora biti preskočen
            "narocnik": "Ministrstvo za finance",
            "naziv": "Dobava računalniške opreme",
            "vrsta": "Blago",
            "datum_objave": "2024-01-10",
            "rok_oddaje": "2024-02-10",
            "stanje": "Objavljeno",
            "kategorije": ["IT & Software"],
        },
    ]

    novo = shrani_narocila(testna_narocila)
    print(f"Novih naročil shranjenih (pričakovano 2): {novo}")

    # 5. Poberi naročila po filtru
    it_narocila = poberi_nova_narocila(["IT & Software"])
    print(f"Naročila za 'IT & Software' (pričakovano 1): {len(it_narocila)}")

    vsa = poberi_nova_narocila([])
    print(f"Vsa nepozvana naročila (pričakovano 2): {len(vsa)}")

    # 6. Označi kot poslano
    oznaci_kot_poslano(["JN001/2024"])
    po_oznacitvi = poberi_nova_narocila([])
    print(f"Nepozvana po oznacitvi (pričakovano 1): {len(po_oznacitvi)}")

    # 7. Izpiši skupno število naročil v bazi
    conn = sqlite3.connect(DB_PATH)
    skupaj = conn.execute("SELECT COUNT(*) FROM narocila").fetchone()[0]
    conn.close()
    print(f"Skupaj naročil v bazi: {skupaj}")

    print("\n✓ Vsi testi uspešno zaključeni.")
