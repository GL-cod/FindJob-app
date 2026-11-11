"""Tests use fixed candidate settings, not the cdi_search.yaml / coordonnees.json of the person running them."""
from pathlib import Path

import pytest

from src import candidat


@pytest.fixture(autouse=True)
def _candidat_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(candidat, "SETTINGS_PATH", Path(__file__).parent / "candidat_test.yaml")
    monkeypatch.setattr(candidat, "CONTACT_PATH", tmp_path / "no_coordonnees.json")
    candidat._cache["key"] = None
    yield
    candidat._cache["key"] = None
