from datetime import date

import pytest

from src import cdi_main, contrats, sheets, stats
from src.sources import adecco

TODAY = date(2026, 11, 26)
SINCE = date(2026, 11, 5)

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <lastmod>2026-11-24T09:23:19Z</lastmod>
    <loc>https://www.adecco.com/fr-fr/offres-emploi/technicien-support-informatique-h-f-massy-essonne/2153392801</loc>
  </url>
  <url>
    <lastmod>2026-11-20T10:00:00Z</lastmod>
    <loc>https://www.adecco.com/fr-fr/offres-emploi/operateur-de-saisie-h-f-courbevoie-hauts-de-seine/2147386101</loc>
  </url>
  <url>
    <lastmod>2026-09-10T13:59:25Z</lastmod>
    <loc>https://www.adecco.com/fr-fr/offres-emploi/technicien-informatique-h-f-rouen-seine-maritime/2115384001</loc>
  </url>
  <url>
    <lastmod>2026-11-25T08:00:00Z</lastmod>
    <loc>https://www.adecco.com/fr-fr/offres-emploi/cariste-h-f-lyon-rhone/2155555501</loc>
  </url>
  <url>
    <lastmod>2026-11-25T08:00:00Z</lastmod>
    <loc>https://www.adecco.com/fr-fr/offres-emploi/technicien-informatique-senior-h-f-nice-alpes-maritimes/2155555502</loc>
  </url>
  <url>
    <lastmod>2026-11-25T08:00:00Z</lastmod>
    <loc>https://www.adecco.com/fr-fr/offres-emploi/technicien-informatique-h-f-lieusaint-seine-et-marne/2155555503</loc>
  </url>
</urlset>"""

# Shape of a real offer page (25/11/2026): JSON-LD with a twice-escaped description + icon lines
DESC = ("&#60;div class&#61;&#34;VacancyDescription&#34;&#62;&#60;h2&#62;Votre mission&#60;/h2&#62;"
        "&#60;p&#62;Support de proximit&#233; N2 chez notre client &#224; Massy&#46;&#60;/br&#62;"
        "&#8226; Installation de postes&#60;/p&#62;&#60;/div&#62;")


def offer_page(contract="Intérim", title="Technicien Support Informatique (h/f)", posted="2026-11-24T09:23:19.382Z"):
    return f"""<html><head><title>{title} | MASSY, Essonne</title>
