"""CRIT (crit-job.com) — intérim, CDD et CDI.

Search (public page, filled on the server):
  /offres/?motsClefs=<mots>&typeContrat=CDI&typeContrat=CDD&typeContrat=Intérim&page=<n>
  20 cards per page: <a href="/offres/<uuid>"><h3>title</h3> ... <p>Contrat</p><p>Intérim</p> ...
  <span class="icon-pin-fill"/><p>Neuilly-sur-Seine (92200)</p></a>
Dates: the public sitemap of offers (robots.txt: Sitemap: https://www.crit-job.com/offres/sitemap.xml)
  gives each offer's <lastmod>, so old offers are skipped without opening them.
Offer page: schema.org JobPosting JSON-LD (title, description, qualifications, datePosted,
  jobLocation, baseSalary, experienceRequirements) + « Contrat » / « Durée du contrat » in the page.
"""
import json
import logging
import re

from bs4 import BeautifulSoup

from .. import contrats
from .common import (
    SourceBlocked, clean_text, get_html, get_html_patient, make_offer, parse_iso_date, polite_sleep,
    title_is_excluded,
)

log = logging.getLogger(__name__)

BASE = "https://www.crit-job.com"
SEARCH_URL = BASE + "/offres/"
SITEMAP_URL = BASE + "/offres/sitemap.xml"
OFFER_URL = BASE + "/offres/{id}"
PREFIX = "crit_"
COMPANY = "CRIT"
PAGE_SIZE = 20

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_HREF_RE = re.compile(r"/offres/(" + _UUID + r")/?$")
_SITEMAP_RE = re.compile(r"<loc>\s*[^<]*/offres/(" + _UUID + r")\s*</loc>\s*<lastmod>\s*([^<\s]+)\s*</lastmod>")
_POSTCODE_RE = re.compile(r"\((\d{5})\)")

# cdi_search.yaml `contrats` -> CRIT's typeContrat values (CDII = CDI intérimaire)
TYPES = {contrats.CDI: ["CDI", "CDII"], contrats.CDD: ["CDD"], contrats.INTERIM: ["Intérim"]}
CONTRACT_KEYS = {"cdi": contrats.CDI, "cdii": contrats.CDI, "cdd": contrats.CDD, "intérim": contrats.INTERIM,
                 "interim": contrats.INTERIM}


def type_params(settings):
    """typeContrat values for the search ([] = all contracts). Older yaml without `contrats`: CDI."""
    if "contrats" not in settings:
        return list(TYPES[contrats.CDI])
    wanted = contrats.value(settings)
    if wanted is None:
        return []
    return [t for k in wanted for t in TYPES[k]]


def contract_key(label):
    """« Intérim - Temps plein » -> interim."""
    first = clean_text(label).split(" - ")[0].strip().lower()
    return CONTRACT_KEYS.get(first, "")


def parse_sitemap(xml):
    """{uuid: lastmod date} from the offers sitemap."""
    return {m.group(1): parse_iso_date(m.group(2)) for m in _SITEMAP_RE.finditer(xml or "")}


def _labelled_values(node):
    """{label: value} for the « Contrat / Intérim », « Durée du contrat / 18 mois » pairs of <p>."""
    out = {}
    for p in node.find_all("p"):
        nxt = p.find_next("p")
        label = p.get_text(" ", strip=True)
        if nxt is not None and label and label not in out and len(label) < 40:
            out[label] = nxt.get_text(" ", strip=True)
    return out


def parse_search_page(html):
    """Cards of a search page: [{id, title, contract, location}]."""
    soup = BeautifulSoup(html, "html.parser")
    cards, seen = [], set()
    for a in soup.select('a[href*="/offres/"]'):
        m = _HREF_RE.search(a.get("href", ""))
        if not m or m.group(1) in seen:
            continue
        h3 = a.find("h3")
        if not h3:
            continue
        seen.add(m.group(1))
        values = _labelled_values(a)
        pin = a.select_one('[class*="icon-pin"]')
        loc = pin.find_next("p") if pin else None
        cards.append({
            "id": m.group(1),
            "title": h3.get_text(" ", strip=True),
            "contract": values.get("Contrat", ""),
            "location": loc.get_text(" ", strip=True) if loc else "",
        })
    return cards


def _job_posting(soup):
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if "JobPosting" not in (raw or ""):
            continue
        try:
            d = json.loads(raw, strict=False)
        except json.JSONDecodeError:
            continue
        if isinstance(d, list):
            d = next((x for x in d if isinstance(x, dict) and x.get("@type") == "JobPosting"), {})
        if isinstance(d, dict) and d.get("@type") == "JobPosting":
            return d
    return {}


def _salary(data):
    value = ((data.get("baseSalary") or {}).get("value") or {})
    lo, hi = value.get("minValue"), value.get("maxValue")
    unit = {"HOUR": "heure", "YEAR": "an", "MONTH": "mois", "DAY": "jour"}.get(str(value.get("unitText") or ""), "")
    if lo is None and hi is None:
        return ""

    def fmt(x):
        return f"{x:,.2f}".replace(",", " ").replace(".", ",").replace(",00", "") if isinstance(x, (int, float)) else str(x)
    text = f"{fmt(lo)} à {fmt(hi)} €" if lo is not None and hi is not None and lo != hi else f"{fmt(lo if lo is not None else hi)} €"
    return text + (f" / {unit}" if unit else "")


