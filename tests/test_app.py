import json

import pytest

FULL_LETTER = "Madame, Monsieur,\n\n" + "Texte de la lettre. " * 40 + "\n\nCordialement,\nCamille Martin"

from src import sheets, tracking


@pytest.fixture
def stores(tmp_path):
    cdi = {"hw_1": {"source": "HelloWork", "title": "PMO Junior", "company": "A", "url": "https://www.hellowork.com/fr-fr/emplois/1.html",
                    "posted": "2026-11-09", "relevancy_check": "relevant", "cv": "projet", "reason": "ok"},
           "hw_2": {"source": "HelloWork", "title": "Comptable", "company": "B", "url": "u2", "posted": "2026-11-08",
                    "relevancy_check": "not_relevant"}}
    li = {"li_9": {"source": "LinkedIn", "title": "Dev Python", "company": "C", "url": "https://www.linkedin.com/jobs/view/9",
                   "posted": "2026-11-10", "relevancy_check": "relevant", "cv": "informatique"}}
    vie = {"248161": {"organizationName": "LEHMANN", "missionTitle": "Business Developer", "cityName": "MIAMI        -FL-",
                      "countryName": "ETATS-UNIS", "missionDescription": "Desc", "missionProfile": "Profil",
                      "startBroadcastDate": "2026-11-07", "relevancy_check": "relevant"}}
    paths = {}
    for name, data in (("cdi", cdi), ("li", li), ("vie", vie)):
        p = tmp_path / f"{name}.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        paths[name] = p
    return paths


def test_load_merge_and_vie(stores, tmp_path):
    offers = tracking.load_offers((stores["cdi"], stores["li"]), suivi={}, vie_path=stores["vie"])
    ids = [o["id"] for o in offers]
    assert ids == ["li_9", "hw_1", "hw_2", "vie_248161"]        # newest first
    v = offers[-1]
    assert v["source"] == "VIE" and v["location"] == "MIAMI -FL-, Etats-Unis"
    assert v["url"] == "https://mon-vie-via.businessfrance.fr/offres/248161"
    assert "Desc" in v["description"] and "Profil" in v["description"]
    assert all(o["status"] == "À regarder" for o in offers)


def test_suivi_snapshot_survives_expiry(stores, tmp_path):
    suivi_path = tmp_path / "suivi.json"
    offers = tracking.load_offers((stores["cdi"],), suivi={}, vie_path=tmp_path / "none.json")
    suivi = {}
    tracking.update_suivi(suivi, offers[0], status="Candidaté", note="Relancer lundi")
    tracking.save_suivi(suivi, suivi_path)
    # the offer disappears from the stores (older than max_days) but stays in the app
    later = tracking.load_offers((tmp_path / "empty.json",), suivi=tracking.load_suivi(suivi_path),
                                 vie_path=tmp_path / "none.json")
    assert len(later) == 1 and later[0]["id"] == "hw_1" and later[0]["expired"]
    assert later[0]["status"] == "Candidaté" and later[0]["note"] == "Relancer lundi"
    assert later[0]["title"] == "PMO Junior"


def test_metrics_rows(tmp_path):
    p = tmp_path / "m.jsonl"
    p.write_text('{"timestamp": "2026-11-10T12:56:27+01:00", "new": {"hellowork": 193, "linkedin": 0}, "blocked": ["linkedin"], "relevant": 36, "sent": 36, "errors": 0, "total_time": 1199.6}\n'
                 '{"timestamp": "2026-11-10T12:07:49+01:00", "scraped": 400, "new": 7, "relevant": 1, "errors": 0, "total_time": 27.0}\nnot json\n')
    rows = tracking.read_metrics(p, "X")
    assert rows[0]["Nouvelles offres"] == 193 and rows[0]["Bloqué"] == "linkedin"
    assert rows[1]["Nouvelles offres"] == 7 and rows[1]["Envoyées"] == 1


