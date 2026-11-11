"""LinkedIn public (logged-out) job search.

No account, no cookies: only the "jobs-guest" endpoints that LinkedIn serves to
visitors who are not signed in.

Search: /jobs-guest/jobs/api/seeMoreJobPostings/search
        ?keywords=..&geoId=..&f_TPR=r86400&f_JT=F&start=0   (25 cards per call)
  card: div.base-search-card[data-entity-urn="urn:li:jobPosting:<id>"]
        .base-search-card__title / __subtitle, .job-search-card__location,
        time[datetime]
Detail: /jobs-guest/jobs/api/jobPosting/<id>
  description: .show-more-less-html__markup ; criteria: .description__job-criteria-item
"""
import logging

from bs4 import BeautifulSoup

from .common import (
    SourceBlocked, clean_text, get_html, get_html_patient, html_to_text, make_offer, parse_iso_date,
    polite_sleep, title_is_excluded,
)

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
VIEW_URL = "https://www.linkedin.com/jobs/view/{id}"
PREFIX = "li_"
PAGE_SIZE = 10  # the guest search returns 10 cards per call


def parse_search_page(html):
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for card in soup.select(".base-search-card"):
        urn = card.get("data-entity-urn") or ""
        offer_id = urn.rsplit(":", 1)[-1] if urn else ""
        if not offer_id.isdigit():
            link = card.select_one("a.base-card__full-link")
            href = (link.get("href") if link else "") or ""
            tail = href.split("?")[0].rstrip("/").rsplit("-", 1)[-1]
            offer_id = tail if tail.isdigit() else ""
        if not offer_id:
            continue

        def txt(sel):
            el = card.select_one(sel)
            return el.get_text(" ", strip=True) if el else ""

        t = card.select_one("time")
        cards.append({
            "id": offer_id,
            "title": txt(".base-search-card__title"),
            "company": txt(".base-search-card__subtitle"),
            "location": txt(".job-search-card__location"),
            "posted": parse_iso_date(t.get("datetime")) if t else None,
        })
    return cards


def parse_detail_page(html):
    soup = BeautifulSoup(html, "html.parser")
    desc = soup.select_one(".show-more-less-html__markup") or soup.select_one(".description__text")
    description = html_to_text(desc) if desc else ""
    criteria = []
    for item in soup.select(".description__job-criteria-item"):
        h = item.select_one("h3")
        v = item.select_one("span")
        if h and v:
            criteria.append(f"{h.get_text(strip=True)} : {v.get_text(' ', strip=True)}")
    return description, criteria


def scrape(session, settings, stored, since, today=None):
    li = settings["linkedin"]
    excluded = settings.get("excluded_title_words", [])
    found = {}
    stop_search = False

    for keyword in settings["keywords"]:
        if stop_search:
            break
        for page in range(li.get("pages_per_keyword", 1)):
            params = {
                "keywords": keyword,
                "geoId": li["geo_id"],
                "f_TPR": li.get("posted_within", "r86400"),
                "start": page * PAGE_SIZE,
            }
            if li.get("job_types"):
                params["f_JT"] = li["job_types"]
            if li.get("experience_levels"):
                params["f_E"] = li["experience_levels"]

            try:
                html = get_html_patient(session, SEARCH_URL, params=params)
            except SourceBlocked as e:
                if not found:
                    raise
                log.warning(f"LinkedIn limiting searches ({e}): continuing with the {len(found)} offer(s) already listed.")
                stop_search = True
                break
            polite_sleep(3, 6)
            if not html:
                break

            cards = parse_search_page(html)
            log.info(f"LinkedIn '{keyword}' p{page + 1}: {len(cards)} cards")
            for c in cards:
                key = PREFIX + c["id"]
                if key in stored or key in found:
                    continue
                if c["posted"] and c["posted"] < since:
                    continue
                if title_is_excluded(c["title"], excluded):
                    continue
                found[key] = c

            if len(cards) < PAGE_SIZE:
                break

    # Detail pages are what LinkedIn rate-limits: fetch them slowly, cap them per run,
    # and on a lasting block keep what we already have. Offers not fetched are not
    # stored, so the next run picks them up again.
    max_details = li.get("max_details_per_run", 40)
    offers = {}
    for n, (key, c) in enumerate(found.items()):
        if n >= max_details:
            log.info(f"LinkedIn: {len(found) - n} more offer(s) left for the next run (max_details_per_run={max_details}).")
            break
        description, criteria = "", []
        try:
            html = get_html_patient(session, DETAIL_URL.format(id=c["id"]))
            polite_sleep(4, 8)
            if html:
                description, criteria = parse_detail_page(html)
        except SourceBlocked as e:
            log.warning(f"LinkedIn still limiting detail pages ({e}): keeping the {len(offers)} offer(s) "
                        f"already read, {len(found) - n} left for the next run.")
            break
        except Exception as e:
            log.warning(f"LinkedIn detail failed for {c['id']}: {e}")

        if criteria:
            description = (description + "\n\n" + "\n".join(criteria)).strip()

        contract = next(
            (x.split(":", 1)[1].strip() for x in criteria if "emploi" in x.lower() or "employment" in x.lower()),
            "",
        )
        offers[key] = make_offer(
            "LinkedIn", c["title"], c["company"], c["location"],
            VIEW_URL.format(id=c["id"]), c["posted"],
            contract=contract, description=description,
        )

    return offers
