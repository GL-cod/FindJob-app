"""Adecco France (adecco.com/fr-fr) — intérim, CDD et CDI.

Adecco's search page is filled by JavaScript, but the site publishes a job sitemap for
search engines (listed in robots.txt: Sitemap: https://www.adecco.com/jobsindex.xml):
  /sitemap-jobs-france-fr.xml -> every open offer in France (~11 000), each as
    <url><lastmod>2026-11-24T09:23:19Z</lastmod>
         <loc>https://www.adecco.com/fr-fr/offres-emploi/technicien-support-informatique-h-f-massy-essonne/2153392801</loc></url>
  The slug carries the title, the city and the département, so keywords are matched on it.
Offer page (public HTML): a schema.org JobPosting JSON-LD block (title, description,
  datePosted, jobLocation, baseSalary) and, in the page, the contract (« Intérim », « CDD »,
  « CDI »), the start date and the length of the mission.
"""
import html as html_lib
import json
import logging
import re
import unicodedata

from bs4 import BeautifulSoup

from .common import (
    SourceBlocked, clean_text, get_html, get_html_patient, html_to_text, make_offer, parse_iso_date,
    polite_sleep, title_is_excluded,
)

log = logging.getLogger(__name__)

BASE = "https://www.adecco.com"
SITEMAP_URL = BASE + "/sitemap-jobs-france-fr.xml"
PREFIX = "ad_"
COMPANY = "Adecco"

_URL_RE = re.compile(r"<url>(.*?)</url>", re.S)
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_LASTMOD_RE = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>")
_OFFER_PATH_RE = re.compile(r"/fr-fr/offres-emploi/([a-z0-9-]+)/(\d+)/?$")
_STOPWORDS = {"d", "de", "du", "des", "l", "la", "le", "les", "et", "en", "a", "au", "aux", "h", "f", "hf"}

# Contract labels shown by Adecco -> the names used in cdi_search.yaml (`contrats`)
CONTRACT_KEYS = {"interim": "interim", "intérim": "interim", "travail temporaire": "interim",
                 "cdd": "CDD", "cdi": "CDI", "cdi interimaire": "CDI", "cdi intérimaire": "CDI"}


def slugify(text):
    """'Développeur C#' -> 'developpeur-c', "Côtes-d'Armor" -> 'cotes-darmor' (like Adecco's URL slugs)."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    text = re.sub(r"['’`]", "", text)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def keyword_tokens(keyword):
    return [t for t in slugify(keyword).split("-") if t and t not in _STOPWORDS]


_MARKER_RE = re.compile(r"(.*?)-(?:h-f|f-h|hf|fh)(?:-(.*)|$)")


def slug_title(slug):
    """Title part of a slug: everything before the « h-f » / « hf » marker (else the whole slug)."""
    m = _MARKER_RE.match(slug)
    return (m.group(1) if m else slug).replace("-", " ")


def slug_place(slug):
    """City + département part of a slug (after the « h-f » marker), '' if unknown."""
    m = _MARKER_RE.match(slug)
    return (m.group(2) or "") if m else ""


def matches(slug, keyword):
    """All the keyword's words appear in the title part of the slug."""
    words = set(slug_title(slug).split())
    tokens = keyword_tokens(keyword)
    return bool(tokens) and all(t in words for t in tokens)


def offer_id(url):
    m = _OFFER_PATH_RE.search(url or "")
    return m.group(2) if m else None


def parse_sitemap(xml):
    """[{id, slug, url, lastmod (date or None)}] from the France job sitemap."""
    out = []
    for block in _URL_RE.findall(xml or ""):
        loc = _LOC_RE.search(block)
        if not loc:
            continue
        url = html_lib.unescape(loc.group(1))
        m = _OFFER_PATH_RE.search(url)
        if not m:
            continue
        lastmod = _LASTMOD_RE.search(block)
        out.append({"id": m.group(2), "slug": m.group(1), "url": url,
                    "lastmod": parse_iso_date(lastmod.group(1)) if lastmod else None})
    return out


def _decode_description(raw):
    """Adecco escapes the description's HTML twice (&#60;p&#62; ...): undo it, then make text."""
    text = raw or ""
    for _ in range(3):
        decoded = html_lib.unescape(text)
        if decoded == text:
            break
        text = decoded
    return html_to_text(text)


def _icon_fields(soup):
    """{icon name: text} for the lines under the title (location_on, work_outline, av_timer...)."""
    fields = {}
    for line in soup.select(".job-icon"):
        spans = line.find_all("span")
        if len(spans) >= 2:
            fields[spans[0].get_text(strip=True)] = spans[-1].get_text(" ", strip=True)
    return fields


