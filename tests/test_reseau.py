from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from src import reseau


def test_links():
    u = reseau.linkedin_people_url("Airbus", "réalité virtuelle")
    assert u.startswith("https://www.linkedin.com/search/results/people/")
    assert parse_qs(urlparse(u).query)["keywords"] == ["réalité virtuelle Airbus"]
    assert parse_qs(urlparse(reseau.linkedin_people_url("Acme")).query)["keywords"] == ["réalité virtuelle Acme"]
    g = reseau.gmail_url("a@b.fr", "Objet & co", "Bonjour,\nTexte")
    q = parse_qs(urlparse(g).query)
    assert q["to"] == ["a@b.fr"] and q["su"] == ["Objet & co"] and q["body"] == ["Bonjour,\nTexte"]
    assert reseau.mailto_url("a@b.fr", "Objet", "x y").startswith("mailto:a%40b.fr?subject=Objet&body=x%20y")


def test_status_changes_and_follow_up():
    today = date(2026, 11, 11)
    f = reseau.status_change("Contacté", today)
    assert f == {"statut": "Contacté", "contacte_le": "11/11/2026", "relance_le": "18/11/2026"}
    assert reseau.status_change("A répondu", today) == {"statut": "A répondu", "relance_le": ""}
    c = {"statut": "Contacté", "relance_le": "18/11/2026"}
    assert not reseau.follow_up_due(c, today) and reseau.follow_up_due(c, date(2026, 11, 18))
    contacts = [c, {"statut": "A répondu"}, {"statut": "À contacter"}, {"statut": "Entretien"}]
    s = reseau.summary(contacts, date(2026, 11, 20))
    assert s["total"] == 4 and s["reached"] == 3 and s["answered"] == 2 and s["rate"] == 67 and s["due"] == 1


def test_suggest_companies():
    offers = [{"company": "Airbus", "score": 8}, {"company": "Thales", "score": 9}, {"company": "Thales", "score": 7},
              {"company": "Petite SAS", "score": 5}, {"company": "Entreprise confidentielle", "score": 9}]
    s = reseau.suggest_companies(offers, [{"entreprise": "airbus"}])
    assert [x["entreprise"] for x in s] == ["Thales"] and s[0]["offres"] == 2 and s[0]["best"] == 9


def test_message_generation():
    long_note = "Bonjour Marie, " + "x" * 320 + "."
    good = '{"note": "Bonjour Marie, ingénieur XR (Acme), j\'aimerais échanger.", "objet": "Échange XR", "mail": "Bonjour Marie Dupont,\\n..."}'
    answers = ["pas de json", '{"note": "%s", "objet": "o", "mail": "m"}' % long_note, good]

    class H:
        def generate(self, prompt):
            assert "Responsable VR" in prompt and "N'invente RIEN" in prompt
            return answers.pop(0)
    msg = reseau.generate_message({"nom": "Marie Dupont", "poste": "Responsable VR", "entreprise": "Airbus"},
                                  {"secteur": "Aéronautique"}, H(), "profil")
    assert msg["note"].startswith("Bonjour Marie") and len(msg["note"]) <= reseau.NOTE_MAX
    assert reseau.unpack_message(reseau.pack_message(msg)) == msg

    class Long:
        def generate(self, prompt):
            return '{"note": "Une phrase. %s", "objet": "o", "mail": "m"}' % ("y" * 400)
    assert len(reseau.generate_message({}, None, Long(), "p")["note"]) <= reseau.NOTE_MAX

    class Bad:
        def generate(self, prompt):
            return "rien"
    with pytest.raises(RuntimeError):
        reseau.generate_message({}, None, Bad(), "p")


def test_save_env_value(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("GEMINI_API_KEY=k\nRESEAU_WEBAPP_URL=old\n", encoding="utf-8")
    monkeypatch.delenv("RESEAU_WEBAPP_URL", raising=False)
    reseau.save_env_value("RESEAU_WEBAPP_URL", "https://script.google.com/x/exec", env)
    assert env.read_text(encoding="utf-8") == "GEMINI_API_KEY=k\nRESEAU_WEBAPP_URL=https://script.google.com/x/exec\n"
    import os
    assert os.environ["RESEAU_WEBAPP_URL"] == "https://script.google.com/x/exec"


def test_script_has_token_placeholder():
    assert "COLLE_ICI_TON_CODE_SECRET" in reseau.SCRIPT_PATH.read_text(encoding="utf-8")
    assert "const TOKEN = 'abc';" in reseau.script_text("abc")
    assert len(reseau.default_companies()) == len(reseau.DEFAULT_COMPANIES) >= 20


SHEET = [["Mon réseau XR", "", ""],
         ["Prénom", "Nom", "Société", "Fonction", "Profil", "Statut", "Date", "Commentaire"],
         ["Marie", "Dupont", "Airbus", "Responsable VR", "https://www.linkedin.com/in/md", "Message envoyé",
          "02/11/2026", "vue au salon"],
         ["", "", "Thales", "", "", "", "", ""],
         ["Paul", "Martin", "Acme", "Chef de projet XR", "", "répondu", "", ""],
         ["Marie", "Dupont", "Airbus", "", "", "", "", ""]]


def test_guess_mapping_and_import():
    m = reseau.guess_mapping(SHEET)
    assert m == {"nom": 1, "prenom": 0, "poste": 3, "entreprise": 2, "secteur": None, "linkedin": 4,
                 "email": None, "statut": 5, "contacte_le": 6, "notes": 7}
    contacts, companies = reseau.build_import(SHEET, m, known_companies=[{"entreprise": "acme"}])
    assert [c["nom"] for c in contacts] == ["Marie Dupont", "Paul Martin"]      # duplicate line ignored
    assert contacts[0]["statut"] == "Contacté" and contacts[0]["relance_le"] == "09/11/2026"
    assert "vue au salon" in contacts[0]["notes"] and contacts[1]["statut"] == "A répondu"
    assert [c["entreprise"] for c in companies] == ["Airbus", "Thales"]          # Acme already known
    again, _ = reseau.build_import(SHEET, m, known_contacts=[{"nom": "marie dupont", "entreprise": "AIRBUS"}])
    assert [c["nom"] for c in again] == ["Paul Martin"]


def test_guess_mapping_by_content():
    v = [["Personne", "Boîte", "Infos", "Lien"],
         ["Jean Roux", "Safran", "jean.roux@safran.example", "https://www.linkedin.com/in/jr"],
         ["Léa Bon", "Orange", "lea@orange.example", "https://linkedin.com/in/lb"]]
    m = reseau.guess_mapping(v)
    assert m["nom"] == 0 and m["entreprise"] == 1 and m["email"] == 2 and m["linkedin"] == 3


def test_map_status():
    assert reseau.map_status("") == ("À contacter", "")
    assert reseau.map_status("Entretien")[0] == "Entretien"
    assert reseau.map_status("RDV le 3/12")[0] == "Entretien"
    assert reseau.map_status("pas de réponse")[0] == "Pas de réponse"
    assert reseau.map_status("En attente")[0] == "Contacté"
    assert reseau.map_status("à voir") == ("À contacter", "Statut d'origine : à voir")
