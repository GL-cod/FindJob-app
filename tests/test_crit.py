import json
from datetime import date

import pytest

from src import cdi_main, sheets, stats
from src.sources import crit

SINCE = date(2026, 11, 5)
TODAY = date(2026, 11, 26)
U1 = "40c4382c-c03f-4294-a5e7-ec232dfc6818"   # Neuilly, intérim, recent
U2 = "d118da76-2cf1-4e92-8955-9d9816691d5f"   # Paris 16e, intérim, recent
U3 = "7245fba4-5426-4d07-9113-54790372d7cf"   # old (sitemap)
U4 = "00005ba8-6f92-4519-bc18-e11aab74a865"   # CDI senior -> excluded word


def card(uuid, title, contract, place):
    # shape of a real card (26/11/2026)
    return (f'<a class="MuiBox-root css-jz3v3e" href="/offres/{uuid}"><div></div><h3 class="MuiTypography-h6">{title}</h3>'
            f'<div><div><div><p class="MuiTypography-caption">Contrat</p><p class="MuiTypography-subtitle1">{contract}</p></div>'
            f'<div><p class="MuiTypography-caption">Date de début</p><p class="MuiTypography-subtitle1">Dès que possible</p></div>'
            f'<div><p class="MuiTypography-caption">Salaire / heure</p><p class="MuiTypography-subtitle1">13,00&nbsp;€ à 15,00&nbsp;€</p></div></div>'
            f'<hr><div><div><span class="icon icon-pin-fill MuiBox-root" data-testid="icon-pin-fill"></span></div>'
            f'<p class="MuiTypography-body2">{place}</p></div></div></a>')


SEARCH = ("<html><body><a href='/offres/'>Trouver un emploi</a>"
          + card(U1, "Technicien Informatique Helpdesk H/F", "Intérim", "Neuilly-sur-Seine (92200)")
          + card(U2, "Technicien Informatique Support Utilisateur H/F", "Intérim", "Paris - 16ème arrondissement (75016)")
          + card(U3, "Technicien informatique H/F", "CDD", "Mesnils-sur-Iton (27240)")
          + card(U4, "Technicien informatique senior H/F", "CDI", "Lyon (69003)")
          + "</body></html>")

SITEMAP = (f"<urlset><url><loc>https://www.crit-job.com/offres/</loc></url>"
           f"<url><loc>https://www.crit-job.com/offres/{U1}</loc><lastmod>2026-11-12T10:01:55.000Z</lastmod></url>"
           f"<url><loc>https://www.crit-job.com/offres/{U2}</loc><lastmod>2026-11-12T09:56:42.000Z</lastmod></url>"
           f"<url><loc>https://www.crit-job.com/offres/{U3}</loc><lastmod>2026-09-01T00:00:00.000Z</lastmod></url>"
           f"</urlset>")


def offer_page(title="Technicien Informatique Helpdesk H/F", city="Neuilly-sur-Seine", cp="92200",
               posted="2026-11-12T10:01:55.000Z", unit="HOUR", lo=13, hi=15):
    ld = {"@context": "https://schema.org", "@type": "JobPosting", "title": title,
          "description": "Nous recherchons un Technicien Informatique HELPDESK en intérim.\n\nMissions :\n- Support N1",
          "qualifications": "- Expérience de 1 à 2 ans dans le domaine de l'informatique.",
          "datePosted": posted, "employmentType": "OTHER", "experienceRequirements": "1-2 ans",
          "hiringOrganization": {"@type": "Organization", "name": "CRIT MONTIGNY-LE-BRETONNEUX"},
          "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": city,
                                                         "postalCode": cp}},
          "baseSalary": {"@type": "MonetaryAmount", "currency": "EUR",
                         "value": {"@type": "QuantitativeValue", "minValue": lo, "maxValue": hi, "unitText": unit}}}
    return (f'<html><head><script type="application/ld+json">{json.dumps({"@type": "BreadcrumbList"})}</script>'
            f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script></head><body>'
            f'<h1>{title}</h1><p>Offre parue le 12 novembre 2026</p>'
            f'<div><p class="body2">Localisation</p><div><p class="subtitle2">{city} ({cp})</p></div></div>'
            f'<div><p class="body2">Contrat</p><div><p class="subtitle2">Intérim - Temps plein</p></div></div>'
            f'<div><p class="body2">Durée du contrat</p><div><p class="subtitle2">18 mois</p></div></div>'
            f'</body></html>')


def test_parse_search_page():
    cards = crit.parse_search_page(SEARCH)
    assert [c["id"] for c in cards] == [U1, U2, U3, U4]
    assert cards[0] == {"id": U1, "title": "Technicien Informatique Helpdesk H/F", "contract": "Intérim",
                        "location": "Neuilly-sur-Seine (92200)"}


def test_parse_sitemap_and_offer():
    assert crit.parse_sitemap(SITEMAP) == {U1: date(2026, 11, 12), U2: date(2026, 11, 12), U3: date(2026, 9, 1)}
    d = crit.parse_offer_page(offer_page())
    assert d["title"] == "Technicien Informatique Helpdesk H/F"
    assert d["location"] == "Neuilly-sur-Seine (92200)" and d["posted"] == date(2026, 11, 12)
    assert d["contract"] == "Intérim - Temps plein" and d["duration"] == "18 mois"
    assert d["salary"] == "13 à 15 € / heure" and d["experience"] == "1-2 ans"
    assert "Support N1" in d["description"] and "1 à 2 ans" in d["description"]
    assert crit.parse_offer_page(offer_page(unit="YEAR", lo=25000, hi=30000))["salary"] == "25 000 à 30 000 € / an"


