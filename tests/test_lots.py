import json

from src import cdi_relevance


def offer(i, desc="Support utilisateurs, Windows.", **kw):
    return {"source": "HelloWork", "title": f"Poste {i}", "company": f"E{i}", "location": "Paris - 75",
            "posted": f"2026-11-{10 + i:02d}", "description": desc, "relevancy_check": "unchecked", **kw}


class BatchHandler:
    """Answers a batch with one verdict per offer (relevant when the title number is even)."""

    def __init__(self, drop=(), fail_batches=False):
        self.prompts, self.drop, self.fail = [], set(drop), fail_batches

    def generate(self, prompt):
        self.prompts.append(prompt)
        if prompt.startswith("Rédige"):
            return "Madame, Monsieur, ..."
        titles = [line.split(": ", 1)[1] for line in prompt.splitlines() if line.startswith("Intitulé :")]
        if "=== OFFRE O1 ===" in prompt:
            if self.fail:
                raise TimeoutError("read timed out")
            items = [{"offre": f"O{k + 1}", "relevant": int(t.split()[-1]) % 2 == 0, "score": 7,
                      "years_required": 0, "cv": "informatique", "reason": f"verdict {t}"}
                     for k, t in enumerate(titles) if t not in self.drop]
            return "```json\n" + json.dumps(items, ensure_ascii=False) + "\n```"
        t = titles[0]
        return json.dumps({"relevant": int(t.split()[-1]) % 2 == 0, "score": 6, "years_required": 0,
                           "cv": "informatique", "reason": f"seul {t}"})


def test_batches_of_ten():
    offers = {f"hw_{i}": offer(i) for i in range(1, 24)}
    h = BatchHandler()
    relevant = cdi_relevance.check_offers(offers, "profil", h, max_checks=100, batch_size=10)
    judge_prompts = [p for p in h.prompts if not p.startswith("Rédige")]
    assert len(judge_prompts) == 3                     # 10 + 10 + 3 offers
    assert all(o["relevancy_check"] in ("relevant", "not_relevant") for o in offers.values())
    assert set(relevant) == {f"hw_{i}" for i in range(2, 24, 2)}
    assert offers["hw_4"]["reason"] == "verdict Poste 4" and offers["hw_4"]["score"] == 7
    assert offers["hw_4"]["letter"].startswith("Madame")   # letters still written one by one


def test_missing_offer_judged_alone_and_failed_batch_falls_back():
    offers = {f"hw_{i}": offer(i) for i in range(1, 6)}
    h = BatchHandler(drop={"Poste 3"})
    cdi_relevance.check_offers(offers, "profil", h, max_checks=100, batch_size=10, draft_letters=False)
    assert offers["hw_3"]["reason"] == "seul Poste 3" and offers["hw_2"]["reason"] == "verdict Poste 2"

    offers = {f"hw_{i}": offer(i) for i in range(1, 4)}
    h = BatchHandler(fail_batches=True)
    cdi_relevance.check_offers(offers, "profil", h, max_checks=100, batch_size=10, draft_letters=False)
    assert all(o["reason"].startswith("seul") for o in offers.values())


def test_max_checks_counts_offers_and_description_fetched_only_when_judged():
    offers = {f"hw_{i}": offer(i, desc="") for i in range(1, 31)}
    asked = []

    def describe(o):
        asked.append(o["title"])
        if o["title"] == "Poste 29":
            return False                                  # removed from the site
        if o["title"] == "Poste 28":
            return None                                   # site unreachable now
        o["description"] = "Expérience : 5 ans minimum." if o["title"] == "Poste 27" else "Débutant accepté."
        return True

    h = BatchHandler()
    cdi_relevance.check_offers(offers, "profil", h, max_checks=12, batch_size=10, draft_letters=False,
                               describe=describe)
    judged = [o for o in offers.values() if o["relevancy_check"] in ("relevant", "not_relevant")
              and o["reason"].startswith("verdict")]
    assert len(judged) == 12
    assert offers["hw_29"]["reason"] == "Offre retirée du site"
    assert offers["hw_28"]["relevancy_check"] == "unchecked"
    assert offers["hw_27"]["reason"] == "5 ans d'expérience exigés"            # filtered without Gemini
    assert len(asked) == 15                                                    # not the 30 offers
    assert sum(o["relevancy_check"] == "unchecked" for o in offers.values()) == 30 - 15 + 1


def test_batch_prompt_and_parse():
    p = cdi_relevance.batch_relevance_prompt([("O1", offer(1)), ("O2", offer(2, desc="x" * 9000))], "PROFIL")
    assert "=== OFFRE O1 ===" in p and "=== OFFRE O2 ===" in p and "PROFIL" in p
    assert "x" * cdi_relevance.BATCH_DESC_CHARS in p and "x" * (cdi_relevance.BATCH_DESC_CHARS + 1) not in p
    got = cdi_relevance.parse_batch('Voici :\n[{"offre": "O1", "relevant": "oui", "score": "8", '
                                    '"years_required": 1, "cv": "informatique", "reason": "bien"}]')
    assert got["O1"][0] is True and got["O1"][2] == "bien" and got["O1"][4] == 8
    assert cdi_relevance.parse_batch("pas de json") == {}


def test_hellowork_reads_offer_pages_only_when_judging(monkeypatch):
    from datetime import date
    from src.sources import hellowork
    from test_tri_date_priorite import page

    calls = []

    def get(session, url, params=None):
        calls.append(url)
        if url == hellowork.SEARCH_URL:
            return page(range(1, 4)) if params["p"] == 1 else "<html></html>"
        return ('<html><script type="application/ld+json">{"@type": "JobPosting", "description": '
                '"<p>Support N1</p>", "datePosted": "2026-11-24T08:00:00Z", '
                '"experienceRequirements": {"monthsOfExperience": 12}}</script></html>')

    monkeypatch.setattr(hellowork, "get_html", get)
    monkeypatch.setattr(hellowork, "get_html_patient", get)
    monkeypatch.setattr(hellowork, "polite_sleep", lambda *a, **k: None)
    settings = {"keywords": ["technicien"], "excluded_title_words": [], "hellowork": {"pages_per_keyword": 3}}
    offers = hellowork.scrape(None, settings, set(), date(2026, 11, 5), today=date(2026, 11, 26))
    assert len(offers) == 3 and all(u == hellowork.SEARCH_URL for u in calls)   # no offer page opened
    o = offers["hw_1"]
    assert o["description"] == "" and o["relevancy_check"] == "unchecked"
    assert hellowork.fill_details(None, o) is True
    assert "Support N1" in o["description"] and o["posted"] == "2026-11-24"
    monkeypatch.setattr(hellowork, "get_html_patient", lambda *a, **k: None)
    assert hellowork.fill_details(None, {"url": "x"}) is False


def test_describer(monkeypatch):
    from src import cdi_main
    from src.sources import common, crit, hellowork

    monkeypatch.setattr(hellowork, "fill_details", lambda s, o: o.update(description="ok") or True)
    monkeypatch.setattr(crit, "fetch_description", lambda s, url: "")

    def blocked(s, url):
        raise common.SourceBlocked("403")

    monkeypatch.setattr(cdi_main.adecco, "fetch_description", blocked)
    d = cdi_main.describer(None)
    hw = {"source": "HelloWork", "url": "u"}
    assert d(hw) is True and hw["description"] == "ok"
    assert d({"source": "CRIT", "url": "u"}) is False
    assert d({"source": "Adecco", "url": "u"}) is None and d({"source": "Adecco", "url": "v"}) is None
    assert d({"source": "LinkedIn", "url": "u"}) is True
