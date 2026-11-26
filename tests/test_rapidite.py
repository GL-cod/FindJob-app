"""The app must stay fast: offer files are parsed once per version, only the open tab and the open
offer cards are drawn, and the window reloads itself after a restart (watchdog)."""
import json
import os
import time

from src import tracking
from test_ouverture_rapide import app_copy  # noqa: F401  (fixture)


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))   # a distinct version, even within 1 ms


def test_offer_files_parsed_once_per_version(tmp_path, monkeypatch):
    cdi, vie = tmp_path / "cdi.json", tmp_path / "vie.json"
    _write(cdi, {"hw_1": {"source": "HelloWork", "title": "PMO", "company": "A", "posted": "2026-11-09"}})
    _write(vie, {"1": {"missionTitle": "Dev", "organizationName": "B", "missionDescription": "Développer"}})
    calls = []
    real = tracking._read_json
    monkeypatch.setattr(tracking, "_read_json", lambda p, d: calls.append(str(p)) or real(p, d))

    first = tracking.load_offers((cdi,), suivi={}, vie_path=vie, scores_path=tmp_path / "none.json")
    first[0]["status"] = "changé par la page"          # the page writes on its copies
    again = tracking.load_offers((cdi,), suivi={}, vie_path=vie, scores_path=tmp_path / "none.json")
    assert calls.count(str(cdi)) == 1 and calls.count(str(vie)) == 1     # not parsed again
    assert all(o["status"] == "À regarder" for o in again)               # copies: no leak between runs

    _write(cdi, {"hw_2": {"source": "HelloWork", "title": "Dev", "company": "C", "posted": "2026-11-10"}})
    later = tracking.load_offers((cdi,), suivi={}, vie_path=vie, scores_path=tmp_path / "none.json")
    assert calls.count(str(cdi)) == 2 and {o["id"] for o in later} == {"hw_2", "vie_1"}


def test_tail_reads_only_the_end(tmp_path):
    log = tmp_path / "linkedin.log"
    log.write_text("".join(f"ligne {i}\n" for i in range(50_000)), encoding="utf-8")
    out = tracking.tail(log, 3, max_bytes=200)
    assert out == "ligne 49997\nligne 49998\nligne 49999"
    assert tracking.tail(tmp_path / "absent.log") == ""


def test_only_open_tab_and_cards_are_drawn(app_copy, monkeypatch):  # noqa: F811
    from streamlit.testing.v1 import AppTest
    data = app_copy / "data"
    for name in ("GITHUB_STORE", "LOCAL_STORE", "VIE_STORE"):        # the copy's stores, not the repo's
        monkeypatch.setattr(tracking, name, data / getattr(tracking, name).name)
    (data / "offers.json").write_text("{}", encoding="utf-8")
    offers = {f"hw_{i}": {"source": "HelloWork", "title": f"Développeur {i}", "company": f"E{i}",
                          "url": f"https://www.hellowork.com/fr-fr/emplois/{i}.html", "posted": "2026-11-20",
                          "relevancy_check": "relevant", "score": 7, "reason": "ok", "cv": "informatique"}
              for i in range(30)}
    (data / "cdi_offers.json").write_text(json.dumps(offers), encoding="utf-8")
    (data / "filtres_offres.json").write_text(json.dumps(
        {"flt_sources": ["HelloWork"], "flt_statuses": ["À regarder"], "flt_sort": "Meilleure note d'abord",
         "flt_old": False}), encoding="utf-8")

    at = AppTest.from_file(str(app_copy / "app" / "dashboard.py"), default_timeout=60)
    at.run()
    assert not at.exception
    assert at.session_state["onglet"] == "📋 Offres"
    assert len(at.expander) >= 25
    assert not any(b.label.startswith("Générer la lettre") for b in at.button)   # closed cards: no content
    # older saved filters (no "known_sources"): the new sources Adecco and CRIT are added
    assert at.session_state["flt_sources"] == ["HelloWork", "Adecco", "CRIT"]

    at.session_state["carte_hw_3"] = True                  # open one card
    at.run()
    assert not at.exception
    assert any(m.value.startswith("📍") for m in at.markdown)

    at.session_state["onglet"] = "⚙️ Activité"            # other tab: the offers are not drawn
    at.run()
    assert not at.exception and len(at.expander) < 5
    assert any("Historique des passages" in s.value for s in at.subheader)

    at.session_state["onglet"] = "📋 Offres"              # back: the filters are still there
    at.run()
    assert not at.exception
    assert at.session_state["flt_sources"] == ["HelloWork", "Adecco", "CRIT"]
    assert at.session_state["flt_statuses"] == ["À regarder"]

    start = time.time()
    for _ in range(3):
        at.run()
    assert (time.time() - start) / 3 < 2.0


def test_watchdog_is_in_the_page(app_copy):  # noqa: F811
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(app_copy / "app" / "dashboard.py"), default_timeout=60)
    at.run()
    html = [h.proto.body for h in at.get("html")]
    assert any("__mesCandidaturesWatchdog" in h and "/_stcore/health" in h for h in html)
