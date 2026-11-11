"""France Travail (ex Pôle emploi) through its official, free API « Offres d'emploi v2 ».

Credentials: create an application on https://francetravail.io and subscribe it to
« API Offres d'emploi ». Its identifier and secret go in FT_CLIENT_ID / FT_CLIENT_SECRET
(GitHub secrets, or .env on the PC). Without them the source is simply skipped.

Token:  POST entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire
Search: GET  api.francetravail.io/partenaire/offresdemploi/v2/offres/search
        (200 = all results, 206 = partial, 204 = none; at most 150 per call)
Offer:  GET  .../offres/<id>
The search already returns the full description: no detail call needed.
"""
import logging
import os
import re
import time

from .common import SourceBlocked, make_offer, parse_iso_date, title_is_excluded

log = logging.getLogger(__name__)

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
API = "https://api.francetravail.io/partenaire/offresdemploi/v2"
SEARCH_URL = API + "/offres/search"
DETAIL_URL = API + "/offres/{id}"
PUBLIC_URL = "https://candidat.francetravail.fr/offres/recherche/detail/{id}"
PREFIX = "ft_"
SCOPES = ("api_offresdemploiv2 o2dsoffre", "api_offresdemploiv2")
PUBLISHED_SINCE = (1, 3, 7, 14, 31)   # the only values the API accepts


class MissingCredentials(Exception):
    pass


def credentials():
    cid, secret = os.environ.get("FT_CLIENT_ID", "").strip(), os.environ.get("FT_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        raise MissingCredentials("FT_CLIENT_ID / FT_CLIENT_SECRET not set")
    return cid, secret


def get_token(session):
    cid, secret = credentials()
    last = None
    for scope in SCOPES:
        r = session.post(TOKEN_URL, params={"realm": "/partenaire"}, timeout=30, data={
            "grant_type": "client_credentials", "client_id": cid, "client_secret": secret, "scope": scope})
        if r.ok and r.json().get("access_token"):
            return r.json()["access_token"]
        last = f"HTTP {r.status_code}: {r.text[:200]}"
    raise SourceBlocked(f"France Travail refused the credentials ({last})")


def keyword_param(keyword):
    """« chef de projet IT » -> « chef,de,projet,IT » (the API wants comma-separated words of 2+ chars)."""
    words = [w for w in re.split(r"[\s,]+", keyword) if len(w) >= 2]
    return ",".join(words)


def published_since(max_days):
    return next((d for d in PUBLISHED_SINCE if d >= max_days), PUBLISHED_SINCE[-1])


def search(session, token, keyword, cfg, max_days):
    params = {
        "motsCles": keyword_param(keyword),
        "typeContrat": cfg.get("contrat", "CDI"),
        "publieeDepuis": published_since(cfg.get("published_within_days", max_days)),
        "sort": 1,                                   # newest first
        "range": f"0-{cfg.get('max_results_per_keyword', 150) - 1}",
    }
    if cfg.get("departements"):
        params["departement"] = ",".join(str(d) for d in cfg["departements"])
    else:
        params["region"] = cfg.get("region", "11")   # 11 = Île-de-France
    for attempt in range(3):
        r = session.get(SEARCH_URL, params=params, timeout=30,
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if r.status_code == 429:
            time.sleep(2 + attempt * 3)
            continue
        if r.status_code == 204:
            return []
        if r.status_code in (401, 403):
            raise SourceBlocked(f"HTTP {r.status_code} on France Travail search")
        if r.status_code == 400:
            log.warning(f"France Travail: keyword '{keyword}' rejected ({r.text[:150]}), skipped.")
            return []
        r.raise_for_status()
        return (r.json() or {}).get("resultats") or []
    raise SourceBlocked("France Travail: too many requests")


def offer_description(o):
    parts = [o.get("description") or ""]
    extra = [
        ("Expérience", o.get("experienceLibelle")),
        ("Salaire", (o.get("salaire") or {}).get("libelle")),
        ("Qualification", o.get("qualificationLibelle")),
        ("Secteur", o.get("secteurActiviteLibelle")),
    ]
    comps = [c.get("libelle") for c in o.get("competences") or [] if c.get("libelle")]
    if comps:
        extra.append(("Compétences", " ; ".join(comps)))
    if (o.get("entreprise") or {}).get("description"):
        extra.append(("Entreprise", o["entreprise"]["description"]))
    lines = [f"{k} : {v}" for k, v in extra if v]
    return "\n\n".join(p for p in parts + ["\n".join(lines)] if p).strip()


def to_offer(o):
    loc = (o.get("lieuTravail") or {}).get("libelle") or ""
    loc = re.sub(r"^\d{2,3}\s*-\s*", "", loc)       # « 75 - Paris 15e » -> « Paris 15e »
    return make_offer(
        "France Travail", o.get("intitule") or "", (o.get("entreprise") or {}).get("nom") or "", loc,
        PUBLIC_URL.format(id=o["id"]), parse_iso_date(o.get("dateCreation") or ""),
        contract=o.get("typeContratLibelle") or o.get("typeContrat") or "CDI",
        description=offer_description(o))


def scrape(session, settings, stored, since, today=None):
    cfg = settings.get("francetravail", {})
    excluded = settings.get("excluded_title_words", [])
    try:
        token = get_token(session)
    except MissingCredentials:
        log.warning("France Travail: no API credentials (FT_CLIENT_ID / FT_CLIENT_SECRET), skipped.")
        return {}
    found = {}
    for keyword in settings["keywords"]:
        results = search(session, token, keyword, cfg, settings.get("max_days", 21))
        kept = 0
        for o in results:
            if not o.get("id"):
                continue
            key = PREFIX + str(o["id"])
            if key in stored or key in found or title_is_excluded(o.get("intitule") or "", excluded):
                continue
            offer = to_offer(o)
            posted = parse_iso_date(offer["posted"])
            if posted and posted < since:
                continue
            found[key] = offer
            kept += 1
        log.info(f"France Travail '{keyword}': {len(results)} offers, {kept} new")
        time.sleep(0.3)   # API limit: 10 calls per second
    return found


def fetch_description(session, offer_id):
    """Full text of one offer (for letters / interview prep in the app)."""
    token = get_token(session)
    r = session.get(DETAIL_URL.format(id=offer_id), timeout=30,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    if r.status_code != 200:
        return ""
    return offer_description(r.json())
