import json
from datetime import date

import pytest

from src.sources import hellowork, linkedin
from src.sources.common import parse_relative_date, title_is_excluded
from src.cdi_relevance import parse_verdict
from src import cdi_main

TODAY = date(2026, 11, 10)

HW_SEARCH = """<ul>
<li data-id-storage-target="item" data-id-storage-item-id="84261016">
 <div><form><input type="hidden" name="offerId" value="84261016">
 <input type="hidden" name="title" value="Développeur Unity H/F">
 <input type="hidden" name="company" value="Gameloft"></form>
 <a data-cy="offerTitle" href="/fr-fr/emplois/84261016.html"><h3>Développeur Unity H/F <p>Gameloft</p></h3></a>
 <div data-cy="localisationCard">Paris - 75</div><div data-cy="contractCard">CDI</div>
 <div class="typo-s text-grey-500 pl-1 pt-1">il y a 1 jour</div></div></li>
<li data-id-storage-item-id="111"><input name="title" value="Stage développeur"><input name="company" value="X">
 <div data-cy="localisationCard">Paris</div><div>il y a 2 jours</div></li>
<li data-id-storage-item-id="222"><input name="title" value="Chef de projet IT"><input name="company" value="Y">
 <div data-cy="localisationCard">Massy - 91</div><div data-cy="contractCard">CDI</div><div>il y a 40 jours</div></li>
</ul>"""