<script type="application/ld+json">{{"@context":"https://schema.org","@type":"JobPosting","title":"{title}",
"description":"{DESC}","datePosted":"{posted}","employmentType":"Temps plein",
"baseSalary":{{"@type":"MonetaryAmount","value":{{"@type":"QuantitativeValue","maxValue":"30000 ","minValue":"28000 ","unitText":"Annuel "}}}},
"jobLocation":{{"@type":"Place","address":{{"@type":"PostalAddress","addressLocality":"MASSY","location":"MASSY, Essonne"}}}}}}</script>
</head><body><main>
<div class="flex align-items_center job-icon base"><span class="material-icons-outlined">location_on</span><span>MASSY, Essonne</span></div>
<div class="flex align-items_center job-icon base"><span class="material-icons-outlined">work_outline</span><span>{contract}</span></div>
<div class="flex align-items_center job-icon base"><span class="material-icons-outlined">event</span><span>Début de contrat : Dès que possible</span></div>
<div class="flex align-items_center job-icon base"><span class="material-icons-outlined">av_timer</span><span>Durée de la mission : 6 mois</span></div>
<div class="flex align-items_center job-icon base"><span class="material-symbols-outlined">acute</span><span>Temps plein</span></div>
</main></body></html>"""


def test_slug_helpers():
    slug = "technicien-support-informatique-h-f-massy-essonne"
    assert adecco.slug_title(slug) == "technicien support informatique"
    assert adecco.slug_place(slug) == "massy-essonne"
    assert adecco.slug_title("technicien-informatique-hf-versailles-yvelines") == "technicien informatique"
    assert adecco.matches(slug, "technicien informatique")         # every word, any order
    assert adecco.matches(slug, "Support informatique")
    assert not adecco.matches(slug, "développeur python")
    assert not adecco.matches("operateur-de-saisie-h-f-courbevoie-hauts-de-seine", "informatique")
    assert adecco.matches("operateur-de-saisie-h-f-courbevoie-hauts-de-seine", "opérateur de saisie")
    assert adecco.slugify("Côtes-d'Armor") == "cotes-darmor"
    assert adecco.location_ok(slug, {"lieux": ["Essonne"]})
    assert adecco.location_ok(slug, {"lieux": ["Massy"]})
    assert not adecco.location_ok(slug, {"lieux": ["Hauts-de-Seine", "Paris"]})
    assert adecco.location_ok(slug, {"lieux": []})


def test_parse_sitemap():
    entries = adecco.parse_sitemap(SITEMAP)
    assert len(entries) == 6
    assert entries[0]["id"] == "2153392801" and entries[0]["lastmod"] == date(2026, 11, 24)
    assert entries[0]["slug"] == "technicien-support-informatique-h-f-massy-essonne"


def test_parse_offer_page():
    d = adecco.parse_offer_page(offer_page())
    assert d["title"] == "Technicien Support Informatique (h/f)"
    assert d["location"] == "Massy, Essonne"
    assert d["posted"] == date(2026, 11, 24)
    assert d["contract"] == "Intérim" and d["duration"] == "6 mois" and d["start"] == "Dès que possible"
    assert d["salary"] == "28000 - 30000 € / Annuel"
    assert "Support de proximité N2 chez notre client à Massy." in d["description"]
    assert "<" not in d["description"] and "&#" not in d["description"]
    assert adecco.contract_label(d) == "Intérim · 6 mois · Temps plein"


class FakeSession:
    def __init__(self, pages):
        self.pages, self.calls = pages, []


@pytest.fixture
def fake_get(monkeypatch):
    pages = {adecco.SITEMAP_URL: SITEMAP}

    def get(session, url, params=None):
        session.calls.append(url)
        return pages.get(url)

    monkeypatch.setattr(adecco, "get_html", get)
    monkeypatch.setattr(adecco, "get_html_patient", get)
    monkeypatch.setattr(adecco, "polite_sleep", lambda *a, **k: None)
    return pages


def settings(**extra):
    return {"keywords": ["technicien informatique", "opérateur de saisie"],
            "excluded_title_words": ["senior", "stage"], "contrats": ["CDI", "CDD", "interim"],
            "adecco": {}, **extra}


def test_scrape(fake_get):
    base = "https://www.adecco.com/fr-fr/offres-emploi/"
    fake_get[base + "technicien-support-informatique-h-f-massy-essonne/2153392801"] = offer_page()
    fake_get[base + "operateur-de-saisie-h-f-courbevoie-hauts-de-seine/2147386101"] = offer_page(
        title="Opérateur de Saisie (h/f)", posted="2026-11-20T10:00:00Z")
    fake_get[base + "technicien-informatique-h-f-lieusaint-seine-et-marne/2155555503"] = offer_page(contract="CDI")
    s = FakeSession(fake_get)
    offers = adecco.scrape(s, settings(), stored={"ad_2147386101"}, since=SINCE, today=TODAY)
    # too old (Rouen), no keyword (cariste), excluded word (senior), already known (saisie) -> left out
    assert set(offers) == {"ad_2153392801", "ad_2155555503"}
    o = offers["ad_2153392801"]
    assert o["source"] == "Adecco" and o["company"] == "Adecco"
    assert o["contract"] == "Intérim · 6 mois · Temps plein" and o["posted"] == "2026-11-24"
    assert "Durée de la mission : 6 mois" in o["description"] and "Salaire : 28000 - 30000 €" in o["description"]
    assert not any("cariste" in u or "rouen" in u or "senior" in u for u in s.calls)   # no page read for nothing


def test_scrape_contract_filter_and_places(fake_get):
    base = "https://www.adecco.com/fr-fr/offres-emploi/"
    fake_get[base + "technicien-support-informatique-h-f-massy-essonne/2153392801"] = offer_page()
    fake_get[base + "technicien-informatique-h-f-lieusaint-seine-et-marne/2155555503"] = offer_page(contract="CDI")
    only_cdi = adecco.scrape(FakeSession(fake_get), settings(contrats=["CDI"]), set(), SINCE, TODAY)
    assert set(only_cdi) == {"ad_2155555503"}
    no_setting = {k: v for k, v in settings().items() if k != "contrats"}     # older yaml: CDI only
    assert set(adecco.scrape(FakeSession(fake_get), no_setting, set(), SINCE, TODAY)) == {"ad_2155555503"}
    essonne = adecco.scrape(FakeSession(fake_get), settings(adecco={"lieux": ["Essonne"]}), set(), SINCE, TODAY)
    assert set(essonne) == {"ad_2153392801"}


def test_contrats_setting():
    assert contrats.value({}) is None
    assert contrats.value({"contrats": ["CDI", "cdd", "Intérim"]}) == ["CDI", "CDD", "interim"]
    assert contrats.value({"contrats": "CDI, interim"}) == ["CDI", "interim"]
    with pytest.raises(ValueError):
        contrats.value({"contrats": ["CDI", "freelance"]})
    s = {"contrats": ["CDI", "CDD", "interim"]}
    assert contrats.hellowork_param(s) == ["CDI", "CDD", "Travail_temp"]
    assert contrats.francetravail_param(s) == "CDI,CDD,MIS"
    assert contrats.apec_param(s) == "" and contrats.apec_param({"contrats": ["CDI"]}) == "101888"
    assert contrats.linkedin_job_types("F", s) == "F,C,T"
    assert contrats.linkedin_job_types("F", {"contrats": ["CDI"]}) == "F"
    assert contrats.linkedin_job_types("", s) == ""            # no filter stays no filter
    # without the setting, each source keeps its old one
    old = {"hellowork": {"contracts": "CDI"}, "apec": {"contrat": "101888"}, "francetravail": {"contrat": "CDI"}}
    assert contrats.hellowork_param(old) == "CDI" and contrats.apec_param(old) == "101888"
    assert contrats.francetravail_param(old) == "CDI" and contrats.linkedin_job_types("F", old) == "F"
    assert contrats.label(s) == "CDI, CDD ou intérim"


def test_adecco_is_opt_in(monkeypatch):
    monkeypatch.delenv("CDI_SOURCES", raising=False)
    assert "adecco" not in cdi_main.selected_sources({"hellowork": {"enabled": True}})
    assert "adecco" in cdi_main.selected_sources({"adecco": {"enabled": True}})


def test_adecco_links_match_whatever_the_slug():
    a = "https://www.adecco.com/fr-fr/offres-emploi/technicien-support-informatique-hf-massy-essonne/2153392801"
    b = "https://www.adecco.com/fr-fr/offres-emploi/technicien-support-informatique-h-f-massy-essonne/2153392801/"
    assert sheets.norm_link(a) == sheets.norm_link(b) == "adecco:2153392801"
    assert sheets.norm_link("https://www.hellowork.com/fr-fr/emplois/1.html?x=1") == "https://www.hellowork.com/fr-fr/emplois/1.html"
    assert stats.source_of(a) == "Adecco"
