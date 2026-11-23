from datetime import date

import pytest

from src import cdi_relevance, temps_travail as tt
from src.sources import francetravail as ft


def test_value_and_aliases():
    assert tt.value({}) is None                                   # old cdi_search.yaml: unchanged
    assert tt.value({"temps_de_travail": "Partiel"}) == "partiel"
    assert tt.value({"temps_de_travail": "temps plein"}) == "plein"
    assert tt.value({"temps_de_travail": None}) == "tous"
    with pytest.raises(ValueError):
        tt.value({"temps_de_travail": "souvent"})


def test_board_filters():
    assert tt.linkedin_job_types({"linkedin": {"job_types": "F"}}) == "F"     # no setting: old value
    assert tt.linkedin_job_types({"temps_de_travail": "partiel", "linkedin": {"job_types": "F"}}) == "P"
    assert tt.linkedin_job_types({"temps_de_travail": "tous"}) == ""
    assert tt.francetravail_param({"temps_de_travail": "plein"}) == "true"
    assert tt.francetravail_param({"temps_de_travail": "partiel"}) == "false"
    assert tt.francetravail_param({"temps_de_travail": "tous"}) is None
    assert tt.francetravail_param({}) is None


def test_detect_and_mismatch():
    assert tt.detect("CDI · Temps partiel") == "partiel"
    assert tt.detect("Temps plein") == "plein"
    assert tt.detect("Part-time") == "partiel"
    assert tt.detect("CDI") is None
    assert tt.mismatch({"contract": "CDI · Temps plein"}, "partiel")
    assert tt.mismatch({"contract": "CDD · Temps partiel"}, "partiel") == ""
    assert tt.mismatch({"contract": "Temps plein"}, "tous") == ""
    assert tt.mismatch({"contract": "Temps plein"}, None) == ""


def test_prompt_mentions_part_time():
    offer = {"title": "Assistant", "company": "X", "location": "Paris", "contract": "CDD", "source": "HelloWork"}
    p = cdi_relevance.relevance_prompt(offer, "profil", work_time="partiel")
    assert "UNIQUEMENT un poste à temps partiel" in p
    assert "temps partiel" not in cdi_relevance.relevance_prompt(offer, "profil")


class FakeHandler:
    def __init__(self):
        self.calls = 0

    def generate(self, prompt):
        self.calls += 1
        return '{"relevant": true, "score": 8, "years_required": 0, "cv": "principal", "reason": "ok"}'


def test_check_offers_skips_wrong_working_time_without_gemini():
    offers = {
        "a": {"title": "Dev", "source": "LinkedIn", "contract": "Temps plein", "relevancy_check": "unchecked"},
        "b": {"title": "Dev", "source": "LinkedIn", "contract": "Temps partiel", "relevancy_check": "unchecked"},
    }
    h = FakeHandler()
    relevant = cdi_relevance.check_offers(offers, "profil", h, 10, draft_letters=False, work_time="partiel")
    assert list(relevant) == ["b"] and h.calls == 1
    assert offers["a"]["relevancy_check"] == "not_relevant" and "temps plein" in offers["a"]["reason"]


class Resp:
    def __init__(self, status, data=None):
        self.status_code, self._data, self.text, self.ok = status, data, "", status < 400

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FTSession:
    def __init__(self, refuse_temps_plein=False):
        self.calls, self.refuse = [], refuse_temps_plein

    def post(self, url, **kw):
        return Resp(200, {"access_token": "tok"})

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(dict(params))
        if self.refuse and "tempsPlein" in params:
            return Resp(400)
        return Resp(200, {"resultats": [{"id": "1", "intitule": "Vendeur", "dateCreation": "2026-11-20T10:00:00Z",
                                         "typeContratLibelle": "CDD", "dureeTravailLibelleConverti": "Temps partiel"}]})


@pytest.fixture
def ft_env(monkeypatch):
    monkeypatch.setenv("FT_CLIENT_ID", "id")
    monkeypatch.setenv("FT_CLIENT_SECRET", "s")
    monkeypatch.setattr(ft.time, "sleep", lambda s: None)


def test_francetravail_part_time(ft_env):
    s = FTSession()
    settings = {"keywords": ["vendeur"], "temps_de_travail": "partiel", "francetravail": {"contrat": ""}}
    found = ft.scrape(s, settings, set(), date(2026, 11, 1))
    assert s.calls[0]["tempsPlein"] == "false" and "typeContrat" not in s.calls[0]
    assert found["ft_1"]["contract"] == "CDD · Temps partiel"


def test_francetravail_retries_without_filter_if_refused(ft_env):
    s = FTSession(refuse_temps_plein=True)
    found = ft.scrape(s, {"keywords": ["vendeur"], "temps_de_travail": "partiel"}, set(), date(2026, 11, 1))
    assert "ft_1" in found and "tempsPlein" not in s.calls[-1]


def test_example_settings_are_valid():
    from src import cdi_main
    for name in ("cdi_search.yaml", "cdi_search.exemple.yaml"):
        assert tt.value(cdi_main.load_settings(cdi_main.PROJECT_ROOT / name)) == "plein"