def test_letter_uses_stored_description_for_vie(stores, tmp_path):
    offers = tracking.load_offers((), suivi={}, vie_path=stores["vie"])
    prompts = []

    class H:
        def generate(self, p):
            prompts.append(p)
            return "  " + FULL_LETTER + "  "

    assert tracking.generate_letter(offers[0], H(), "profil") == FULL_LETTER
    assert "Desc" in prompts[0] and "Contrat : VIE" in prompts[0]


class FakeResp:
    def __init__(self, data): self.data = data
    def raise_for_status(self): pass
    def json(self): return self.data


def test_sheets_push_mapping(monkeypatch):
    monkeypatch.setenv("SHEETS_WEBAPP_URL", "https://script.google.com/macros/s/X/exec")
    monkeypatch.setenv("SHEETS_TOKEN", "secret")
    sent = []
    monkeypatch.setattr(sheets.requests, "post", lambda url, json, timeout: sent.append(json) or FakeResp({"ok": True, "created": True, "row": 80}))
    offer = {"url": "https://www.linkedin.com/jobs/view/9", "title": "Dev Python", "company": "C"}
    assert sheets.push(offer, "À regarder") is None and not sent           # not synced
    assert sheets.push(offer, "Candidaté", note="n")["created"]
    assert sent[0]["retour"] == "En attente" and sent[0]["poste"] == "Dev Python" and sent[0]["token"] == "secret"
    sheets.push(offer, "Entretien"); sheets.push(offer, "Refusé")
    assert [p["retour"] for p in sent[1:]] == ["Positif", "Negatif"]


def test_sheets_fetch_and_norm(monkeypatch):
    monkeypatch.setenv("SHEETS_WEBAPP_URL", "u"); monkeypatch.setenv("SHEETS_TOKEN", "t")
    monkeypatch.setattr(sheets.requests, "get", lambda url, params, timeout: FakeResp({"ok": False, "error": "token"}))
    with pytest.raises(RuntimeError):
        sheets.fetch_rows()
    assert sheets.norm_link("https://www.LinkedIn.com/jobs/view/4360772575/?trk=x") == "https://www.linkedin.com/jobs/view/4360772575"


def test_vie_cv_and_english_letter(tmp_path):
    from src.lang import guess_lang
    assert guess_lang("We are looking for an engineer to join our team. You will work on the platform.") == "en"
    assert guess_lang("Nous recherchons un ingénieur pour rejoindre notre équipe.") == "fr"
    assert guess_lang("") == "fr"
    vie = {"1": {"missionTitle": "Software Engineer", "missionDescription": "You will join the team and work on the product with our engineers.",
                 "organizationName": "X", "startBroadcastDate": "2026-11-10", "relevancy_check": "relevant"},
           "2": {"missionTitle": "Ingénieur logiciel", "missionDescription": "Vous rejoindrez l'équipe pour développer le produit avec nous.",
                 "organizationName": "Y", "startBroadcastDate": "2026-11-09", "relevancy_check": "relevant"}}
    p = tmp_path / "vie.json"
    p.write_text(json.dumps(vie), encoding="utf-8")
    offers = {o["id"]: o for o in tracking.load_offers((), suivi={}, vie_path=p)}
    assert offers["vie_1"]["cv"] == "vie_en" and offers["vie_2"]["cv"] == "vie_fr"
    prompts = []

    class H:
        def generate(self, prompt):
            prompts.append(prompt)
            return FULL_LETTER

    tracking.generate_letter(offers["vie_1"], H(), "profil")
    tracking.generate_letter(offers["vie_2"], H(), "profil")
    assert prompts[0].startswith("Write in English") and "Dear Hiring Manager" in prompts[0]
    assert prompts[1].startswith("Rédige en français")


def test_vie_telegram_message_has_cv():
    from src.telegram import format_offer
    msg = format_offer("9", {"missionTitle": "Data Engineer", "organizationName": "Z", "cityName": "Berlin",
                             "countryName": "ALLEMAGNE", "startBroadcastDate": "2026-11-10",
                             "missionDescription": "You will build data pipelines with the team and our partners."})
    assert "CV VIE en anglais" in msg and msg.endswith("/offres/9")


