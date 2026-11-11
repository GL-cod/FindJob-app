from datetime import date

import pytest

from src import dedupe, stats
from src.sources import apec
from src.sources.common import SourceBlocked

TODAY = date(2026, 11, 10)

SEARCH = {"totalCount": 3, "resultats": [
    {"id": 179702081, "numeroOffre": "179702081W", "intitule": "ingénieur support applicatif F/H",
     "nomCommercial": "YESIT", "lieuTexte": "Noisy-le-Grand - 93", "salaireTexte": "43 - 56 k€ brut annuel",
     "texteOffre": "Rejoignez un acteur majeur de la mobilité...", "datePublication": "2026-11-10T16:53:00.000+0000",
     "offreConfidentielle": False},
    {"numeroOffre": "1C", "intitule": "Chef de projet", "nomCommercial": "X", "offreConfidentielle": True,
     "datePublication": "2026-11-10T00:00:00.000+0000"},
    {"numeroOffre": "2S", "intitule": "Stage PMO", "nomCommercial": "Y", "offreConfidentielle": False,
     "datePublication": "2026-11-09T00:00:00.000+0000"},
]}
DETAIL = {"texteHtml": "<p><strong>Rejoignez</strong> un acteur majeur</p><ul><li>Support N2</li></ul>",
          "texteHtmlProfil": "<p>Vous disposez d&rsquo;au moins 3 ans d&rsquo;exp&eacute;rience</p>",
          "salaireTexte": "43 - 56 k€ brut annuel"}


def test_apec_parsers():
    cards = apec.parse_results(SEARCH)
    assert [c["id"] for c in cards] == ["179702081W", "2S"]            # confidential offer skipped
    assert cards[0]["company"] == "YESIT" and cards[0]["posted"] == date(2026, 11, 10)
    text = apec.parse_detail(DETAIL)
    assert "Rejoignez un acteur majeur" in text and "- Support N2" in text
    assert "au moins 3 ans d’expérience" in text and "Salaire : 43 - 56 k€" in text
    body = apec.search_body("PMO junior", "711", "101888")
    assert body["lieux"] == ["711"] and body["typesContrat"] == ["101888"] and body["motsCles"] == "PMO junior"


class FakeResp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, block_details_after=None):
        self.details = 0
        self.block_after = block_details_after

    def post(self, url, json, timeout, headers):
        assert url == apec.SEARCH_URL
        return FakeResp(200, SEARCH)

    def get(self, url, params, timeout, headers):
        self.details += 1
        if self.block_after is not None and self.details > self.block_after:
            return FakeResp(429, {})
        return FakeResp(200, DETAIL)


def test_apec_scrape(monkeypatch):
    monkeypatch.setattr(apec, "polite_sleep", lambda *a, **k: None)
    settings = {"keywords": ["support"], "excluded_title_words": ["stage"], "apec": {}}
    offers = apec.scrape(FakeSession(), settings, set(), date(2026, 11, 1), today=TODAY)
    assert list(offers) == ["apec_179702081W"]                           # « Stage PMO » excluded
    o = offers["apec_179702081W"]
    assert o["source"] == "APEC" and o["contract"] == "CDI"
    assert o["url"].endswith("/detail-offre/179702081W") and "Support N2" in o["description"]
    # already known -> nothing new
    assert apec.scrape(FakeSession(), settings, {"apec_179702081W"}, date(2026, 11, 1)) == {}


def test_apec_blocked_on_search_raises():
    class Blocked(FakeSession):
        def post(self, *a, **k):
            return FakeResp(429, {})
    with pytest.raises(SourceBlocked):
        apec.scrape(Blocked(), {"keywords": ["x"], "apec": {}}, set(), date(2026, 11, 1))


def test_dedupe_across_boards():
    known = {"hw_1": {"title": "Ingénieur Projet Junior H/F", "company": "Assystem", "relevancy_check": "relevant"}}
    new = {
        "apec_9": {"title": "INGENIEUR PROJET JUNIOR (F/H) - CDI", "company": "ASSYSTEM SAS", "relevancy_check": "unchecked"},
        "li_5": {"title": "Développeur C# H/F", "company": "IT Link", "relevancy_check": "unchecked"},
        "apec_7": {"title": "Développeur C# (F/H)", "company": "IT LINK", "relevancy_check": "unchecked"},
        "li_6": {"title": "Développeur C++ H/F", "company": "IT Link", "relevancy_check": "unchecked"},
    }
    assert dedupe.mark_duplicates(new, known) == 2
    assert new["apec_9"]["duplicate_of"] == "hw_1" and new["apec_7"]["duplicate_of"] == "li_5"
    assert new["li_5"]["relevancy_check"] == "unchecked" and new["li_6"]["relevancy_check"] == "unchecked"


