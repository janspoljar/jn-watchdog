"""
db.py — Upravljanje SQLite baze podatkov za jn-watchdog
Vse operacije z naročili, uporabniki in email logi.
"""

import sqlite3
import json
import logging
from datetime import datetime, timedelta
from config import DB_PATH

logger = logging.getLogger(__name__)


def _poveži():
    """
    Vrne novo SQLite povezavo z row_factory.

    Enoten connection pattern (Faza 2):
    - WAL mode: bralci ne blokirajo pisca — app (gunicorn) in scheduler
      delita isto bazo na docker volume.
    - busy_timeout 10s: ob sočasnem pisanju povezava počaka, namesto
      da takoj vrže "database is locked".
    - synchronous=NORMAL: varno v kombinaciji z WAL, hitrejše od FULL.
    Vse funkcije v tem modulu MORAJO povezavo dobiti izključno tukaj.
    """
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
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

    # Tabela leadov (Faza 4) — vpisi iz brezplačnega pregleda (lead magnet).
    # Lead še ni naročnik; hranimo email + profil dejavnosti za nadaljnji kontakt.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            email     TEXT    NOT NULL,
            panoga    TEXT,
            opis      TEXT,
            izbrani   TEXT,
            vir       TEXT,
            datum     TEXT
        )
    """)

    conn.commit()

    # Migracije obstoječih tabel (idempotentno) — dodaj manjkajoče stolpce.
    _migriraj_uporabnike(conn)

    conn.commit()
    conn.close()
    logger.info("Baza inicializirana.")


def _migriraj_uporabnike(conn):
    """
    Idempotentno doda stolpce na tabelo uporabniki, ki so prišli v Fazi 4:
    panoga, opis (profil dejavnosti), paket, double opt-in (potrditveni_token,
    potrjen). Varno za večkratni klic — preskoči obstoječe stolpce.
    """
    obstojeci = {vrstica[1] for vrstica in conn.execute("PRAGMA table_info(uporabniki)")}
    novi_stolpci = {
        "panoga": "TEXT",
        "opis": "TEXT",
        "paket": "TEXT",
        "potrditveni_token": "TEXT",
        "potrjen": "INTEGER NOT NULL DEFAULT 0",
    }
    for ime, tip in novi_stolpci.items():
        if ime not in obstojeci:
            conn.execute(f"ALTER TABLE uporabniki ADD COLUMN {ime} {tip}")
            logger.info(f"Migracija: dodan stolpec uporabniki.{ime}")


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


def poberi_narocila_zadnjih_dni(dni: int = 30) -> list:
    """
    Vrne naročila, scrapana v zadnjih `dni` dneh (po datum_scrape, ISO format).
    Uporablja se za brezplačni pregled (lead magnet) — "zamujena naročila".

    Returns:
        Seznam slovarjev z naročili, najnovejša najprej.
    """
    meja = (datetime.now() - timedelta(days=dni)).isoformat()
    conn = _poveži()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM narocila WHERE datum_scrape >= ? ORDER BY datum_scrape DESC",
        (meja,),
    )
    vrstice = [dict(row) for row in cur.fetchall()]
    conn.close()
    return vrstice


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


def nastavi_stripe_customer(email: str, customer_id: str):
    """Shrani Stripe customer ID za podanega uporabnika."""
    conn = _poveži()
    cur = conn.cursor()
    cur.execute(
        "UPDATE uporabniki SET stripe_customer_id = ? WHERE email = ?",
        (customer_id, email)
    )
    conn.commit()
    conn.close()
    logger.info(f"Stripe customer ID nastavljen za: {email}")


# ---------------------------------------------------------------------------
# Email logi
# ---------------------------------------------------------------------------

def je_email_poslan_danes(uporabnik_id: int, datum: str | None = None) -> bool:
    """
    Preveri, ali je bil uporabniku na podani datum email že poslan.
    Idempotentnost dnevnega joba: dvojni zagon ne sme poslati dvojnih emailov.

    Args:
        uporabnik_id: ID uporabnika.
        datum:        Datum v formatu YYYY-MM-DD; privzeto današnji dan.

    Returns:
        True če log za (uporabnik, datum) že obstaja.
    """
    if datum is None:
        datum = datetime.now().strftime("%Y-%m-%d")

    conn = _poveži()
    cur = conn.cursor()
    # datum_poslanega je ISO timestamp — date() iz njega izlušči YYYY-MM-DD
    cur.execute(
        "SELECT 1 FROM email_logi WHERE uporabnik_id = ? AND date(datum_poslanega) = ? LIMIT 1",
        (uporabnik_id, datum),
    )
    obstaja = cur.fetchone() is not None
    conn.close()
    return obstaja


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
# Leadi (Faza 4) — brezplačni pregled
# ---------------------------------------------------------------------------

def shrani_lead(email: str, panoga: str, opis: str, izbrani: list, vir: str = "pregled") -> int:
    """
    Shrani lead iz brezplačnega pregleda. Vrne ID vstavljenega leada.

    Args:
        email:   email naslov leada.
        panoga:  ključ izbrane panoge (npr. "gradbenistvo").
        opis:    prosto besedilo dejavnosti.
        izbrani: seznam izbranih podpodročij (labelov).
        vir:     izvor leada (privzeto "pregled").
    """
    conn = _poveži()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO leads (email, panoga, opis, izbrani, vir, datum)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        email,
        panoga,
        opis,
        json.dumps(izbrani, ensure_ascii=False),
        vir,
        datetime.now().isoformat(),
    ))
    conn.commit()
    lead_id = cur.lastrowid
    conn.close()
    logger.info(f"Shranjen lead: {email} (panoga={panoga}).")
    return lead_id


# ---------------------------------------------------------------------------
# Registracija z double opt-in (Faza 4)
# ---------------------------------------------------------------------------

def registriraj_uporabnika(
    email: str, panoga: str, opis: str, paket: str,
    kategorije: list, token: str,
) -> bool:
    """
    Vstavi/posodobi uporabnika za beta registracijo z double opt-in.
    Uporabnik je aktiven=0 in potrjen=0, dokler ne klikne potrditvenega linka.

    Če email že obstaja, posodobi profil in token (npr. ponovna prijava
    pred potrditvijo). Vrne True ob uspehu.
    """
    conn = _poveži()
    cur = conn.cursor()
    kategorije_json = json.dumps(kategorije, ensure_ascii=False)
    try:
        cur.execute("SELECT id FROM uporabniki WHERE email = ?", (email,))
        obstojec = cur.fetchone()
        if obstojec:
            cur.execute("""
                UPDATE uporabniki
                SET panoga = ?, opis = ?, paket = ?, kategorije = ?,
                    potrditveni_token = ?, potrjen = 0
                WHERE email = ?
            """, (panoga, opis, paket, kategorije_json, token, email))
        else:
            cur.execute("""
                INSERT INTO uporabniki
                    (email, kategorije, aktiven, datum_registracije,
                     panoga, opis, paket, potrditveni_token, potrjen)
                VALUES (?, ?, 0, ?, ?, ?, ?, ?, 0)
            """, (
                email, kategorije_json, datetime.now().isoformat(),
                panoga, opis, paket, token,
            ))
        conn.commit()
        uspelo = True
    except sqlite3.Error as e:
        logger.error(f"Napaka pri registraciji {email}: {e}")
        uspelo = False
    finally:
        conn.close()
    if uspelo:
        logger.info(f"Registracija (čaka potrditev): {email}")
    return uspelo


def potrdi_uporabnika(token: str) -> str | None:
    """
    Potrdi email prek opt-in tokena: nastavi potrjen=1 in aktiven=1
    (beta — brez plačila se uporabnik aktivira ob potrditvi).

    Returns:
        Email potrjenega uporabnika ob uspehu, sicer None (neveljaven token).
    """
    if not token:
        return None
    conn = _poveži()
    cur = conn.cursor()
    cur.execute("SELECT email FROM uporabniki WHERE potrditveni_token = ?", (token,))
    vrstica = cur.fetchone()
    if not vrstica:
        conn.close()
        logger.warning("Potrditev z neveljavnim tokenom.")
        return None
    email = vrstica[0]
    cur.execute("""
        UPDATE uporabniki
        SET potrjen = 1, aktiven = 1, potrditveni_token = NULL
        WHERE potrditveni_token = ?
    """, (token,))
    conn.commit()
    conn.close()
    logger.info(f"Email potrjen, uporabnik aktiviran (beta): {email}")
    return email


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