def test_sheet_summary_and_status_sync():
    from datetime import date
    rows = [{"retour": "En attente", "date": "10/11/2026"}, {"retour": "Negatif", "date": "09/11/2026"},
            {"retour": "Positif", "date": "23/01/2026"}, {"retour": "", "date": ""}, {"retour": "Négatif", "date": "bad"}]
    s = sheets.summary(rows, today=date(2026, 11, 10))
    assert (s["total"], s["en_attente"], s["positif"], s["negatif"], s["sans_retour"], s["cette_semaine"]) == (5, 1, 1, 2, 1, 2)
    assert s["par_semaine"][date(2026, 11, 9)] == 2
    # the sheet's answer wins over "waiting" statuses, not over what the user decided
    assert sheets.merged_status("À regarder", "En attente") == "Candidaté"
    assert sheets.merged_status("À regarder", "Positif") == "Entretien"
    assert sheets.merged_status("Candidaté", "Negatif") == "Refusé"
    assert sheets.merged_status("Candidaté", "En attente") == "Candidaté"
    assert sheets.merged_status("Pas intéressé", "Positif") == "Pas intéressé"


def test_fetch_sheet_old_and_new_script(monkeypatch):
    monkeypatch.setenv("SHEETS_WEBAPP_URL", "u"); monkeypatch.setenv("SHEETS_TOKEN", "t")
    monkeypatch.setattr(sheets.requests, "get", lambda url, params, timeout: FakeResp({"ok": True, "rows": [{"lien": "x"}]}))
    old = sheets.fetch_sheet()
    assert old["version"] == 1 and old["sheet_url"] == "" and old["rows"] == [{"lien": "x"}]
    monkeypatch.setattr(sheets.requests, "get", lambda url, params, timeout: FakeResp(
        {"ok": True, "version": 2, "sheet_url": "https://docs.google.com/x", "rows": []}))
    assert sheets.fetch_sheet()["version"] == 2


def test_sheet_editor_diff_from_dataframe():
    import pandas as pd
    before = [{"_row": 2, "N": "1", "Poste": "PMO", "Entreprise": "A", "Date": "23/01/2026", "Retour": "En attente",
               "Lien": "", "Commentaire": ""},
              {"_row": 3, "N": "2", "Poste": "Dev", "Entreprise": "B", "Date": "", "Retour": "", "Lien": "u", "Commentaire": ""}]
    df = pd.DataFrame(before)
    df.loc[0, "Retour"] = "Positif"
    df.loc[0, "Commentaire"] = "Entretien lundi"
    df.loc[1, "Lien"] = None                                  # cleared cell comes back as NaN/None
    after = df.fillna("").to_dict("records")
    changes = sheets.diff_rows(before, after)
    assert changes == [(2, "PMO", {"retour": "Positif", "commentaire": "Entretien lundi"}), (3, "Dev", {"url": ""})]
    assert sheets.diff_rows(before, pd.DataFrame(before).fillna("").to_dict("records")) == []


def test_update_row_refused_when_row_moved(monkeypatch):
    monkeypatch.setenv("SHEETS_WEBAPP_URL", "u"); monkeypatch.setenv("SHEETS_TOKEN", "t")
    monkeypatch.setattr(sheets.requests, "post", lambda url, json, timeout: FakeResp({"ok": False, "error": "row_changed"}))
    with pytest.raises(RuntimeError, match="a bougé"):
        sheets.update_row(5, "PMO", {"retour": "Positif"})


def test_row_style_colours():
    assert "d9ead3" in sheets.row_style({"Retour": "Positif", "N": "1"})[0]
    assert "f4cccc" in sheets.row_style({"Retour": "Negatif "})[0]
    assert "fff2cc" in sheets.row_style({"Retour": "En attente "})[0]
    assert sheets.row_style({"Retour": "", "N": "1"}) == ["", ""]