HW_DETAIL = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting","title":"Développeur Unity H/F",
"description":"<h2>Détail du poste</h2><p>Vous développerez des expériences <b>XR</b>.<br/>C# requis.</p>",
"datePosted":"2026-11-09T00:07:52Z","employmentType":"FULL_TIME","experienceRequirements":"Débutant accepté",
"hiringOrganization":{"name":"Gameloft"}}
</script></head><body><main>x</main></body></html>"""

LI_SEARCH = """<li><div class="base-card base-search-card job-search-card" data-entity-urn="urn:li:jobPosting:4487254006">
<a class="base-card__full-link" href="https://fr.linkedin.com/jobs/view/ingenieur-logiciel-at-thales-4487254006?position=1"></a>
<div class="base-search-card__info"><h3 class="base-search-card__title"> Ingénieur logiciel junior </h3>
<h4 class="base-search-card__subtitle"><a> Thales </a></h4><div class="base-search-card__metadata">
<span class="job-search-card__location"> Palaiseau </span><time class="job-search-card__listdate" datetime="2026-11-09">il y a 1 jour</time>
</div></div></div></li>
<li><div class="base-card base-search-card" data-entity-urn="urn:li:jobPosting:999"><h3 class="base-search-card__title">Senior Developer</h3>
<time datetime="2026-11-09"></time></div></li>"""

LI_DETAIL = """<section><div class="show-more-less-html__markup"><p>Nous cherchons un ingénieur.</p><ul><li>Python</li></ul></div>
<ul class="description__job-criteria-list"><li class="description__job-criteria-item"><h3>Niveau hiérarchique</h3><span>Premier emploi</span></li>
<li class="description__job-criteria-item"><h3>Type d’emploi</h3><span> Temps plein </span></li></ul></section>"""


def test_relative_dates():
    assert parse_relative_date("il y a 5 jours", TODAY) == date(2026, 11, 5)
    assert parse_relative_date("il y a 3 heures", TODAY) == TODAY
    assert parse_relative_date("il y a 2\xa0semaines", TODAY) == date(2026, 10, 27)
    assert parse_relative_date("blah", TODAY) is None


def test_exclusions():
    words = ["stage", "senior", "intern", "head of"]
    assert title_is_excluded("Stage - Développeur", words)
    assert title_is_excluded("Développeur Senior H/F", words)
    assert title_is_excluded("Head of Data", words)
    assert not title_is_excluded("Chef de projet international", words)
    assert not title_is_excluded("Ingénieur interne", words)


def test_hellowork_parsers():
    cards = hellowork.parse_search_page(HW_SEARCH, today=TODAY)
    assert [c["id"] for c in cards] == ["84261016", "111", "222"]
    c = cards[0]
    assert (c["title"], c["company"], c["location"], c["contract"]) == ("Développeur Unity H/F", "Gameloft", "Paris - 75", "CDI")
    assert c["posted"] == date(2026, 11, 9)
    desc, posted, extra = hellowork.parse_offer_page(HW_DETAIL)
    assert "expériences XR" in desc and "C# requis" in desc and "<b>" not in desc
    assert posted == date(2026, 11, 9) and extra["experience"] == "Débutant accepté"


def test_linkedin_parsers():
    cards = linkedin.parse_search_page(LI_SEARCH)
    assert cards[0] == {"id": "4487254006", "title": "Ingénieur logiciel junior", "company": "Thales",
                        "location": "Palaiseau", "posted": date(2026, 11, 9)}
    desc, criteria = linkedin.parse_detail_page(LI_DETAIL)
    assert "Nous cherchons" in desc and "Python" in desc
    assert "Type d’emploi : Temps plein" in criteria


def test_verdict_parsing():
    assert parse_verdict('```json\n{"relevant": true, "years_required": 0, "cv": "projet", "reason": "ok"}\n```') == (True, "projet", "ok", 0)
    assert parse_verdict('{"relevant": "false", "cv": "informatique", "reason": "senior"}')[0] is False
    assert parse_verdict("YES") == (True, "informatique", "", 0)
    assert parse_verdict("garbage")[0] is False


def test_end_to_end(monkeypatch, tmp_path):
    pages = {
        hellowork.SEARCH_URL: HW_SEARCH,
        hellowork.OFFER_URL.format(id="84261016"): HW_DETAIL,
        linkedin.SEARCH_URL: LI_SEARCH,
        linkedin.DETAIL_URL.format(id="4487254006"): LI_DETAIL,
    }
    calls = []

    def fake_get(session, url, params=None):
        calls.append(url)
        return pages.get(url)

    for mod in (hellowork, linkedin):
        monkeypatch.setattr(mod, "get_html", fake_get)
        monkeypatch.setattr(mod, "get_html_patient", fake_get)
        monkeypatch.setattr(mod, "polite_sleep", lambda *a, **k: None)

    prompts = []

    class FakeHandler:
        def __init__(self, *a, **k): pass
        def generate(self, prompt):
            prompts.append(prompt)
            if prompt.startswith("Rédige"):
                return "Madame, Monsieur,\nJe suis <motivé> & disponible.\nCamille Martin"
            if "Thales" in prompt:
                return '{"relevant": true, "score": 8, "cv": "informatique", "reason": "Poste junior logiciel"}'
            return '{"relevant": false, "cv": "informatique", "reason": "non"}'

    sent = []
    monkeypatch.setattr(cdi_main, "GeminiHandler", FakeHandler)
    monkeypatch.setattr(cdi_main, "send_message", lambda text, env: sent.append(text))
    monkeypatch.setattr(cdi_main.time, "sleep", lambda *_: None)
    monkeypatch.setattr(cdi_main, "STORE_PATH", tmp_path / "cdi_offers.json")
    monkeypatch.setattr(cdi_main, "STATE_PATH", tmp_path / "cdi_state.json")
    monkeypatch.setattr(cdi_main, "METRICS_PATH", tmp_path / "m.jsonl")
    for k, v in {"GEMINI_API_KEY": "k", "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1",
                 "CDI_USER_DESCRIPTION": "Ingénieur généraliste", "FORCE_RUN": "1",
                 "CDI_SOURCES": "hellowork,linkedin", "TELEGRAM_ENABLED": "true"}.items():
        monkeypatch.setenv(k, v)

    cdi_main.run()

    store = json.loads((tmp_path / "cdi_offers.json").read_text())
    # stage (excluded title), 40-day-old offer and Senior LinkedIn card are filtered out
    assert set(store) == {"hw_84261016", "li_4487254006"}
    assert store["li_4487254006"]["relevancy_check"] == "relevant"
    assert store["hw_84261016"]["relevancy_check"] == "not_relevant"
    assert all("letter" not in o and "description" not in o for o in store.values())
    assert len(sent) == 2 and "Ingénieur logiciel junior" in sent[0] and "Ingénieur Informatique" in sent[0]
    assert "&lt;motivé&gt; &amp;" in sent[1] and sent[1].count("<pre>") == 1
    m = json.loads((tmp_path / "m.jsonl").read_text())
    assert m["relevant"] == 1 and m["sent"] == 1 and m["errors"] == 0

    # second run: nothing new, nothing re-sent, no new Gemini call
    n_prompts = len(prompts)
    cdi_main.run()
    assert len(sent) == 2 and len(prompts) == n_prompts


def test_blocked_source_does_not_stop_others(monkeypatch, tmp_path):
    from src.sources.common import SourceBlocked

    def blocked(*a, **k):
        raise SourceBlocked("HTTP 999")

    monkeypatch.setattr(linkedin, "scrape", blocked)
    monkeypatch.setattr(hellowork, "scrape", lambda *a, **k: {})
    monkeypatch.setattr(cdi_main, "STORE_PATH", tmp_path / "s.json")
    monkeypatch.setattr(cdi_main, "STATE_PATH", tmp_path / "st.json")
    monkeypatch.setattr(cdi_main, "METRICS_PATH", tmp_path / "m.jsonl")
    for k, v in {"GEMINI_API_KEY": "k", "TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "1",
                 "USER_DESCRIPTION": "x", "FORCE_RUN": "1", "CDI_SOURCES": "hellowork,linkedin"}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("CDI_USER_DESCRIPTION", raising=False)
    cdi_main.run()
    m = json.loads((tmp_path / "m.jsonl").read_text())
    assert m["blocked"] == ["linkedin"]


def test_should_run_hours():
    from datetime import datetime
    s = {"run_hours": [9, 13, 18]}
    tue9 = datetime(2026, 11, 10, 9, 7, tzinfo=cdi_main.PARIS)
    assert cdi_main.should_run(s, {}, tue9)
    assert not cdi_main.should_run(s, {"last_slot": "2026-11-10T09"}, tue9)
    assert not cdi_main.should_run(s, {}, tue9.replace(hour=10))
    assert not cdi_main.should_run(s, {}, datetime(2026, 11, 14, 9, tzinfo=cdi_main.PARIS))


@pytest.mark.parametrize("text,expected", [
    ("Vous justifiez d'une expérience de 5 ans minimum en développement.", 5),
    ("Expérience : 3 à 5 ans sur un poste similaire", 3),
    ("Expérience demandée : 2 ans", 2),
    ("5+ years of experience in C#", 5),
    ("At least 4 years of professional experience", 4),
    ("Minimum 6 ans d'expérience en gestion de projet", 6),
    ("Une première expérience (stage ou alternance) est appréciée.", None),
    ("Bac+5 école d'ingénieur. Débutant accepté.", None),
    ("Entreprise créée il y a 30 ans. CDI. Expérience bienvenue.", None),
    ("Contrat de 2 ans renouvelable", None),
])
def test_required_years(text, expected):
    from src.cdi_relevance import required_years
    assert required_years(text) == expected


def test_experience_limit_enforced(monkeypatch):
    from src.cdi_relevance import check_offers
    calls = []

    class H:
        def generate(self, prompt):
            calls.append(prompt)
            if prompt.startswith("Rédige"):
                return "lettre"
            # Gemini says yes but reports 5 years: code must override
            if "Mid" in prompt:
                return '{"relevant": true, "years_required": 5, "cv": "informatique", "reason": "ok"}'
            return '{"relevant": true, "years_required": 1, "cv": "projet", "reason": "ok"}'

    offers = {
        "a": {"title": "Dev confirmé", "source": "X", "description": "Expérience de 4 ans minimum.", "relevancy_check": "unchecked"},
        "b": {"title": "Mid dev", "source": "X", "description": "Pas de chiffre.", "relevancy_check": "unchecked"},
        "c": {"title": "Junior PMO", "source": "X", "description": "Expérience : 1 à 2 ans.", "relevancy_check": "unchecked"},
    }
    rel = check_offers(offers, "profil", H(), max_checks=10, max_years=3)
    assert set(rel) == {"c"}
    assert offers["a"]["relevancy_check"] == "not_relevant" and "4 ans" in offers["a"]["reason"]
    assert offers["b"]["relevancy_check"] == "not_relevant"
    # offer "a" never reached Gemini
    assert not any("Dev confirmé" in p for p in calls)


def test_local_windows_mode(monkeypatch, tmp_path):
    """Same env as windows/run_linkedin.bat: LinkedIn only, local files, .env + profile file."""
    root = tmp_path
    (root / ".env").write_text("﻿GEMINI_API_KEY=g\nTELEGRAM_BOT_TOKEN='t'\n# comment\nTELEGRAM_CHAT_ID=\"42\"\n", encoding="utf-8")
    (root / "profile_cdi.txt").write_text("﻿Jeune ingénieur généraliste", encoding="utf-8")
    monkeypatch.setattr(cdi_main, "PROJECT_ROOT", root)
    for k in ("GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "CDI_USER_DESCRIPTION", "USER_DESCRIPTION"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    monkeypatch.setenv("CDI_SOURCES", "linkedin")
    monkeypatch.setenv("CDI_STORE_PATH", r"data\cdi_offers_linkedin.json".replace("\\", "/"))
    monkeypatch.setenv("CDI_STATE_PATH", "data/cdi_state_linkedin.json")
    monkeypatch.setenv("CDI_METRICS_PATH", "logs/cdi_metrics_linkedin.jsonl")
    monkeypatch.setenv("FORCE_RUN", "1")
    for name in ("STORE_PATH", "STATE_PATH", "METRICS_PATH"):
        monkeypatch.setattr(cdi_main, name, getattr(cdi_main, name))  # restored after test

    called = []
    monkeypatch.setattr(hellowork, "scrape", lambda *a, **k: called.append("hw") or {})
    def li_scrape(session, settings, stored, since, today=None):
        called.append("li")
        from src.sources.common import make_offer
        return {"li_1": make_offer("LinkedIn", "Développeur Python junior", "ACME", "Paris",
                                   "https://www.linkedin.com/jobs/view/1/", today, description="Débutant accepté")}
    monkeypatch.setattr(linkedin, "scrape", li_scrape)

    prompts, sent = [], []
    class H:
        def __init__(self, *a, **k): pass
        def generate(self, p):
            prompts.append(p)
            return "lettre" if p.startswith("Rédige") else '{"relevant": true, "years_required": 0, "cv": "informatique", "reason": "ok"}'
    monkeypatch.setattr(cdi_main, "GeminiHandler", H)
    monkeypatch.setattr(cdi_main, "send_message", lambda text, env: sent.append((text, env["TELEGRAM_CHAT_ID"])))
    monkeypatch.setattr(cdi_main.time, "sleep", lambda *_: None)

    cdi_main.run()

    assert called == ["li"]                      # HelloWork not run locally
    assert "Jeune ingénieur généraliste" in prompts[0]  # profile read from profile_cdi.txt
    assert sent[0][1] == "42" and "LinkedIn" in sent[0][0]
    assert (root / "data" / "cdi_offers_linkedin.json").exists()
    assert (root / "logs" / "cdi_metrics_linkedin.jsonl").exists()


def test_sources_selection(monkeypatch):
    s = {"hellowork": {"enabled": True}, "linkedin": {"enabled": False}}
    monkeypatch.delenv("CDI_SOURCES", raising=False)
    assert cdi_main.selected_sources(s) == ["hellowork", "francetravail", "apec"]  # not listed -> enabled
    assert cdi_main.selected_sources({**s, "apec": {"enabled": False}}) == ["hellowork", "francetravail"]  # GitHub
    monkeypatch.setenv("CDI_SOURCES", "linkedin")
    assert cdi_main.selected_sources(s) == ["linkedin"]           # PC
    monkeypatch.setenv("CDI_SOURCES", "linkdin")
    with pytest.raises(ValueError):
        cdi_main.selected_sources(s)


def test_linkedin_keeps_offers_when_detail_pages_are_limited(monkeypatch):
    """A 429 on detail pages must not throw away the offers already read (bug seen on 10/11)."""
    from src.sources.common import SourceBlocked
    cards = "".join(
        f'<div class="base-search-card" data-entity-urn="urn:li:jobPosting:{i}"><h3 class="base-search-card__title">Dev {i}</h3>'
        f'<h4 class="base-search-card__subtitle">C{i}</h4><time datetime="2026-11-10"></time></div>' for i in range(1, 6))
    calls = {"detail": 0}

    def fake_get(session, url, params=None):
        if url == linkedin.SEARCH_URL:
            return cards
        calls["detail"] += 1
        if calls["detail"] > 2:
            raise SourceBlocked("HTTP 429")
        return LI_DETAIL

    monkeypatch.setattr(linkedin, "get_html", lambda *a, **k: (_ for _ in ()).throw(AssertionError("use patient")))
    monkeypatch.setattr(linkedin, "get_html_patient", fake_get)
    monkeypatch.setattr(linkedin, "polite_sleep", lambda *a, **k: None)
    settings = {"keywords": ["dev"], "excluded_title_words": [],
                "linkedin": {"geo_id": "1", "max_details_per_run": 40}}
    offers = linkedin.scrape(None, settings, set(), date(2026, 11, 1), today=TODAY)
    assert sorted(offers) == ["li_1", "li_2"]          # kept, the 3 others wait for the next run
    assert "Nous cherchons" in offers["li_1"]["description"]

    calls["detail"] = -100                               # no more limit
    settings["linkedin"]["max_details_per_run"] = 3
    offers = linkedin.scrape(None, settings, {"li_1", "li_2"}, date(2026, 11, 1), today=TODAY)
    assert sorted(offers) == ["li_3", "li_4", "li_5"]


def test_patient_get_retries_once(monkeypatch):
    from src.sources import common
    seq = [common.SourceBlocked("429"), "<html>ok</html>"]

    def fake(session, url, params=None):
        v = seq.pop(0)
        if isinstance(v, Exception):
            raise v
        return v

    monkeypatch.setattr(common, "get_html", fake)
    monkeypatch.setattr(common.time, "sleep", lambda s: None)
    assert common.get_html_patient(None, "u") == "<html>ok</html>"



def test_scores_and_low_score_rejected():
    from src.cdi_relevance import check_offers, parse_score

    class H:
        def generate(self, prompt):
            if prompt.startswith("Rédige"):
                return "lettre"
            if "Bon poste" in prompt:
                return '{"relevant": true, "score": 8, "years_required": 0, "cv": "projet", "reason": "Très proche"}'
            return '{"relevant": true, "score": 4, "years_required": 0, "cv": "projet", "reason": "Peu adapté"}'

    offers = {"a": {"title": "Bon poste", "source": "X", "description": "", "relevancy_check": "unchecked"},
              "b": {"title": "Poste moyen", "source": "X", "description": "", "relevancy_check": "unchecked"}}
    rel = check_offers(offers, "profil", H(), max_checks=10)
    assert set(rel) == {"a"} and offers["a"]["score"] == 8
    assert offers["b"]["score"] == 4 and offers["b"]["relevancy_check"] == "not_relevant"
    assert parse_score('{"score": "7,6"}') == 8 and parse_score("YES") is None


def test_telegram_off_by_default(monkeypatch):
    from src import telegram
    monkeypatch.delenv("TELEGRAM_ENABLED", raising=False)
    assert telegram.enabled() is False
    monkeypatch.setenv("TELEGRAM_ENABLED", "true")
    assert telegram.enabled() is True
