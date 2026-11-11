"""The app must work for someone else: settings come from cdi_search.yaml (candidat) and the Réglages tab."""
import json
from pathlib import Path

import pytest
import yaml

from src import candidat, cdi_relevance, reseau, tracking
from src.lang import VIE_CV

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def friend(tmp_path, monkeypatch):
    """A fresh copy set up with cdi_search.exemple.yaml and nothing filled in."""
    monkeypatch.setattr(candidat, "SETTINGS_PATH", ROOT / "cdi_search.exemple.yaml")
    monkeypatch.setattr(candidat, "CONTACT_PATH", tmp_path / "coordonnees.json")
    candidat._cache["key"] = None
    yield tmp_path
    candidat._cache["key"] = None


def test_example_settings_are_neutral(friend):
    text = (ROOT / "cdi_search.exemple.yaml").read_text(encoding="utf-8")
    for word in ("réalité virtuelle", "Ingénieur Projet", "XR"):
        assert word not in text
    data = yaml.safe_load(text)
    assert data["keywords"] and data["candidat"]["cvs"]
    # every key the watchers read is still there
    real = yaml.safe_load((ROOT / "cdi_search.yaml").read_text(encoding="utf-8"))
    assert set(real) == set(data)


def test_friend_prompts_have_no_trace_of_the_owner(friend):
    assert candidat.nom() == "" and candidat.prenom() == ""
    p = cdi_relevance.relevance_prompt({"title": "x"}, "profil", 3, [], "")
    letter = cdi_relevance.letter_prompt({"title": "x"}, "profil", "principal")
    msg = reseau.message_prompt({"nom": "Marie"}, {}, "profil")
    for text in (p, letter, msg):
        assert "Camille" not in text and "XR" not in text and "réalité virtuelle" not in text
    assert '"cv": "principal"' in p and "sans inventer de nom" in letter
    assert reseau.default_companies() == [] and reseau.DEFAULT_SEARCH == "chef de projet"
    assert VIE_CV["fr"] == "CV en français"


def test_name_from_reglages_wins(friend):
    (friend / "coordonnees.json").write_text(json.dumps({"nom": "Karim Benali"}), encoding="utf-8")
    assert candidat.nom() == "Karim Benali" and candidat.prenom() == "Karim"
    assert "« Karim Benali »" in cdi_relevance.letter_prompt({"title": "x"}, "profil", "principal")
    assert tracking.letter_is_complete("Madame, Monsieur,\n\n" + "Texte. " * 120 + "\n\nCordialement,\nKarim Benali")
    assert not tracking.letter_is_complete("Madame, Monsieur,\n\n" + "Texte. " * 120 + "\n\nCordialement,")


def test_cv_choice_follows_the_configured_cvs(friend, tmp_path, monkeypatch):
    cfg = tmp_path / "s.yaml"
    cfg.write_text(yaml.safe_dump({"candidat": {"cvs": {
        "commercial": {"nom": "CV Commercial", "quand": "vente"},
        "marketing": {"nom": "CV Marketing", "quand": "communication, marketing"}}}}, allow_unicode=True),
        encoding="utf-8")
    monkeypatch.setattr(candidat, "SETTINGS_PATH", cfg)
    candidat._cache["key"] = None
    assert cdi_relevance.parse_verdict('{"relevant": true, "cv": "marketing", "reason": "ok"}')[1] == "marketing"
    assert cdi_relevance.parse_verdict('{"relevant": true, "cv": "Marketing digital"}')[1] == "marketing"
    assert cdi_relevance.parse_verdict('{"relevant": true, "cv": "???"}')[1] == "commercial"
    assert candidat.cv_label("marketing") == "CV Marketing" and candidat.cv_label("inconnu") == ""
    assert '"commercial"|"marketing"' in cdi_relevance.relevance_prompt({"title": "x"}, "p")