def test_feedback_store_and_prompts(tmp_path, monkeypatch):
    from src import feedback, relevance, cdi_relevance
    path = tmp_path / "fb.json"
    monkeypatch.setattr(feedback, "FEEDBACK_PATH", path)
    assert feedback.prompt_block() == ""
    feedback.record({"id": "hw_1", "source": "HelloWork", "title": "Business Developer", "company": "A"}, "trop commercial")
    feedback.record({"id": "li_2", "source": "LinkedIn", "title": "Technicien support N1", "company": "B"})
    feedback.record({"id": "hw_1", "source": "HelloWork", "title": "Business Developer", "company": "A"}, "trop commercial, pas technique")
    entries = feedback.load()
    assert [e["id"] for e in entries] == ["li_2", "hw_1"] and entries[1]["reason"] == "trop commercial, pas technique"
    block = feedback.prompt_block()
    assert "Business Developer (A) : trop commercial, pas technique" in block and "Technicien support N1 (B)\n" in block

    # CDI prompt carries it
    p = cdi_relevance.relevance_prompt({"title": "x"}, "profil", 3, [], block)
    assert "déjà refusées" in p and "trop commercial" in p
    # VIE prompt carries it (English header)
    seen = []

    class H:
        def generate(self, prompt):
            seen.append(prompt)
            return "NO"
    relevance.is_relevant({"missionTitle": "Sales"}, H(), {"USER_PROFILE": "p"})
    assert "already turned down" in seen[0] and "trop commercial" in seen[0]

    feedback.forget("hw_1")
    assert [e["id"] for e in feedback.load()] == ["li_2"]


