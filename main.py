"""
main.py — Orchestrator za javna-narocila.si (Faza 3).

Urnik (časovna cona iz config.TIMEZONE / TZ, privzeto Europe/Ljubljana):
- vsako uro:      scrape novih naročil -> AI matching -> pošlji Business (real-time)
- vsak dan 07:00: pošlji Pro + dnevni povzetek adminu
- ponedeljek 07:00: pošlji Osnovni (tedensko)

Zagon:
    python main.py                 # scheduler
    python main.py --test          # enkrat: scrape + match + pošlji Business
    python main.py --match         # enkrat: samo AI matching nad zadnjimi 30 dnevi
    python main.py --send pro       # enkrat: pošlji izbranemu paketu (osnovni/pro/business)
    python main.py --server         # samo Flask API
    python main.py --dry-run ...    # emaili v datoteko namesto na Resend
"""

import sys
import time
import logging

import schedule

import config
import db
import emailer
import sources
import matching

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Gradniki
# ---------------------------------------------------------------------------

def scrape_nova() -> tuple:
    """
    Scrapa vse vire z retry logiko in shrani nova naročila.
    Returns: (pobranih, novih, napake[list]).
    """
    db.init_db()
    napake, pobranih, novih = [], 0, 0
    for source in sources.SOURCES:
        try:
            narocila = sources.fetch_z_retryjem(source)
            pobranih += len(narocila)
            novih += db.shrani_narocila(narocila)
        except sources.SourceError as e:
            logger.error(str(e))
            napake.append(str(e))
            emailer.pošlji_alert_adminu(f"Vir {source.name} ni dosegljiv", str(e))
    logger.info(f"Scrape: pobranih {pobranih}, novih {novih}, napak {len(napake)}.")
    return pobranih, novih, napake


def pozeni_matching() -> dict:
    """AI matching nad naročili zadnjih 30 dni (cache prepreči podvajanje)."""
    narocila = db.poberi_narocila_zadnjih_dni(30)
    return matching.pozeni_matching(narocila)


def poslji_paketu(paket: str) -> int:
    """
    Vsakemu aktivnemu uporabniku paketa pošlje ujemajoča naročila, ki mu še
    niso bila poslana (confidence >= prag morda). Vrne število poslanih emailov.
    """
    poslanih = 0
    for u in db.poberi_uporabnike_po_paketu(paket):
        matchi = db.poberi_matche_za_uporabnika(u["id"], config.MATCH_PRAG_MORDA)
        if not matchi:
            continue
        if emailer.pošlji_ai_email(u["email"], matchi):
            db.oznaci_poslano_userju(u["id"], [m["pjn"] for m in matchi])
            db.shrani_email_log(u["id"], len(matchi))
            poslanih += 1
        else:
            logger.error(f"Email za {u['email']} ni bil poslan.")
    logger.info(f"Paket {paket}: poslanih {poslanih} emailov.")
    return poslanih


# ---------------------------------------------------------------------------
# Zagnani joby (po urniku)
# ---------------------------------------------------------------------------

def urni_job():
    """Vsako uro: scrape -> match -> pošlji Business (real-time)."""
    logger.info("=== Urni job ===")
    try:
        scrape_nova()
        pozeni_matching()
        poslji_paketu("business")
    except Exception as e:
        logger.exception("Urni job je padel.")
        emailer.pošlji_alert_adminu("Urni job napaka", str(e))


def dnevni_job():
    """Vsak dan 07:00: pošlji Pro + dnevni povzetek adminu."""
    logger.info("=== Dnevni job (Pro) ===")
    try:
        poslanih = poslji_paketu("pro")
        emailer.pošlji_admin_heartbeat(db.statistika(), poslanih)
    except Exception as e:
        logger.exception("Dnevni job je padel.")
        emailer.pošlji_alert_adminu("Dnevni job napaka", str(e))


def tedenski_job():
    """Ponedeljek 07:00: pošlji Osnovni (tedensko)."""
    logger.info("=== Tedenski job (Osnovni) ===")
    try:
        poslji_paketu("osnovni")
    except Exception as e:
        logger.exception("Tedenski job je padel.")
        emailer.pošlji_alert_adminu("Tedenski job napaka", str(e))


def zazeni_scheduler():
    """Inicializira bazo in zažene scheduler s frekvencami po paketu."""
    db.init_db()
    schedule.every().hour.at(":05").do(urni_job)
    schedule.every().day.at("07:00").do(dnevni_job)
    schedule.every().monday.at("07:00").do(tedenski_job)
    logger.info(
        "Scheduler zagnan (TZ=%s): urni scrape+match+Business, dnevni 07:00 Pro, "
        "ponedeljek 07:00 Osnovni. Čakam...", config.TIMEZONE
    )
    while True:
        schedule.run_pending()
        time.sleep(30)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        emailer.DRY_RUN = True
        logger.info(f"DRY-RUN: emaili se zapisujejo v {emailer.DRY_RUN_FILE}")

    if "--test" in sys.argv:
        urni_job()
    elif "--match" in sys.argv:
        db.init_db()
        print(pozeni_matching())
    elif "--send" in sys.argv:
        paket = sys.argv[sys.argv.index("--send") + 1]
        db.init_db()
        print(f"Poslanih: {poslji_paketu(paket)}")
    elif "--server" in sys.argv:
        from server import app
        db.init_db()
        app.run(host="0.0.0.0", port=config.PORT)
    else:
        zazeni_scheduler()
