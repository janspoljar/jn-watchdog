"""
main.py — Glavni orchestrator za jn-watchdog.
Dnevni job: scraping -> filtriranje po uporabnikih -> pošiljanje emailov.

Zagon:
    python main.py            # inicializira bazo + scheduler (vsak dan ob 06:00)
    python main.py --test     # požene dnevni job takoj enkrat
    python main.py --server   # zažene samo Flask API strežnik
    python main.py --test --dry-run   # job brez pošiljanja: emaili v datoteko
"""

import sys
import time
import logging

import schedule

import db
import emailer
import sources

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def dnevni_job():
    """
    Dnevni job:
    1. Inicializira bazo
    2. Požene scraper in shrani nova naročila
    3. Za vsakega aktivnega uporabnika pošlje email z relevantnimi naročili
    4. Označi poslana naročila in shrani loge
    5. Izpiše summary
    """
    logger.info("=== Začetek dnevnega joba ===")

    napake = []
    scraped = 0
    novih = 0

    # 1. Baza
    db.init_db()

    # 2. Viri podatkov — vsak z retry logiko (30s, 2min, 10min);
    #    ob popolnem failu vira alert adminu, job pa nadaljuje z že
    #    shranjenimi (neposlanimi) naročili.
    for source in sources.SOURCES:
        try:
            narocila_vira = sources.fetch_z_retryjem(source)
            scraped += len(narocila_vira)
            novih += db.shrani_narocila(narocila_vira)
        except sources.SourceError as e:
            logger.error(str(e))
            napake.append(str(e))
            emailer.pošlji_alert_adminu(f"Vir {source.name} ni dosegljiv", str(e))

    logger.info(f"Viri končani: pobranih {scraped}, novih v bazi {novih}")

    # 3. Aktivni uporabniki
    uporabniki = db.poberi_aktivne_uporabnike()
    logger.info(f"Aktivnih uporabnikov: {len(uporabniki)}")

    poslanih_emailov = 0
    preskocenih = 0
    poslanih_narocil = set()

    # 4. Za vsakega uporabnika: relevantna neposlana naročila -> email -> log
    for uporabnik in uporabniki:
        # Idempotentnost: dvojni zagon joba ne sme poslati dvojnih emailov
        if db.je_email_poslan_danes(uporabnik["id"]):
            logger.info(f"Email za {uporabnik['email']} danes že poslan — preskočim.")
            preskocenih += 1
            continue

        narocila = db.poberi_nova_narocila(uporabnik["kategorije"])
        if not narocila:
            logger.info(f"Ni novih naročil za {uporabnik['email']}.")
            continue

        if emailer.pošlji_email(uporabnik["email"], narocila):
            poslanih_emailov += 1
            db.shrani_email_log(uporabnik["id"], len(narocila))
            # Zberi PJN oznake za kasnejšo označitev
            for n in narocila:
                poslanih_narocil.add(n["pjn"])
        else:
            logger.error(f"Email za {uporabnik['email']} ni bil poslan.")
            napake.append(f"Email za {uporabnik['email']} ni bil poslan.")

    # Označi kot poslano šele po vseh uporabnikih,
    # da isto naročilo dobijo vsi relevantni uporabniki
    if poslanih_narocil:
        db.oznaci_kot_poslano(list(poslanih_narocil))

    # 5. Summary v log + dnevni povzetek adminu na email
    logger.info("=== Summary dnevnega joba ===")
    logger.info(f"Uporabnikov:        {len(uporabniki)}")
    logger.info(f"Poslanih emailov:   {poslanih_emailov}")
    logger.info(f"Preskočenih:        {preskocenih}")
    logger.info(f"Naročil v emailih:  {len(poslanih_narocil)}")
    logger.info(f"Pobranih z virov:   {scraped} (novih: {novih})")
    logger.info(f"Napak:              {len(napake)}")

    emailer.pošlji_dnevni_povzetek({
        "scraped": scraped,
        "novih": novih,
        "poslanih_emailov": poslanih_emailov,
        "preskocenih": preskocenih,
        "napake": napake,
    })


def zazeni_scheduler():
    """Inicializira bazo in zažene scheduler — dnevni job vsak dan ob 06:00."""
    db.init_db()
    schedule.every().day.at("06:00").do(dnevni_job)
    logger.info("Scheduler zagnan — dnevni job ob 06:00. Čakam...")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    # Dry-run: emaili gredo v datoteko (emailer.DRY_RUN_FILE) namesto na Resend
    if "--dry-run" in sys.argv:
        emailer.DRY_RUN = True
        logger.info(f"DRY-RUN mode: emaili se zapisujejo v {emailer.DRY_RUN_FILE}")

    if "--test" in sys.argv:
        # Testni zagon — požene job takoj enkrat
        dnevni_job()
    elif "--server" in sys.argv:
        # Samo Flask API strežnik
        import config
        from server import app
        db.init_db()
        app.run(host="0.0.0.0", port=config.PORT)
    else:
        # Privzeto: scheduler v neskončni zanki
        zazeni_scheduler()
