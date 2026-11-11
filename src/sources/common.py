import logging
import random
import re
import time
from datetime import date, datetime, timedelta

import requests

log = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
]

HTTP_MAX_RETRIES = 3
HTTP_RETRY_WAIT = 8


class SourceBlocked(Exception):
    """The site refused us (403, 429, 999...). Stop this source for this run."""


def new_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    return s


def polite_sleep(min_s=1.5, max_s=3.5):
    time.sleep(random.uniform(min_s, max_s))


def get_html(session, url, params=None):
    """GET a page, retrying on network errors / 5xx. Raises SourceBlocked on refusal."""
    for attempt in range(1, HTTP_MAX_RETRIES + 1):
        try:
            r = session.get(url, params=params, timeout=30)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            log.warning(f"HTTP WARNING - {url} attempt {attempt}/{HTTP_MAX_RETRIES}: {e}")
            time.sleep(HTTP_RETRY_WAIT)
            continue

        if r.status_code in (403, 429, 999):
            raise SourceBlocked(f"HTTP {r.status_code} on {r.url}")
        if r.status_code == 404:
            return None
        if r.status_code >= 500:
            log.warning(f"HTTP WARNING - {r.status_code} on {url} attempt {attempt}/{HTTP_MAX_RETRIES}")
            time.sleep(HTTP_RETRY_WAIT)
            continue

        r.raise_for_status()
        return r.text

    raise RuntimeError(f"Request failed after {HTTP_MAX_RETRIES} attempts: {url}")


BLOCK_BACKOFF = 60


def get_html_patient(session, url, params=None, backoff=None):
    """get_html, but on a rate limit wait once (default 60 s) and retry before giving up."""
    try:
        return get_html(session, url, params=params)
    except SourceBlocked as e:
        wait = BLOCK_BACKOFF if backoff is None else backoff
        log.warning(f"Rate limited ({e}); waiting {wait}s before one retry...")
        time.sleep(wait)
        return get_html(session, url, params=params)


def clean_text(text):
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


_RELATIVE = re.compile(r"il y a\s+(\d+)\s*(minute|heure|jour|semaine|mois)", re.IGNORECASE)


def parse_relative_date(text, today=None):
    """'il y a 5 jours' -> date. Returns None when not understood."""
    today = today or date.today()
    if not text:
        return None
    t = text.replace("\xa0", " ").lower()
    if "aujourd" in t or "instant" in t:
        return today
    if "hier" in t:
        return today - timedelta(days=1)
    m = _RELATIVE.search(t)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    if unit in ("minute", "heure"):
        return today
    if unit == "jour":
        return today - timedelta(days=n)
    if unit == "semaine":
        return today - timedelta(weeks=n)
    if unit == "mois":
        return today - timedelta(days=30 * n)
    return None


def parse_iso_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def title_is_excluded(title, excluded_words):
    t = f" {(title or '').lower()} "
    for w in excluded_words:
        w = w.lower().strip()
        if not w:
            continue
        if re.search(r"(?<![a-zà-ÿ])" + re.escape(w) + r"(?![a-zà-ÿ])", t):
            return True
    return False


def make_offer(source, title, company, location, url, posted, contract="", description=""):
    return {
        "source": source,
        "title": clean_text(title),
        "company": clean_text(company),
        "location": clean_text(location),
        "contract": clean_text(contract),
        "url": url,
        "posted": posted.isoformat() if isinstance(posted, date) else (posted or ""),
        "description": description,
        "relevancy_check": "unchecked",
        "reason": "",
    }


_BLOCK_TAGS = ["p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "br"]


def html_to_text(node_or_html):
    """Readable text from HTML: line breaks for block tags, inline tags kept inline."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(node_or_html, "html.parser") if isinstance(node_or_html, str) else node_or_html
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(_BLOCK_TAGS):
        if tag.name == "li":
            tag.insert_before("\n- ")
        else:
            tag.insert_before("\n")
        tag.insert_after("\n")
    return clean_text(soup.get_text(""))
