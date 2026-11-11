from pathlib import Path
from datetime import datetime
import json

from .scraper import sort_offers_by_date

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STORE_PATH = DATA_DIR / "offers.json"


def load_offers(path=STORE_PATH):
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_offers(offers, path=STORE_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(offers, f, ensure_ascii=False, indent=2)


def new_offers(scraped, stored):
    return {
        offer_id: offer
        for offer_id, offer in scraped.items()
        if offer_id not in stored
    }


def delete_old(offers, since):
    # drop offers that are too old (> 14 days)
    kept = {
        offer_id: offer
        for offer_id, offer in offers.items()
        if datetime.fromisoformat(offer["startBroadcastDate"]).date() >= since
    }
    return sort_offers_by_date(kept)