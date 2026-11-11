import requests
import logging
import time

import os

from .lang import VIE_CV, guess_lang


def enabled():
    """Telegram alerts are off unless TELEGRAM_ENABLED=true (replaced by Windows notifications)."""
    return os.environ.get("TELEGRAM_ENABLED", "false").strip().lower() in ("1", "true", "yes", "oui")

log = logging.getLogger(__name__)

TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_DELAY = 5
TELEGRAM_MAX_RETRIES = 5
OFFER_BASE_URL = "https://mon-vie-via.businessfrance.fr/offres/{offer_id}"



def escape_html(text):
    if text is None:
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("", "•").replace("\u2022", "•")


def format_offer(offer_id, offer):
    title = escape_html(offer.get("missionTitle"))
    org = escape_html(offer.get("organizationName"))
    city = escape_html(offer.get("cityName"))
    country = escape_html(offer.get("countryName"))
    date = escape_html(offer.get("startBroadcastDate"))
    url = OFFER_BASE_URL.format(offer_id=offer_id)

    location = ", ".join(p for p in [city, country] if p)

    lang = guess_lang((offer.get("missionTitle") or "") + " " + (offer.get("missionDescription") or "")
                      + " " + (offer.get("missionProfile") or ""))

    lines = [
        "<b>" + title + "</b>",
        org,
        location,
        "Published: " + date,
        "📄 " + VIE_CV[lang],
        url,
    ]
    return "\n".join(line for line in lines if line)


def send_message(text, config_dict):
    url = TELEGRAM_URL.format(token=config_dict["TELEGRAM_BOT_TOKEN"])

    r = requests.post(
        url,
        json={
            "chat_id": config_dict["TELEGRAM_CHAT_ID"],
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    r.raise_for_status()


def send_offer(offer_id, offer, config_dict):
    send_message(format_offer(offer_id, offer), config_dict)


def send_offers(offers, config_dict):
    for offer_id, offer in offers.items():
        for attempt in range(TELEGRAM_MAX_RETRIES):
            try:
                send_offer(offer_id, offer, config_dict)
                break
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    log.warning(
                        f"TELEGRAM WARNING - Telegram rate limit hit, waiting {TELEGRAM_DELAY}s (retry {attempt + 1}/{TELEGRAM_MAX_RETRIES})...",
                    )
                    time.sleep(TELEGRAM_DELAY)
                    continue
                else:
                    log.warning(
                        f"TELEGRAM WARNING - Telegram error {e.response.status_code}",
                    )
                    time.sleep(TELEGRAM_DELAY)
                    continue
            except requests.exceptions.RequestException as e:
                log.error(f"TELEGRAM ERROR - failed to send offer {offer_id}: {e}")
                time.sleep(TELEGRAM_DELAY)
                continue
            except Exception as e:
                log.exception(f"TELEGRAM ERROR - non API related error {offer_id}")
                time.sleep(TELEGRAM_DELAY)
                continue

        time.sleep(1)