def parse_offer_page(page):
    """{title, location, posted, contract, duration, salary, experience, description}."""
    soup = BeautifulSoup(page, "html.parser")
    data = _job_posting(soup)
    values = _labelled_values(soup)
    address = ((data.get("jobLocation") or {}).get("address") or {})
    location = " ".join(x for x in [address.get("addressLocality"),
                                    f"({address['postalCode']})" if address.get("postalCode") else ""] if x)
    parts = [clean_text(data.get("description") or ""), clean_text(data.get("qualifications") or "")]
    return {
        "title": clean_text(data.get("title") or (soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else "")),
        "location": location or values.get("Localisation", ""),
        "posted": parse_iso_date(data.get("datePosted")),
        "contract": values.get("Contrat", ""),
        "duration": values.get("Durée du contrat", ""),
        "salary": _salary(data),
        "experience": clean_text(str(data.get("experienceRequirements") or "")),
        "description": "\n\n".join(p for p in parts if p),
    }


def departement_ok(location, cfg):
    """Optional filter on départements (crit.departements: [75, 92, 91...]); empty = all France."""
    wanted = [str(d).strip() for d in (cfg.get("departements") or []) if str(d).strip()]
    if not wanted:
        return True
    m = _POSTCODE_RE.search(location or "")
    if not m:
        return True     # unknown: let Gemini decide
    code = m.group(1)
    return any(code.startswith(d.zfill(2)) for d in wanted)


def contract_label(d):
    return " · ".join(x for x in [d.get("contract"), d.get("duration")] if x)


def scrape(session, settings, stored, since, today=None):
    cfg = settings.get("crit", {}) or {}
    excluded = settings.get("excluded_title_words", [])
    types = type_params(settings)
    wanted = {CONTRACT_KEYS[t.lower()] for t in types} if types else None

    lastmods = {}
    try:
        lastmods = parse_sitemap(get_html(session, SITEMAP_URL) or "")
        log.info(f"CRIT sitemap: {len(lastmods)} offers")
    except SourceBlocked:
        raise
    except Exception as e:
        log.warning(f"CRIT sitemap unavailable ({e}): offer dates read on each page.")

    found = {}
    for keyword in settings["keywords"]:
        for page in range(1, cfg.get("pages_per_keyword", 2) + 1):
            params = {"motsClefs": keyword, "page": page}
            if types:
                params["typeContrat"] = types
            try:
                html = get_html(session, SEARCH_URL, params=params)
            except SourceBlocked:
                if not found:
                    raise
                log.warning(f"CRIT limiting searches: continuing with the {len(found)} offer(s) already listed.")
                break
            polite_sleep()
            if not html:
                break
            cards = parse_search_page(html)
            log.info(f"CRIT '{keyword}' p{page}: {len(cards)} cards")
            for c in cards:
                key = PREFIX + c["id"]
                if key in stored or key in found:
                    continue
                lastmod = lastmods.get(c["id"])
                if lastmod and lastmod < since:
                    continue
                if title_is_excluded(c["title"], excluded) or not departement_ok(c["location"], cfg):
                    continue
                if wanted is not None and c["contract"] and contract_key(c["contract"]) not in wanted:
                    continue
                found[key] = c
            if len(cards) < PAGE_SIZE:
                break
    log.info(f"CRIT: {len(found)} new offer(s) to read")

    offers = {}
    max_details = cfg.get("max_details_per_run", 80)
    for n, (key, c) in enumerate(found.items()):
        if n >= max_details:
            log.info(f"CRIT: {len(found) - n} more offer(s) left for the next run.")
            break
        url = OFFER_URL.format(id=c["id"])
        try:
            page = get_html_patient(session, url)
            polite_sleep(1, 2.5)
        except SourceBlocked as e:
            log.warning(f"CRIT limiting offer pages ({e}): keeping {len(offers)} offer(s), the rest next run.")
            break
        except Exception as e:
            log.warning(f"CRIT detail failed for {url}: {e}")
            continue
        if not page:
            continue
        d = parse_offer_page(page)
        posted = d["posted"] or lastmods.get(c["id"])
        if posted and posted < since:
            continue
        d["contract"] = d["contract"] or c["contract"]
        extra = [f"{k} : {v}" for k, v in (("Contrat", d["contract"]), ("Durée du contrat", d["duration"]),
                                           ("Salaire", d["salary"]), ("Expérience demandée", d["experience"])) if v]
        description = (d["description"] + ("\n\n" + "\n".join(extra) if extra else "")).strip()
        offers[key] = make_offer("CRIT", d["title"] or c["title"], COMPANY, d["location"] or c["location"], url,
                                 posted, contract=contract_label(d), description=description)
    return offers


def fetch_description(session, url):
    page = get_html(session, url)
    if not page:
        return ""
    d = parse_offer_page(page)
    extra = [f"{k} : {v}" for k, v in (("Contrat", d["contract"]), ("Durée du contrat", d["duration"]),
                                       ("Salaire", d["salary"]), ("Expérience demandée", d["experience"])) if v]
    return (d["description"] + ("\n\n" + "\n".join(extra) if extra else "")).strip()