def test_gitsync_pushes_feedback(tmp_path):
    """Feedback commit goes to the remote, even when the remote moved on meanwhile."""
    import subprocess
    from src import gitsync

    def run(cwd, *a):
        subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)

    remote, pc, actions = tmp_path / "remote.git", tmp_path / "pc", tmp_path / "actions"
    run(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    run(tmp_path, "clone", "-q", str(remote), str(actions))
    for k, v in (("user.name", "bot"), ("user.email", "b@x")):
        run(actions, "config", k, v)
    (actions / "data").mkdir()
    (actions / "data" / "feedback.json").write_text("[]\n")
    (actions / "data" / "offers.json").write_text("{}\n")
    run(actions, "add", "."); run(actions, "commit", "-qm", "init"); run(actions, "push", "-q", "origin", "HEAD:main")
    run(tmp_path, "clone", "-q", str(remote), str(pc))

    # GitHub Actions commits something meanwhile
    (actions / "data" / "offers.json").write_text('{"1": {}}\n')
    run(actions, "commit", "-qam", "store"); run(actions, "push", "-q", "origin", "HEAD:main")

    # the app records a rejection on the PC and pushes it
    (pc / "data" / "feedback.json").write_text('[{"id": "hw_1", "reason": "trop commercial"}]\n')
    ok, out = gitsync.push_file(pc, "data/feedback.json", "Update feedback")
    assert ok, out
    run(actions, "pull", "-q", "--rebase", "origin", "main")
    assert "trop commercial" in (actions / "data" / "feedback.json").read_text()
    assert (actions / "data" / "offers.json").read_text() == '{"1": {}}\n'
    # nothing new to push: still fine
    assert gitsync.push_file(pc, "data/feedback.json", "Update feedback")[0]


def test_mark_seen_keeps_first_day(tmp_path):
    from datetime import date
    p = tmp_path / "seen.json"
    s1 = tracking.mark_seen(["a", "b"], path=p, today=date(2026, 11, 10))
    s2 = tracking.mark_seen(["a", "c"], path=p, today=date(2026, 11, 20))
    assert s1 == {"a": "2026-11-10", "b": "2026-11-10"}
    assert s2 == {"a": "2026-11-10", "b": "2026-11-10", "c": "2026-11-20"}


def test_auto_refresh_only_when_something_changed():
    state, calls = {}, []
    sigs = iter(["A", "A", "B", "B"])
    tick = lambda: tracking.check_for_updates(state, signature=lambda: next(sigs),
                                              pull=lambda: calls.append("pull"), clear=lambda: calls.append("clear"),
                                              now=lambda: "2026-11-10 19:15")
    assert tick() is False and calls == []                  # first draw: nothing fetched
    assert tick() is False and calls == ["pull", "clear"]   # 15 min later, nothing new: no reload
    assert tick() is True                                   # new data: reload
    assert tick() is False                                  # same again: no reload
    assert state["last_auto_check"] == "19:15"


def test_reloader_picks_up_new_code(tmp_path, monkeypatch):
    import importlib, sys, time
    pkg = tmp_path / "src"
    (pkg).mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "tracking.py").write_text("def old():\n    return 1\n")
    for name in [n for n in list(sys.modules) if n == "src" or n.startswith("src.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.syspath_prepend(str(tmp_path))
    spec = importlib.util.spec_from_file_location("real_reloader", str(__import__("pathlib").Path(__file__).parent.parent / "src" / "reloader.py"))
    rl = importlib.util.module_from_spec(spec); spec.loader.exec_module(rl)
    import src.tracking as t
    assert rl.reload_if_changed(pkg) is False                     # first call: just remembers
    time.sleep(0.01)
    (pkg / "tracking.py").write_text("def old():\n    return 1\n\ndef check_for_updates():\n    return 'new'\n")
    import os; st_ = os.stat(pkg / "tracking.py"); os.utime(pkg / "tracking.py", ns=(st_.st_atime_ns, st_.st_mtime_ns + 10**9))
    assert rl.reload_if_changed(pkg) is True
    assert sys.modules["src.tracking"].check_for_updates() == "new"


def test_removed_status_maps_to_candidate(tmp_path):
    import json
    store = tmp_path / "s.json"
    store.write_text(json.dumps({"hw_1": {"source": "HelloWork", "title": "PMO", "relevancy_check": "relevant"}}))
    offers = tracking.load_offers((store,), suivi={"hw_1": {"status": "Relance à faire"}}, vie_path=tmp_path / "none.json")
    assert offers[0]["status"] == "Candidaté" and "Relance à faire" not in tracking.STATUSES


def test_letter_docx(tmp_path):
    import io
    from datetime import date
    from docx import Document
    from src import letter_docx as L
    contact = {"nom": "Camille Martin", "telephone": "06 00 00 00 00", "email": "a@b.fr", "ville": "Lyon"}
    L.save_contact(contact, tmp_path / "c.json")
    assert L.load_contact(tmp_path / "c.json")["ville"] == "Lyon"
    assert L.load_contact(tmp_path / "missing.json")["nom"] == "Camille Martin"
    letter = "Madame, Monsieur,\n\nPremier paragraphe\nsur deux lignes.\n\nSecond paragraphe.\n\nCamille Martin"
    offer = {"title": "Développeur C# H/F", "company": "IT Link", "location": "Paris - 75"}
    doc = Document(io.BytesIO(L.build(offer, letter, contact, today=date(2026, 11, 10))))
    texts = [p.text for p in doc.paragraphs if p.text]
    assert texts[:3] == ["Camille Martin", "06 00 00 00 00", "a@b.fr"]
    assert "Lyon, le 10 novembre 2026" in texts and "Objet : Candidature au poste de Développeur C#" in texts
    assert "Premier paragraphe sur deux lignes." in texts and texts[-1] == "Camille Martin"
    en = Document(io.BytesIO(L.build({"title": "Data Engineer", "company": "Z"}, "Dear Hiring Manager,\n\nText.", contact,
                                     english=True, today=date(2026, 11, 10))))
    en_texts = [p.text for p in en.paragraphs if p.text]
    assert "Lyon, November 10, 2026" in en_texts and "Subject: Application for the position of Data Engineer" in en_texts
    assert L.file_name(offer) == "Lettre_IT_Link_Developpeur_C.docx"


def test_gitsync_recovers_from_a_stuck_rebase(tmp_path):
    """The user's PC was left mid-rebase (CHERRY_PICK_HEAD) after a conflict on feedback.json."""
    import subprocess
    from src import gitsync

    def run(cwd, *a, check=True):
        return subprocess.run(["git", *a], cwd=cwd, check=check, capture_output=True, text=True)

    remote, pc, other = tmp_path / "remote.git", tmp_path / "pc", tmp_path / "other"
    run(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    run(tmp_path, "clone", "-q", str(remote), str(other))
    for repo in (other,):
        run(repo, "config", "user.name", "x"); run(repo, "config", "user.email", "x@x")
    (other / "data").mkdir()
    (other / "data" / "feedback.json").write_text("[]\n")
    (other / "app.py").write_text("v1\n")
    run(other, "add", "."); run(other, "commit", "-qm", "init"); run(other, "push", "-q", "origin", "HEAD:main")
    run(tmp_path, "clone", "-q", str(remote), str(pc))
    run(pc, "config", "user.name", "pc"); run(pc, "config", "user.email", "pc@x")

    # PC: a feedback commit that never got pushed
    (pc / "data" / "feedback.json").write_text('[{"id": "hw_1", "reason": "trop commercial"}]\n')
    run(pc, "commit", "-qam", "feedback local")
    # GitHub: an older feedback push + a new version of the app
    (other / "data" / "feedback.json").write_text('[{"id": "hw_0", "reason": "ancien"}]\n')
    (other / "app.py").write_text("v2\n")
    run(other, "commit", "-qam", "remote"); run(other, "push", "-q", "origin", "HEAD:main")

    # plain rebase conflicts and leaves the repo stuck, like on the user's PC
    assert run(pc, "pull", "--rebase", "origin", "main", check=False).returncode != 0
    assert run(pc, "pull", "--rebase", "origin", "main", check=False).returncode != 0   # every later pull fails

    ok, out = gitsync.pull(pc)
    assert ok, out
    assert (pc / "app.py").read_text() == "v2\n"                                   # update received
    assert "trop commercial" in (pc / "data" / "feedback.json").read_text()        # local refusals kept
    assert not (pc / ".git" / "rebase-merge").exists() and not (pc / ".git" / "CHERRY_PICK_HEAD").exists()
    assert gitsync.pull(pc)[0]                                                     # and later pulls work
    # the kept feedback is then pushed
    ok, out = gitsync.push_file(pc, "data/feedback.json", "feedback")
    assert ok, out
    run(other, "pull", "-q", "--rebase", "origin", "main")
    assert "trop commercial" in (other / "data" / "feedback.json").read_text()


def test_gitsync_reattaches_a_detached_head(tmp_path):
    import subprocess
    from src import gitsync

    def run(cwd, *a):
        return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

    remote, pc = tmp_path / "r.git", tmp_path / "pc"
    run(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    run(tmp_path, "clone", "-q", str(remote), str(pc))
    run(pc, "config", "user.name", "x"); run(pc, "config", "user.email", "x@x")
    (pc / "a.txt").write_text("1\n"); run(pc, "add", "."); run(pc, "commit", "-qm", "1"); run(pc, "push", "-q", "origin", "HEAD:main")
    run(pc, "checkout", "-q", "--detach")
    assert gitsync.pull(pc)[0]
    assert run(pc, "symbolic-ref", "--short", "HEAD") == "main"



def test_windows_notification_once_per_offer(tmp_path, monkeypatch):
    import json
    from src import winnotify
    store = tmp_path / "s.json"
    offers = {"hw_1": {"source": "HelloWork", "title": "PMO Junior", "company": "A", "score": 9, "relevancy_check": "relevant"},
              "hw_2": {"source": "HelloWork", "title": "Comptable", "company": "B", "relevancy_check": "not_relevant"}}
    store.write_text(json.dumps(offers))
    monkeypatch.setattr(tracking, "GITHUB_STORE", store)
    monkeypatch.setattr(tracking, "LOCAL_STORE", tmp_path / "none.json")
    monkeypatch.setattr(tracking, "VIE_STORE", tmp_path / "none2.json")
    monkeypatch.setattr(tracking, "SUIVI_PATH", tmp_path / "suivi.json")
    shown, path = [], tmp_path / "notified.json"
    assert winnotify.notify_new_offers(path, notify=lambda t, b: shown.append((t, b))) == 0   # first run: silent
    offers["li_3"] = {"source": "LinkedIn", "title": "Développeur Python", "company": "C", "score": 7, "relevancy_check": "relevant"}
    offers["apec_4"] = {"source": "APEC", "title": "Chef de projet IT", "company": "D", "score": 9, "relevancy_check": "relevant"}
    store.write_text(json.dumps(offers))
    assert winnotify.notify_new_offers(path, notify=lambda t, b: shown.append((t, b))) == 2
    title, body = shown[0]
    assert "2 nouvelle(s) offre(s)" in title and body.splitlines()[0].startswith("⭐9 Chef de projet IT")
    assert winnotify.notify_new_offers(path, notify=lambda t, b: shown.append((t, b))) == 0   # never twice
    assert winnotify.toast("x", "y") is False                                                 # not Windows here


def test_score_existing_offer_and_show_it(tmp_path):
    import json
    class H:
        def generate(self, prompt):
            assert "note d'adéquation sur 10" in prompt and "Missions : reporting" in prompt
            return '{"relevant": true, "score": 7, "years_required": 0, "cv": "projet", "reason": "Bonne piste PMO"}'
    offer = {"id": "vie_1", "title": "PMO", "company": "A", "source": "VIE", "description": "Missions : reporting"}
    assert tracking.score_offer(offer, H(), "profil") == (7, "Bonne piste PMO")
    store = tmp_path / "s.json"
    store.write_text(json.dumps({"hw_1": {"source": "HelloWork", "title": "PMO", "relevancy_check": "relevant", "reason": "ok"}}))
    o = tracking.load_offers((store,), suivi={"hw_1": {"score": 7, "score_reason": "Bonne piste PMO"}},
                             vie_path=tmp_path / "none.json")[0]
    assert o["score"] == 7 and o["reason"] == "Bonne piste PMO"


def test_scores_file_and_background_scoring(tmp_path):
    store = tmp_path / "store.json"
    store.write_text(json.dumps({
        "hw_1": {"source": "HelloWork", "title": "PMO", "company": "A", "relevancy_check": "relevant",
                 "description": "x"},
        "hw_2": {"source": "HelloWork", "title": "Dev", "company": "B", "relevancy_check": "relevant",
                 "description": "x", "score": 8},
        "hw_3": {"source": "HelloWork", "title": "Bad", "company": "C", "relevancy_check": "relevant",
                 "description": "x"},
    }), encoding="utf-8")
    scores = tmp_path / "notes.json"
    offers = tracking.load_offers((store,), suivi={}, vie_path=tmp_path / "none.json", scores_path=scores)
    todo = [o for o in offers if tracking.needs_score(o)]
    assert {o["id"] for o in todo} == {"hw_1", "hw_3"}

    class H:
        def generate(self, prompt):
            if "Bad" in prompt:
                return "pas du json"
            return '{"relevant": true, "score": 6, "years_required": 0, "cv": "projet", "reason": "ok"}'

    state = {}
    tracking.score_missing(todo, H(), "profil", state,
                           save=lambda oid, s, r: tracking.save_score(oid, s, r, path=scores), pause=0)
    assert state["done"] == 2 and not state["running"] and "hw_3" in state["failed"]
    offers = {o["id"]: o for o in tracking.load_offers((store,), suivi={}, vie_path=tmp_path / "none.json",
                                                        scores_path=scores)}
    assert offers["hw_1"]["score"] == 6 and offers["hw_2"]["score"] == 8 and offers["hw_3"].get("score") is None
    # a failed offer is not retried in the same session
    assert tracking.start_scoring([offers["hw_3"]], H(), "profil", state) is False


def test_letter_when_site_refuses_description(tmp_path, monkeypatch):
    from src.sources.common import SourceBlocked

    def refuse(offer):
        raise SourceBlocked("HTTP 429")
    monkeypatch.setattr(tracking, "_download_description", refuse)
    offer = {"id": "li_1", "source": "LinkedIn", "title": "Développeur C#", "company": "ACME", "cv": "informatique"}
    assert tracking.fetch_description(offer, cache_path=tmp_path / "d.json") == ""

    prompts = []

    class H:
        def generate(self, prompt):
            prompts.append(prompt)
            return FULL_LETTER
    assert tracking.generate_letter(offer, H(), "profil", description="") == FULL_LETTER
    assert "indisponible" in prompts[0] and "Développeur C#" in prompts[0]

    # once downloaded, a description is cached and never fetched again
    monkeypatch.setattr(tracking, "_download_description", lambda o: "Texte de l'offre")
    assert tracking.fetch_description(offer, cache_path=tmp_path / "d.json") == "Texte de l'offre"
    monkeypatch.setattr(tracking, "_download_description", refuse)
    assert tracking.fetch_description(offer, cache_path=tmp_path / "d.json") == "Texte de l'offre"


def test_local_store_keeps_descriptions():
    from src import cdi_main
    offers = {"a": {"relevancy_check": "relevant", "description": "x", "letter": "l"}}
    assert cdi_main.slim(dict(a=dict(offers["a"])), keep_descriptions=True)["a"] == {"relevancy_check": "relevant",
                                                                                     "description": "x"}
    assert "description" not in cdi_main.slim(dict(a=dict(offers["a"])))["a"]


def test_gemini_answer_joins_parts_and_short_letters_are_retried():
    from src.gemini_handler import answer_text
    data = {"candidates": [{"content": {"parts": [{"text": "réflexion", "thought": True},
                                                  {"text": "Madame, Monsieur,\n\nDipl"}, {"text": "ômé d'école d'ingénieurs"}]},
                            "finishReason": "STOP"}]}
    assert answer_text(data) == "Madame, Monsieur,\n\nDiplômé d'école d'ingénieurs"

    full = "Madame, Monsieur,\n\n" + "Texte de la lettre. " * 40 + "\n\nCordialement,\nCamille Martin"
    answers = ["Madame, Monsieur,\n\nDipl", full]

    class H:
        def generate(self, prompt):
            return answers.pop(0)
    offer = {"id": "hw_1", "title": "Dev", "company": "A", "cv": "informatique"}
    assert tracking.generate_letter(offer, H(), "profil", description="desc") == full

    class Short:
        def generate(self, prompt):
            return "Madame, Monsieur,\n\nDipl"
    with pytest.raises(RuntimeError):
        tracking.generate_letter(offer, Short(), "profil", description="desc")


def test_code_changed_ignores_offer_updates(tmp_path):
    import subprocess
    from src import gitsync
    r = tmp_path
    run = lambda *a: subprocess.run(["git", *a], cwd=r, check=True, capture_output=True)
    run("init", "-q"); run("config", "user.email", "t@t"); run("config", "user.name", "t")
    (r / "data").mkdir(); (r / "src").mkdir()
    (r / "data" / "offers.json").write_text("{}"); (r / "src" / "a.py").write_text("x=1")
    run("add", "."); run("commit", "-qm", "a")
    a = gitsync.head(r)
    (r / "data" / "offers.json").write_text('{"1": {}}'); run("commit", "-qam", "offers")
    b = gitsync.head(r)
    (r / "src" / "a.py").write_text("x=2"); run("commit", "-qam", "code")
    c = gitsync.head(r)
    assert not gitsync.code_changed(r, a, b)
    assert gitsync.code_changed(r, b, c) and gitsync.code_changed(r, a, c)
    assert not gitsync.code_changed(r, c, c)
    assert gitsync.last_update(r)
