import io
import json

import pytest
from pptx import Presentation
from pptx.util import Inches

from src import cv_pptx, tracking


def _cv_bytes():
    """A small fictitious one-page CV, built like a real one: name, title, contact, labels in bold."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])

    def line(*parts):
        tf = slide.shapes.add_textbox(Inches(0.5), Inches(0.5), Inches(7), Inches(0.4)).text_frame
        para = tf.paragraphs[0]
        for text, bold in parts:
            r = para.add_run()
            r.text, r.font.bold = text, bold
    line(("CAMILLE MARTIN", True))
    line(("DÉVELOPPEUSE", False))
    line(("camille.martin@example.com", False))
    line(("06 12 34 56 78  •  Lyon", False))
    line(("PROFIL", True))
    line(("Diplômée de l’", False), ("École Exemple", True), (" : développement web et tests. Je recherche un poste de ", False),
         ("développeuse junior", True), (".", False))
    line(("Société Test — Stagiaire développement", True))
    line(("2024 – 2025", False))
    line(("Développement :", True), (" création d’une application web en Python et React.", False))
    line(("Langages :", True), (" Python, SQL, React.", False))
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


class FakeGemini:
    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return self.answer


def _by_text(segs, start):
    return next(s for s in segs if s["text"].replace("**", "").strip().startswith(start))


def test_segments_protect_facts_and_find_title():
    segs = cv_pptx.segments(_cv_bytes())
    assert _by_text(segs, "CAMILLE")["kind"] == "nom" and not _by_text(segs, "CAMILLE")["editable"]
    assert _by_text(segs, "DÉVELOPPEUSE")["kind"] == "titre" and _by_text(segs, "DÉVELOPPEUSE")["editable"]
    for fixed in ("camille.martin@", "06 12", "PROFIL", "Société Test —", "2024", "Développement :", "Langages :"):
        assert not _by_text(segs, fixed)["editable"], fixed
    profile = _by_text(segs, "Diplômée")
    assert profile["editable"] and "**École Exemple**" in profile["text"]   # bold kept as **…**
    assert _by_text(segs, "Python, SQL")["editable"]


def test_generate_keeps_only_allowed_changes_and_builds_a_valid_file():
    data = _cv_bytes()
    segs = cv_pptx.segments(data)
    ids = {k: _by_text(segs, t)["id"] for k, t in
           {"titre": "DÉVELOPPEUSE", "profil": "Diplômée", "langages": "Python, SQL", "mail": "camille.martin@",
            "dev": "création"}.items()}
    answer = json.dumps({"modifications": {
        ids["titre"]: "Développeuse fullstack junior (H/F)",
        ids["profil"]: "Diplômée de l’**École Exemple** : développement web, React et tests. "
                       "Je recherche un poste de **développeuse React chez ACME**.",   # « Je recherche » kept as is
        ids["langages"]: "**React**, Python, SQL.",          # bold added by Gemini: removed
        ids["mail"]: "pirate@example.com",                 # protected: ignored
        ids["dev"]: "x" * 400,                             # far too long: ignored
    }, "resume": "React mis en avant."})
    gemini = FakeGemini("Voici :\n```json\n" + answer + "\n```")
    result = cv_pptx.generate("Intitulé : Développeur React", gemini, "profil", data)

    assert set(result["modifications"]) == {ids["titre"], ids["profil"], ids["langages"]}
    assert result["modifications"][ids["titre"]] == "DÉVELOPPEUSE FULLSTACK JUNIOR"
    assert result["modifications"][ids["langages"]] == " React, Python, SQL."      # leading space restored
    assert result["resume"] == "React mis en avant."
    assert "N'invente RIEN" in gemini.prompts[0] and "camille.martin@" not in gemini.prompts[0].split("=== CV")[0]

    out = Presentation(io.BytesIO(cv_pptx.build(data, result["modifications"])))
    texts = [sh.text_frame.text for sh in out.slides[0].shapes]
    assert "DÉVELOPPEUSE FULLSTACK JUNIOR" in texts
    assert "camille.martin@example.com" in texts
    assert "Développement : création d’une application web en Python et React." in texts
    profile_runs = next(sh for sh in out.slides[0].shapes if sh.text_frame.text.startswith("Diplômée")
                        ).text_frame.paragraphs[0].runs
    assert [(r.text, bool(r.font.bold)) for r in profile_runs] == [
        ("Diplômée de l’", False), ("École Exemple", True),
        (" : développement web, React et tests. Je recherche un poste de ", False),
        ("développeuse junior", True), (".", False)]
    assert cv_pptx.diff(data, result["modifications"])[0][0] == "DÉVELOPPEUSE"


def test_generate_fails_cleanly_on_unusable_answers():
    with pytest.raises(RuntimeError):
        cv_pptx.generate("offre", FakeGemini("pas de JSON"), "profil", _cv_bytes())
    with pytest.raises(RuntimeError):
        cv_pptx.generate("offre", FakeGemini('{"modifications": {"p0.0": "HACK"}}'), "profil", _cv_bytes())


def test_models_on_disk_and_tracking(tmp_path):
    with pytest.raises(ValueError):
        cv_pptx.save_model("informatique", b"not a pptx", tmp_path)
    data = _cv_bytes()
    keys = cv_pptx.model_keys()
    cv_pptx.save_model(keys[0], data, tmp_path)
    assert cv_pptx.available_models(tmp_path) == [keys[0]]
    assert cv_pptx.model_for_offer({"cv": "inconnu"}, tmp_path) == keys[0]

    segs = cv_pptx.segments(data)
    titre = _by_text(segs, "DÉVELOPPEUSE")["id"]
    gemini = FakeGemini(json.dumps({"modifications": {titre: "Data analyst"}, "resume": "ok"}))
    offer = {"id": "hw_1", "title": "Data analyst H/F", "company": "ACME", "description": "SQL et Python"}
    done = tracking.generate_cv(offer, gemini, "profil", keys[0], models_dir=tmp_path)
    assert done == {"modele": keys[0], "modifications": {titre: "DATA ANALYST"}, "resume": "ok"}
    assert "SQL et Python" in gemini.prompts[0]
    assert cv_pptx.file_name(offer, "Camille Martin") == "CV_Camille_Martin_ACME.pptx"

    cv_pptx.delete_model(keys[0], tmp_path)
    with pytest.raises(RuntimeError):
        tracking.generate_cv(offer, gemini, "profil", keys[0], models_dir=tmp_path)


def test_light_touch_rules():
    segs = [{"id": f"x{i}", "text": f" texte numéro {i} assez long pour être modifié.", "editable": True,
             "kind": "texte"} for i in range(10)]
    changes = {f"x{i}": f"texte numéro {i} un peu reformulé ici." for i in range(10)}
    assert len(cv_pptx.clean_changes(segs, changes)) == cv_pptx.MAX_CHANGES

    old = "Ingénieur polyvalent. Je recherche un poste de **ingénieur informatique**."
    assert cv_pptx._keep_looking_for(old, "Ingénieur polyvalent, orienté tests. Je recherche un poste de "
                                          "**consultant PMO chez X**.") == \
        "Ingénieur polyvalent, orienté tests. Je recherche un poste de **ingénieur informatique**."
    assert cv_pptx._keep_looking_for(old, "Ingénieur orienté tests.") == \
        "Ingénieur orienté tests. Je recherche un poste de **ingénieur informatique**."
    segs = [{"id": "p", "text": old, "editable": True, "kind": "texte"}]
    assert cv_pptx.clean_changes(segs, {"p": "Ingénieur polyvalent. Je recherche un CDI chez ACME."}) == {}
