"""APEC (apec.fr) public job search, the one its own search page uses.

Search: POST /cms/webservices/rechercheOffre (JSON) -> {resultats: [...], totalCount}
  lieux 711 = Île-de-France, typesContrat 101888 = CDI, sorted by date.
Offer:  GET /cms/webservices/offre/public?numeroOffre=<n> -> texteHtml, texteHtmlProfil...
Public page: /candidat/recherche-emploi.html/emploi/detail-offre/<numeroOffre>
"""
import logging

from .common import (
    SourceBlocked, html_to_text, make_offer, parse_iso_date, polite_sleep, title_is_excluded,
)

log = logging.getLogger(__name__)

BASE = "https://www.apec.fr"
SEARCH_URL = BASE + "/cms/webservices/rechercheOffre"
DETAIL_URL = BASE + "/cms/webservices/offre/public"
PUBLIC_URL = BASE + "/candidat/recherche-emploi.html/emploi/detail-offre/{numero}"
PREFIX = "apec_"
PAGE_SIZE = 20


def search_body(keyword, lieu, contrat, start=0):
    return {
        "lieux": [lieu] if lieu else [], "fonctions": [], "statutPoste": [],
        "typesContrat": [contrat] if contrat else [], "typesConvention": ["143684", "143685", "143686", "143687"],
        "niveauxExperience": [], "idsEtablissement": [], "secteursActivite": [], "typesTeletravail": [],
        "idNomZonesDeplacement": [], "positionNumbersExcluded": [], "typeClient": "CADRE",
        "sorts": [{"type": "DATE", "direction": "DESCENDING"}],
        "pagination": {"range": PAGE_SIZE, "startIndex": start},
        "activeFiltre": True, "pointGeolocDeReference": {"distance": 0}, "motsCles": keyword,
    }


def _post_json(session, url, body):
    r = session.post(url, json=body, timeout=30, headers={"Accept": "application/json"})
    if r.status_code in (403, 429):
        raise SourceBlocked(f"HTTP {r.status_code} on {url}")
    r.raise_for_status()
    return r.json()


def _get_json(session, url, params):
    r = session.get(url, params=params, timeout=30, headers={"Accept": "application/json"})
    if r.status_code in (403, 429):
        raise SourceBlocked(f"HTTP {r.status_code} on {url}")
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def parse_results(data):
    cards = []
    for o in (data or {}).get("resultats") or []:
        numero = o.get("numeroOffre")
        if not numero or o.get("offreConfidentielle"):
            continue
        cards.append({
            "id": str(numero),
            "title": o.get("intitule") or "",
            "company": o.get("nomCommercial") or "",
            "location": o.get("lieuTexte") or "",
            "posted": parse_iso_date((o.get("datePublication") or "")[:10]),
            "snippet": o.get("texteOffre") or "",
            "salary": o.get("salaireTexte") or "",
        })
    return cards


def parse_detail(data):
    if not data:
        return ""
    parts = [data.get("texteHtml"), data.get("texteHtmlProfil"), data.get("texteHtmlEntreprise")]
    text = "\n\n".join(html_to_text(p) for p in parts if p)
    if data.get("salaireTexte"):
        text += f"\n\nSalaire : {data['salaireTexte']}"
    return text.strip()


def scrape(session, settings, stored, since, today=None):
    cfg = settings.get("apec", {})
    excluded = settings.get("excluded_title_words", [])
    found = {}
    for keyword in settings["keywords"]:
        for page in range(cfg.get("pages_per_keyword", 1)):
            try:
                data = _post_json(session, SEARCH_URL,
                                  search_body(keyword, cfg.get("lieu", "711"), cfg.get("contrat", "101888"),
                                              page * PAGE_SIZE))
            except SourceBlocked:
                if not found:
                    raise
                log.warning(f"APEC limiting searches: continuing with the {len(found)} offer(s) already listed.")
                break
            polite_sleep(1.5, 3)
            cards = parse_results(data)
            log.info(f"APEC '{keyword}' p{page + 1}: {len(cards)} offers")
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

    offers = {}
    max_details = cfg.get("max_details_per_run", 80)
    for n, (key, c) in enumerate(found.items()):
        if n >= max_details:
            log.info(f"APEC: {len(found) - n} more offer(s) left for the next run.")
            break
        description = c["snippet"]
        try:
            description = parse_detail(_get_json(session, DETAIL_URL, {"numeroOffre": c["id"]})) or description
            polite_sleep(1, 2)
        except SourceBlocked as e:
            log.warning(f"APEC limiting offer pages ({e}): keeping {len(offers)} offer(s), the rest next run.")
            break
        except Exception as e:
            log.warning(f"APEC detail failed for {c['id']}: {e}")
        offers[key] = make_offer("APEC", c["title"], c["company"], c["location"],
                                 PUBLIC_URL.format(numero=c["id"]), c["posted"], contract="CDI",
                                 description=description)
    return offers