def test_type_params_and_contracts():
    assert crit.type_params({"contrats": ["CDI", "CDD", "interim"]}) == ["CDI", "CDII", "CDD", "Intérim"]
    assert crit.type_params({}) == ["CDI", "CDII"]                    # older yaml: CDI only
    assert crit.type_params({"contrats": []}) == []                   # empty = all
    assert crit.contract_key("Intérim - Temps plein") == "interim" and crit.contract_key("CDII") == "CDI"
    assert crit.departement_ok("Neuilly-sur-Seine (92200)", {"departements": [92, 75]})
    assert not crit.departement_ok("Lyon (69003)", {"departements": [92, 75]})
    assert crit.departement_ok("Lyon (69003)", {})


@pytest.fixture
def fake_get(monkeypatch):
    calls = []

    def get(session, url, params=None):
        calls.append((url, params))
        if url == crit.SITEMAP_URL:
            return SITEMAP
        if url == crit.SEARCH_URL:
            return SEARCH if params["page"] == 1 else "<html></html>"
        if url.endswith(U1):
            return offer_page()
        if url.endswith(U2):
            return offer_page("Technicien Informatique Support Utilisateur H/F", "Paris - 16ème arrondissement",
                              "75016", "2026-11-12T09:56:42.000Z", "YEAR", 25000, 30000)
        return None

    monkeypatch.setattr(crit, "get_html", get)
    monkeypatch.setattr(crit, "get_html_patient", get)
    monkeypatch.setattr(crit, "polite_sleep", lambda *a, **k: None)
    return calls


def test_scrape(fake_get):
    settings = {"keywords": ["technicien informatique"], "excluded_title_words": ["senior"],
                "contrats": ["CDI", "CDD", "interim"], "crit": {}}
    offers = crit.scrape(None, settings, stored={"crit_" + U2}, since=SINCE, today=TODAY)
    assert set(offers) == {"crit_" + U1}           # U2 known, U3 too old (sitemap), U4 « senior »
    o = offers["crit_" + U1]
    assert o["source"] == "CRIT" and o["company"] == "CRIT" and o["posted"] == "2026-11-12"
    assert o["url"] == f"https://www.crit-job.com/offres/{U1}"
    assert o["contract"] == "Intérim - Temps plein · 18 mois"
    assert "Salaire : 13 à 15 € / heure" in o["description"]
    search = [p for u, p in fake_get if u == crit.SEARCH_URL][0]
    assert search["typeContrat"] == ["CDI", "CDII", "CDD", "Intérim"] and search["motsClefs"] == "technicien informatique"
    assert not any(u.endswith(U3) or u.endswith(U4) for u, _ in fake_get)   # no page read for nothing


def test_scrape_only_cdi_and_departements(fake_get):
    settings = {"keywords": ["technicien informatique"], "excluded_title_words": [], "contrats": ["CDI"],
                "crit": {"departements": [75]}}
    assert crit.scrape(None, settings, set(), SINCE, TODAY) == {}      # intérim cards dropped from the list


def test_crit_wiring(monkeypatch):
    monkeypatch.delenv("CDI_SOURCES", raising=False)
    assert "crit" not in cdi_main.selected_sources({})
    assert "crit" in cdi_main.selected_sources({"crit": {"enabled": True}})
    url = f"https://www.crit-job.com/offres/{U1}"
    assert stats.source_of(url) == "CRIT"
    assert sheets.norm_link(url + "/") == sheets.norm_link(url)


def test_agency_offers_in_two_cities_are_not_duplicates():
    from src import dedupe
    base = {"title": "Technicien Support Informatique (h/f)", "company": "Adecco", "source": "Adecco",
            "relevancy_check": "unchecked"}
    new = {"ad_1": {**base, "location": "Massy, Essonne"}, "ad_2": {**base, "location": "Lyon, Rhône"},
           "ad_3": {**base, "location": "MASSY, Essonne"}}
    assert dedupe.mark_duplicates(new, {}) == 1 and new["ad_3"]["duplicate_of"] == "ad_1"
    assert new["ad_2"]["relevancy_check"] == "unchecked"
    # other boards keep the old key: same title + company = same job
    hw = {"hw_1": {"title": "Dev Python H/F", "company": "Acme", "source": "HelloWork", "location": "Paris"},
          "li_1": {"title": "Dev Python", "company": "ACME SAS", "source": "LinkedIn", "location": "Paris 8e"}}
    assert dedupe.mark_duplicates(hw, {}) == 1
    # store written by the older key: the wrongly flagged one is judged again, the real duplicate stays
    stored = {"ad_1": {**base, "location": "Massy, Essonne"},
              "ad_2": {**base, "location": "Lyon, Rhône", "relevancy_check": "duplicate", "duplicate_of": "ad_1"},
              "ad_3": {**base, "location": "Massy, Essonne", "relevancy_check": "duplicate", "duplicate_of": "ad_1"}}
    assert dedupe.unflag_wrong_duplicates(stored) == 1
    assert stored["ad_2"]["relevancy_check"] == "unchecked" and "duplicate_of" not in stored["ad_2"]
    assert stored["ad_3"]["relevancy_check"] == "duplicate"