def parse_offer_page(page):
    """Offer details: {title, location, posted, contract, duration, start, salary, description}."""
    soup = BeautifulSoup(page, "html.parser")
    data = {}
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
        if d.get("@type") == "JobPosting":
            data = d
            break

    icons = _icon_fields(soup)
    address = ((data.get("jobLocation") or {}).get("address") or {})
    location = address.get("location") or icons.get("location_on") or ""

    salary = ""
    value = ((data.get("baseSalary") or {}).get("value") or {})
    lo, hi, unit = (str(value.get(k) or "").strip() for k in ("minValue", "maxValue", "unitText"))
    if lo or hi:
        salary = (f"{lo} - {hi} €" if lo and hi and lo != hi else f"{lo or hi} €") + (f" / {unit}" if unit else "")

    def after_colon(text):
        return text.split(":", 1)[1].strip() if ":" in text else text

    description = _decode_description(data.get("description"))
    if not description:
        main = soup.select_one("main") or soup
        description = html_to_text(main)[:8000]

    return {
        "title": clean_text(data.get("title") or (soup.title.get_text().split("|")[0] if soup.title else "")),
        "location": clean_text(_nice_place(location)),
        "posted": parse_iso_date(data.get("datePosted")),
        "contract": icons.get("work_outline", ""),
        "duration": after_colon(icons.get("av_timer", "")),
        "start": after_colon(icons.get("event", "")),
        "working_time": icons.get("acute", "") or (data.get("employmentType") or ""),
        "salary": salary,
        "description": description,
    }


def _nice_place(text):
    """« MASSY, Essonne » -> « Massy, Essonne » (Adecco writes the city in capitals)."""
    parts = [p.strip() for p in (text or "").split(",")]
    return ", ".join(p.title() if p.isupper() else p for p in parts if p)


def contract_key(label):
    return CONTRACT_KEYS.get(clean_text(label).lower(), "")


def contract_label(details):
    """« Intérim · 6 mois · Temps plein » for the app's contract field."""
    parts = [details.get("contract"), details.get("duration"), details.get("working_time")]
    return " · ".join(p for p in parts if p)


def wanted_contracts(settings):
    """Set of contract keys wanted (CDI / CDD / interim), or None for all.

    Without the `contrats` setting (older cdi_search.yaml), CDI only, like the other sources then."""
    if "contrats" not in settings:
        return {"CDI"}
    contrats = settings.get("contrats")
    if not contrats:
        return None
    return {contract_key(c) or str(c).strip() for c in contrats}


def location_ok(slug, cfg):
    """Optional filter on départements / villes (adecco.lieux in cdi_search.yaml); empty = all France."""
    lieux = [slugify(x) for x in (cfg.get("lieux") or []) if str(x).strip()]
    if not lieux:
        return True
    place = f"-{slug_place(slug)}-"
    return any(f"-{x}-" in place for x in lieux)


def scrape(session, settings, stored, since, today=None):
    cfg = settings.get("adecco", {}) or {}
    excluded = settings.get("excluded_title_words", [])
    wanted = wanted_contracts(settings)

    xml = get_html(session, SITEMAP_URL)
    if not xml:
        log.warning("Adecco: job sitemap not found.")
        return {}
    entries = parse_sitemap(xml)
    log.info(f"Adecco sitemap: {len(entries)} offers in France")

    found = {}
    for e in entries:
        key = PREFIX + e["id"]
        if key in stored or key in found:
            continue
        if e["lastmod"] and e["lastmod"] < since:
            continue
        if not location_ok(e["slug"], cfg):
            continue
        title = slug_title(e["slug"])
        if title_is_excluded(title, excluded):
            continue
        if any(matches(e["slug"], k) for k in settings["keywords"]):
            found[key] = e
    # newest first, so the cap below keeps the freshest offers
    found = dict(sorted(found.items(), key=lambda kv: kv[1]["lastmod"] or since, reverse=True))
    log.info(f"Adecco: {len(found)} offer(s) match the keywords")

    offers = {}
    max_details = cfg.get("max_details_per_run", 80)
    for n, (key, e) in enumerate(found.items()):
        if n >= max_details:
            log.info(f"Adecco: {len(found) - n} more offer(s) left for the next run.")
            break
        try:
            page = get_html_patient(session, e["url"])
            polite_sleep(1, 2.5)
        except SourceBlocked as err:
            log.warning(f"Adecco limiting offer pages ({err}): keeping {len(offers)} offer(s), the rest next run.")
            break
        except Exception as err:
            log.warning(f"Adecco detail failed for {e['url']}: {err}")
            continue
        if not page:            # offer closed in the meantime
            continue
        d = parse_offer_page(page)
        posted = d["posted"] or e["lastmod"]
        if posted and posted < since:
            continue
        if wanted is not None and d["contract"] and contract_key(d["contract"]) not in wanted:
            continue
        if title_is_excluded(d["title"], excluded):
            continue
        description = d["description"]
        extra = [f"{k} : {v}" for k, v in (("Contrat", d["contract"]), ("Durée de la mission", d["duration"]),
                                           ("Début", d["start"]), ("Salaire", d["salary"])) if v]
        if extra:
            description = (description + "\n\n" + "\n".join(extra)).strip()
        offers[key] = make_offer("Adecco", d["title"] or title_case(slug_title(e["slug"])), COMPANY,
                                 d["location"], e["url"], posted, contract=contract_label(d),
                                 description=description)
    return offers


def title_case(text):
    return text[:1].upper() + text[1:]


def fetch_description(session, url):
    page = get_html(session, url)
    if not page:
        return ""
    d = parse_offer_page(page)
    extra = [f"{k} : {v}" for k, v in (("Contrat", d["contract"]), ("Durée de la mission", d["duration"]),
                                       ("Salaire", d["salary"])) if v]
    return (d["description"] + ("\n\n" + "\n".join(extra) if extra else "")).strip()

