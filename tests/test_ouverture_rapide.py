"""The window must open without waiting for GitHub or Google: git pull and the two Google Sheets
are read in the background, from the last copy kept on the PC."""
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SLOW = 3.0


def _slow_sheet(timeout=20):
    time.sleep(SLOW)
    return {"rows": [{"row": 2, "n": "1", "poste": "Dev", "entreprise": "ACME", "lien": "",
                      "retour": "Positif", "date": "01/11/2026"}], "sheet_url": "u", "version": 3}


def _slow_reseau(timeout=25, tabs=False):
    time.sleep(SLOW)
    return {"contacts": [{"id": "1", "nom": "Alice", "entreprise": "ACME", "statut": "À contacter"}],
            "companies": [{"entreprise": "ACME"}], "sheet_url": "u", "version": 9}


def _slow_pull(root):
    time.sleep(SLOW)
    return True, "ok"


@pytest.fixture
def app_copy(tmp_path, monkeypatch):
    pytest.importorskip("streamlit.testing.v1")
    dest = tmp_path / "app_copy"
    shutil.copytree(ROOT, dest, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", "logs",
                                                              "sheet_cache.json", "reseau_cache.json",
                                                              "suivi_candidatures.json", "coordonnees.json",
                                                              "cv_modeles", ".env"))
    for k, v in {"MES_CANDIDATURES_NO_PUSH": "1", "SHEETS_WEBAPP_URL": "http://sheets.invalid",
                 "SHEETS_TOKEN": "t", "RESEAU_WEBAPP_URL": "http://reseau.invalid", "RESEAU_TOKEN": "t",
                 "GEMINI_API_KEY": "", "CDI_USER_DESCRIPTION": ""}.items():
        monkeypatch.setenv(k, v)
    from src import gitsync, reseau, reseau_ui, sheets, tracking
    for name in ("SEEN_PATH", "SUIVI_PATH", "SCORES_PATH", "DESC_CACHE_PATH"):   # never the real data/
        monkeypatch.setattr(tracking, name, dest / "data" / getattr(tracking, name).name)
    monkeypatch.setattr(reseau_ui, "CACHE_PATH", dest / "data" / "reseau_cache.json")
    monkeypatch.setattr(sheets, "fetch_sheet", _slow_sheet)
    monkeypatch.setattr(reseau, "fetch", _slow_reseau)
    monkeypatch.setattr(gitsync, "pull", _slow_pull)
    monkeypatch.setattr(sys, "path", [str(dest)] + [p for p in sys.path if Path(p).resolve() != ROOT])
    return dest


def test_window_opens_without_waiting_for_network(app_copy):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(app_copy / "app" / "dashboard.py"), default_timeout=60)
    start = time.time()
    at.run()
    assert not at.exception
    assert time.time() - start < SLOW, "la page attend GitHub ou Google Sheets avant de s'afficher"

    time.sleep(SLOW + 1.5)          # background readings done
    at.run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["📨 Candidatures"] == "1"
    assert (app_copy / "data" / "sheet_cache.json").exists()
    assert (app_copy / "data" / "reseau_cache.json").exists()
