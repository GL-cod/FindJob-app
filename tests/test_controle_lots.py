import json

from src import cdi_main, controle_lots
from test_lots import BatchHandler


def test_controle_compares_alone_and_batch(tmp_path, monkeypatch, capsys):
    store = {f"hw_{i}": {"source": "HelloWork", "title": f"Poste {i}", "company": "E", "location": "Paris - 75",
                         "posted": f"2026-11-{10 + i}", "url": f"u{i}", "description": "Support",
                         "relevancy_check": "relevant" if i % 2 == 0 else "not_relevant", "reason": "r"}
             for i in range(1, 13)}
    path = tmp_path / "cdi_offers.json"
    path.write_text(json.dumps(store), encoding="utf-8")
    monkeypatch.setattr(cdi_main, "STORE_PATH", path)
    monkeypatch.setattr(cdi_main, "load_env", lambda: {"GEMINI_API_KEY": "k", "USER_PROFILE": "profil"})
    monkeypatch.setattr(controle_lots, "GeminiHandler", lambda *a, **k: BatchHandler())
    same, total = controle_lots.main(n=12, batch_size=10)
    assert (same, total) == (12, 12)
    assert "Même verdict (retenue ou non) : 12/12" in capsys.readouterr().out
    assert json.loads(path.read_text(encoding="utf-8")) == store          # nothing saved