def test_stats_families_sources_insights():
    assert stats.family("Assistant ingénieur pédagogique") == "XR / pédagogie"
    assert stats.family("Consultant PMO") == "Gestion de projet / PMO"
    assert stats.family("Technicien Helpdesk N1") == "Support / technicien"
    assert stats.family("Développeur Junior - C#/SQL (F/H)") == "Développement"
    assert stats.family("Candidature spontanée") == "Candidature spontanée"
    assert stats.source_of("https://www.linkedin.com/jobs/view/1") == "LinkedIn"
    assert stats.source_of("https://www.apec.fr/candidat/x") == "APEC"
    assert stats.source_of("") == "Sans lien"
    rows = [{"poste": "PMO Junior", "retour": "Positif", "date": "10/11/2026"}] + \
           [{"poste": "PMO", "retour": "En attente", "date": "01/11/2026"}] * 5 + \
           [{"poste": "Développeur Python", "retour": "Negatif", "date": "05/10/2026"}] * 5
    fam = {t["Catégorie"]: t for t in stats.breakdown(rows, lambda r: stats.family(r["poste"]))}
    assert fam["Gestion de projet / PMO"]["Positifs"] == 1 and fam["Développement"]["Taux de réponse"] == 100
    text = " ".join(stats.insights(rows))
    assert "Sur 11 candidatures" in text and "Gestion de projet / PMO" in text and "Développement" in text
    assert stats.by_month(rows) == [{"Mois": "2026-10", "Candidatures": 5, "Positifs": 0},
                                    {"Mois": "2026-11", "Candidatures": 6, "Positifs": 1}]


def test_interview_prompt_is_grounded():
    from src import tracking
    p = tracking.interview_prompt({"title": "PMO Junior", "company": "GEC", "source": "LinkedIn"}, "Profil ingénieur", "Missions : reporting")
    assert "n'invente RIEN sur l'entreprise" in p and "Profil ingénieur" in p and "Missions : reporting" in p
    assert "8 questions probables" in p


# ---------------------------------------------------------------- France Travail
from src.sources import francetravail as ft

FT_RESULTS = {"resultats": [
    {"id": "201ABCD", "intitule": "Développeur C# (H/F)", "description": "Vous développerez des applications .NET.",
     "dateCreation": "2026-11-09T10:12:00.000Z", "lieuTravail": {"libelle": "92 - Nanterre"},
     "entreprise": {"nom": "ACME"}, "typeContrat": "CDI", "typeContratLibelle": "Contrat à durée indéterminée",
     "experienceLibelle": "Débutant accepté", "salaire": {"libelle": "Annuel de 38000 Euros"},
     "competences": [{"libelle": "Développer en C#"}]},
    {"id": "201OLD", "intitule": "Ingénieur logiciel", "dateCreation": "2026-09-01T10:00:00.000Z",
     "lieuTravail": {"libelle": "75 - Paris"}, "entreprise": {}},
    {"id": "201STG", "intitule": "Stage développeur", "dateCreation": "2026-11-09T10:00:00.000Z"},
]}


class FakeResp:
    def __init__(self, status, data=None):
        self.status_code, self._data, self.text = status, data, ""
        self.ok = status < 400

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeFTSession:
    def __init__(self, search_status=206):
        self.calls, self.search_status = [], search_status

    def post(self, url, **kw):
        return FakeResp(200, {"access_token": "tok"})

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(params)
        assert headers["Authorization"] == "Bearer tok"
        return FakeResp(self.search_status, FT_RESULTS if self.search_status != 204 else None)


def test_francetravail_helpers():
    assert ft.keyword_param("chef de projet IT") == "chef,de,projet,IT"
    assert ft.keyword_param("développeur C#") == "développeur,C#"
    assert ft.published_since(21) == 31 and ft.published_since(3) == 3 and ft.published_since(90) == 31
    o = ft.to_offer(FT_RESULTS["resultats"][0])
    assert o["source"] == "France Travail" and o["company"] == "ACME" and o["location"] == "Nanterre"
    assert o["url"] == "https://candidat.francetravail.fr/offres/recherche/detail/201ABCD"
    assert o["posted"] == "2026-11-09"
    assert "Expérience : Débutant accepté" in o["description"] and "Développer en C#" in o["description"]


def test_francetravail_scrape(monkeypatch):
    monkeypatch.setenv("FT_CLIENT_ID", "id")
    monkeypatch.setenv("FT_CLIENT_SECRET", "secret")
    monkeypatch.setattr(ft.time, "sleep", lambda s: None)
    s = FakeFTSession()
    settings = {"keywords": ["développeur C#"], "excluded_title_words": ["stage"], "max_days": 21,
                "francetravail": {"region": "11"}}
    found = ft.scrape(s, settings, set(), date(2026, 10, 20), today=TODAY)
    assert list(found) == ["ft_201ABCD"]              # too old and internship dropped
    p = s.calls[0]
    assert p["region"] == "11" and p["typeContrat"] == "CDI" and p["publieeDepuis"] == 31
    assert ft.scrape(s, settings, {"ft_201ABCD"}, date(2026, 10, 20)) == {}
    assert ft.scrape(FakeFTSession(204), settings, set(), date(2026, 10, 20)) == {}


def test_francetravail_without_credentials_is_skipped(monkeypatch):
    monkeypatch.delenv("FT_CLIENT_ID", raising=False)
    monkeypatch.delenv("FT_CLIENT_SECRET", raising=False)
    assert ft.scrape(FakeFTSession(), {"keywords": ["x"]}, set(), date(2026, 10, 1)) == {}


def test_francetravail_refused_credentials_blocks(monkeypatch):
    monkeypatch.setenv("FT_CLIENT_ID", "id")
    monkeypatch.setenv("FT_CLIENT_SECRET", "bad")

    class Refused(FakeFTSession):
        def post(self, url, **kw):
            return FakeResp(401, {})
    with pytest.raises(SourceBlocked):
        ft.scrape(Refused(), {"keywords": ["x"]}, set(), date(2026, 10, 1))
