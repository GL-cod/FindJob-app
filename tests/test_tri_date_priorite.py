from datetime import date

from src import cdi_relevance
from src.sources import hellowork

TODAY = date(2026, 11, 26)
SINCE = date(2026, 11, 5)


def page(ids, age="il y a 1 jour"):
    cards = "".join(
        f'<li data-id-storage-item-id="{i}"><input name="title" value="Technicien informatique {i}">'
        f'<input name="company" value="E{i}"><span data-cy="localisationCard">Paris - 75</span>'
        f'<span data-cy="contractCard">CDI</span><span>{age}</span></li>' for i in ids)
    return f"<html><body><ul>{cards}</ul></body></html>"


def test_hellowork_sorted_by_date_reads_pages_until_nothing_new(monkeypatch):
    pages = {1: page(range(1, 31)), 2: page(range(31, 61)), 3: page(range(61, 91)), 4: page(range(91, 121))}
    calls = []

    def get(session, url, params=None):
        if url == hellowork.SEARCH_URL:
            calls.append(dict(params))
            return pages.get(params["p"], "<html></html>")
        return None                                   # offer pages: not needed here

    monkeypatch.setattr(hellowork, "get_html", get)
    monkeypatch.setattr(hellowork, "get_html_patient", get)
    monkeypatch.setattr(hellowork, "polite_sleep", lambda *a, **k: None)
    settings = {"keywords": ["technicien informatique"], "excluded_title_words": [],
                "contrats": ["CDI", "CDD", "interim"], "hellowork": {"pages_per_keyword": 8, "tri": "date"}}
    known = {f"hw_{i}" for i in range(61, 121)}       # page 3 onwards: already seen at the last run
    offers = hellowork.scrape(None, settings, known, SINCE, today=TODAY)
    assert set(offers) == {f"hw_{i}" for i in range(1, 61)}
    assert [c["p"] for c in calls] == [1, 2, 3]       # page 3 had nothing new: stop there
    assert all(c["st"] == "date" for c in calls)
    assert calls[0]["c"] == ["CDI", "CDD", "Travail_temp"]

    calls.clear()                                     # old setting: relevance, fixed number of pages
    settings["hellowork"] = {"pages_per_keyword": 2, "tri": "pertinence"}
    hellowork.scrape(None, settings, set(), SINCE, today=TODAY)
    assert [c["p"] for c in calls] == [1, 2] and "st" not in calls[0]


IDF = ["Île-de-France", 75, 77, 78, 91, 92, 93, 94, 95, "Essonne", "Hauts-de-Seine"]


def test_priority_places():
    yes = ["Paris - 75", "Le Plessis-Robinson - 92", "Neuilly-sur-Seine (92200)", "Massy, Essonne",
           "Paris, Île-de-France, France", "Lieusaint, Seine-Et-Marne (77)"]
    no = ["Lyon - 69", "Marseille 13075", "Lille (59000)", "Cormeilles-en-Parisis-sur-Loire", ""]
    assert all(cdi_relevance.in_priority_places(x, IDF) for x in yes)
    assert not any(cdi_relevance.in_priority_places(x, IDF) for x in no)


class FakeHandler:
    def __init__(self):
        self.seen = []

    def generate(self, prompt):
        self.seen.append(next(line for line in prompt.splitlines() if line.startswith("Intitulé :")))
        return '{"relevant": false, "score": 3, "years_required": 0, "cv": "informatique", "reason": "non"}'


def test_gemini_judges_priority_places_then_newest_first():
    offers = {
        "a": {"title": "Lyon ancien", "location": "Lyon - 69", "posted": "2026-11-10", "relevancy_check": "unchecked"},
        "b": {"title": "Lyon récent", "location": "Lyon - 69", "posted": "2026-11-25", "relevancy_check": "unchecked"},
        "c": {"title": "Paris ancien", "location": "Paris - 75", "posted": "2026-11-09", "relevancy_check": "unchecked"},
        "d": {"title": "Massy récent", "location": "Massy, Essonne", "posted": "2026-11-24",
              "relevancy_check": "unchecked"},
        "e": {"title": "Déjà jugée", "location": "Paris - 75", "posted": "2026-11-26", "relevancy_check": "relevant"},
    }
    for o in offers.values():
        o.update(company="X", source="HelloWork", description="")
    h = FakeHandler()
    cdi_relevance.check_offers(offers, "profil", h, max_checks=3, draft_letters=False, priority_places=IDF,
                                batch_size=1)
    assert h.seen == ["Intitulé : Massy récent", "Intitulé : Paris ancien", "Intitulé : Lyon récent"]
    assert offers["a"]["relevancy_check"] == "unchecked"          # waits for the next run


def test_sites_take_turns_inside_each_group():
    offers = {}
    for i in range(5):
        offers[f"hw_{i}"] = {"source": "HelloWork", "location": "Paris - 75", "posted": f"2026-11-2{i}",
                             "relevancy_check": "unchecked"}
    offers["ad_1"] = {"source": "Adecco", "location": "Massy, Essonne", "posted": "2026-11-10", "relevancy_check": "unchecked"}
    offers["crit_1"] = {"source": "CRIT", "location": "Neuilly-sur-Seine (92200)", "posted": "2026-11-12",
                        "relevancy_check": "unchecked"}
    offers["crit_2"] = {"source": "CRIT", "location": "Lyon (69003)", "posted": "2026-11-26", "relevancy_check": "unchecked"}
    order = cdi_relevance.judging_order(offers, IDF)
    assert order[:3] == ["hw_4", "crit_1", "ad_1"]        # each site gets a turn, newest site first
    assert order[3:6] == ["hw_3", "hw_2", "hw_1"]
    assert order[-1] == "crit_2"                          # outside the priority places: last
