"""
main.py — Glavna vstopna točka za jn-watchdog
Zažene scraping in pošiljanje alertov po urniku.
"""

import schedule
import time
import logging
from scraper import pridobi_narocila
from db import inicializiraj_bazo, shrani_narocilo, pridobi_nepozvana_narocila, \
    oznaci_kot_poslano, pridobi_aktivne_narocnike
from emailer import posli_vsem_narocnikom

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def scraping_opravilo():
    """Pridobi nova naročila in jih shrani v bazo."""
    logger.info("Začenjam scraping...")
    narocila = pridobi_narocila(max_strani=5)
    nova = 0
    for n in narocila:
        if shrani_narocilo(n):
            nova += 1
    logger.info(f"Scraping končan. Shranjenih {nova} novih naročil.")


def alert_opravilo():
    """Pošlje tedenske alerte vsem aktivnim naročnikom."""
    logger.info("Pripravljam tedenske alerte...")
    narocila = pridobi_nepozvana_narocila()
    narocniki = pridobi_aktivne_narocnike()

    if not narocniki:
        logger.info("Ni aktivnih naročnikov.")
        return

    if not narocila:
        logger.info("Ni novih naročil za pošiljanje.")
        return

    posli_vsem_narocnikom(narocniki, narocila)

    # Označi kot poslano
    for n in narocila:
        oznaci_kot_poslano(n["id"])

    logger.info(f"Alerti poslani za {len(narocila)} naročil.")


if __name__ == "__main__":
    # Inicializiraj bazo ob zagonu
    inicializiraj_bazo()

    # Urnik: scraping vsak dan ob 06:00, alerti vsak ponedeljek ob 08:00
    schedule.every().day.at("06:00").do(scraping_opravilo)
    schedule.every().monday.at("08:00").do(alert_opravilo)

    logger.info("jn-watchdog zagnan. Čakam na urnik...")

    # Takoj poženi prvi scraping
    scraping_opravilo()

    while True:
        schedule.run_pending()
        time.sleep(60)
