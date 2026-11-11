from .config import load_config
from .scraper import scrape_offers, cutoff_date
from .relevance import filter_relevant
from .telegram import enabled as telegram_enabled, send_offers
from .store import load_offers, save_offers, new_offers, delete_old
from .gemini_handler import GeminiHandler
from .metrics import append_run, count_unchecked, ErrorCounter

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import logging
import sys
import os

log = logging.getLogger(__name__)


START_HOUR = 8  
END_HOUR = 20
error_counter = ErrorCounter()


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger().addHandler(error_counter)


def within_active_window():
    now = datetime.now(ZoneInfo("Europe/Paris"))
    is_weekday = now.weekday() < 5             
    is_active_hour = START_HOUR <= now.hour <= END_HOUR
    return is_weekday and is_active_hour


def run():

    time_start = time.time()

    # ------------------------- Initialization
    force_run = os.environ.get("FORCE_RUN") == "1"
    setup_logging()
    log.info("Initializing...")

    initialization_time_start = time.time()

    if not force_run and not within_active_window():
        log.info("Outside active window (Paris time), skipping run.")
        return
    
    config_dict = load_config()
    since = cutoff_date(config_dict["MAX_DAYS"])
    stored = load_offers()
    initialization_total_time = round(time.time() - initialization_time_start, 1)

    # ------------------------- Scraping 
    log.info("Beginning scrapping...")

    scraping_time_start = time.time()

    scraped = scrape_offers(
        config_dict, since=since, stored=stored, batch=config_dict["BATCH_SIZE"]
    )
    log.info("--- done scrapping")
    fresh = new_offers(scraped, stored)
    log.info(f"--- {len(fresh)} new offers ({len(stored)} already known).")
    merged = {**stored, **fresh}
    scraping_total_time = round(time.time() - scraping_time_start, 1)

    # ------------------------- Relevance
    log.info("Beginning relevancy check...")

    relevance_time_start = time.time()

    handler = GeminiHandler(config_dict["GEMINI_API_KEY"], config_dict["GEMINI_MODELS"])
    relevant = filter_relevant(merged, config_dict, handler, save_func=save_offers)
    log.info(f"--- {len(relevant)} newly relevant offer(s) to notify.")
    relevance_total_time = round(time.time() - relevance_time_start, 1)

    # ------------------------- Telegram part
    if relevant and telegram_enabled():
        log.info("Beginning sending offers Telegram...")
        send_offers(relevant, config_dict)
    elif relevant:
        log.info("Telegram alerts are off: relevant offers are shown in the app (Windows notification on the PC).")
    else:
        log.info("No relevant offers this run.")

    merged = delete_old(merged, since=since)
    save_offers(merged)

    total_runtime = round(time.time() - time_start, 1)
    append_run(
        scraped=len(scraped),
        new=len(fresh),
        relevant=len(relevant),
        stored=len(merged),
        unchecked=count_unchecked(merged),
        errors=error_counter.count,
        initialization_time = initialization_total_time,
        scraping_total_time = scraping_total_time,
        relevance_total_time = relevance_total_time,
        runtime = total_runtime
    )
  
    log.info(f"Run complete: {len(fresh)} new, {len(relevant)} relevant, {len(merged)} stored.")


if __name__ == "__main__":
    run()