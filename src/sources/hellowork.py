"""HelloWork (hellowork.com) public search pages.

Search page: /fr-fr/emploi/recherche.html?k=<keywords>&l=<location>&c=CDI&p=<page>
  - 30 cards per page, each <li data-id-storage-item-id="<id>"> with
    input[name=title], input[name=company], [data-cy=localisationCard],
    [data-cy=contractCard] and a relative date ("il y a 5 jours").
Offer page: /fr-fr/emplois/<id>.html carries a schema.org JobPosting JSON-LD
  block (title, description, datePosted, hiringOrganization, jobLocation...).
"""
import json
import logging

from bs4 import BeautifulSoup

from .common import (
    SourceBlocked, clean_text, get_html, get_html_patient, html_to_text, make_offer, parse_iso_date,
    parse_relative_date, polite_sleep, title_is_excluded,
)

log = logging.getLogger(__name__)

BASE = "https://www.hellowork.com"
SEARCH_URL = BASE + "/fr-fr/emploi/recherche.html"
OFFER_URL = BASE + "/fr-fr/emplois/{id}.html"
PREFIX = "hw_"


def parse_search_page(html, today=None):
    """Return a list of card dicts from a search results page."""
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for li in soup.select("li[data-id-storage-item-id]"):
        offer_id = li.get("data-id-storage-item-id")
        if not offer_id:
            continue

        title_input = li.select_one("input[name=title]")
        company_input = li.select_one("input[name=company]")
        title = title_input.get("value") if title_input else ""
        company = company_input.get("value") if company_input else ""
        if not title:
            t = li.select_one("[data-cy=offerTitle] h3, [data-cy=offerTitle]")
            title = t.get_text(" ", strip=True) if t else ""

        loc = li.select_one("[data-cy=localisationCard]")
        contract = li.select_one("[data-cy=contractCard]")

        cards.append({
            "id": offer_id,
            "title": title,
            "company": company,
            "location": loc.get_text(" ", strip=True) if loc else "",
            "contract": contract.get_text(" ", strip=True) if contract else "",
            "posted": parse_relative_date(li.get_text(" ", strip=True), today=today),
        })
    return cards


def parse_offer_page(html):
    """Return (description_text, posted_date, extra) from an offer page's JSON-LD."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if "JobPosting" not in (raw or ""):
            continue
        try:
            data = json.loads(raw, strict=False)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            data = next((d for d in data if d.get("@type") == "JobPosting"), {})
        if data.get("@type") != "JobPosting":
            continue

        desc_html = data.get("description") or ""
        description = html_to_text(desc_html)
        extra = {
            "experience": clean_text(str(data.get("experienceRequirements") or "")),
            "education": clean_text(str(data.get("educationRequirements") or "")),
        }
        return description, parse_iso_date(data.get("datePosted")), extra

    # Fallback: page text if no JSON-LD
    main = soup.select_one("main") or soup
    return html_to_text(main)[:8000], None, {}


def scrape(session, settings, stored, since, today=None):
    """Scrape new HelloWork offers. `stored` = ids already known (any source)."""
    hw = settings["hellowork"]
    excluded = settings.get("excluded_title_words", [])
    found = {}

    for keyword in settings["keywords"]:
        for page in range(1, hw.get("pages_per_keyword", 1) + 1):
            params = {"k": keyword, "l": hw["location"], "p": page}
            if hw.get("contracts"):
                params["c"] = hw["contracts"]

            html = get_html(session, SEARCH_URL, params=params)
            polite_sleep()
            if not html:
                break

            cards = parse_search_page(html, today=today)
            log.info(f"HelloWork '{keyword}' p{page}: {len(cards)} cards")
            if not cards:
                break

            for c in cards:
                key = PREFIX + c["id"]
                if key in stored or key in found:
                    continue
                if c["posted"] and c["posted"] < since:
                    continue
                if title_is_excluded(c["title"], excluded):
                    continue
                found[key] = c

    offers = {}
    for n, (key, c) in enumerate(found.items()):
        url = OFFER_URL.format(id=c["id"])
        description, posted, extra = "", c["posted"], {}
        try:
            html = get_html_patient(session, url)
            polite_sleep(1, 2.5)
            if html:
                description, json_date, extra = parse_offer_page(html)
                posted = json_date or posted
        except SourceBlocked as e:
            log.warning(f"HelloWork limiting offer pages ({e}): keeping the {len(offers)} offer(s) already read, "
                        f"{len(found) - n} left for the next run.")
            break
        except Exception as e:
            log.warning(f"HelloWork detail failed for {url}: {e}")

        if posted and posted < since:
            continue

        offer = make_offer(
            "HelloWork", c["title"], c["company"], c["location"], url, posted,
            contract=c["contract"], description=description,
        )
        if extra.get("experience"):
            offer["description"] += f"\n\nExpérience demandée : {extra['experience']}"
        offers[key] = offer

    return offers
