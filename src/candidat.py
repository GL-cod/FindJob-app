"""Who the app works for: name, CVs, target jobs, network search.

Everything personal that the prompts and the app need lives here, so the same code can
serve anyone who copies the repo. Sources, in order:
  1. data/coordonnees.json (filled in the app's 🔎 Réglages tab, never pushed) for the name;
  2. the 'candidat' block of cdi_search.yaml (edited on GitHub, read by GitHub and the PC);
  3. the neutral defaults below.
"""
from pathlib import Path
import json

import yaml

ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = ROOT / "cdi_search.yaml"
CONTACT_PATH = ROOT / "data" / "coordonnees.json"

DEFAULTS = {
    "nom": "",
    "metiers": "",
    "cvs": {
        "principal": {"nom": "CV principal", "quand": "tous les postes", "angle": ""},
    },
    "cv_vie": {"fr": "CV en français", "en": "CV en anglais"},
    "reseau": {"recherche": "", "exemple": "", "entreprises": []},
}

_cache = {"key": None, "data": None}


def _read_yaml(path):
    try:
        with open(path, encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}).get("candidat") or {}
    except (FileNotFoundError, yaml.YAMLError, AttributeError):
        return {}


def settings(path=None):
    """The 'candidat' block merged over the defaults (re-read when the file changes)."""
    path = Path(path or SETTINGS_PATH)
    try:
        key = (str(path), path.stat().st_mtime)
    except OSError:
        key = (str(path), None)
    if _cache["key"] != key:
        raw = _read_yaml(path)
        data = {**DEFAULTS, **{k: v for k, v in raw.items() if v not in (None, "")}}
        data["reseau"] = {**DEFAULTS["reseau"], **(raw.get("reseau") or {})}
        data["cv_vie"] = {**DEFAULTS["cv_vie"], **(raw.get("cv_vie") or {})}
        cvs = raw.get("cvs") or {}
        data["cvs"] = {str(k): {"nom": str((v or {}).get("nom") or k), "quand": str((v or {}).get("quand") or ""),
                                "angle": str((v or {}).get("angle") or "")}
                       for k, v in cvs.items()} or DEFAULTS["cvs"]
        _cache.update(key=key, data=data)
    return _cache["data"]


# ------------------------------------------------------------------ name
def nom(contact_path=None):
    """Full name for letters and messages: Réglages tab first, then cdi_search.yaml."""
    try:
        local = json.loads(Path(contact_path or CONTACT_PATH).read_text(encoding="utf-8")).get("nom")
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        local = None
    return (local or settings().get("nom") or "").strip()


def prenom():
    return nom().split(" ")[0] if nom() else ""


def signature_rule(lang="fr"):
    """End-of-letter instruction for Gemini."""
    n = nom()
    if lang == "en":
        return f'end with "{n}"' if n else "end with a short sign-off, without inventing a name"
    return f"suivie de « {n} »" if n else "sans inventer de nom (il sera ajouté à la main)"


# ------------------------------------------------------------------ CVs
def cvs():
    return settings()["cvs"]


def default_cv():
    return next(iter(cvs()))


def cv_label(key):
    """Name shown in the app ('Ingénieur Informatique'), or '' for an unknown key."""
    if key in ("vie_fr", "vie_en"):
        return vie_cv(key[4:])
    cv = cvs().get(key)
    return cv["nom"] if cv else ""


def normalize_cv(value):
    """Gemini's answer -> one of the configured CV keys (prefix match, else the first CV)."""
    value = str(value or "").strip().lower()
    keys = list(cvs())
    for k in keys:
        if value == k.lower():
            return k
    for k in keys:
        if value and (value.startswith(k.lower()[:4]) or k.lower().startswith(value[:4])):
            return k
    return keys[0]


def cv_angle(key):
    cv = cvs().get(key) or cvs()[default_cv()]
    return cv.get("angle") or cv.get("quand") or ""


def vie_cv(lang):
    return settings()["cv_vie"].get(lang) or DEFAULTS["cv_vie"].get(lang, "")


# ------------------------------------------------------------------ jobs and network
def metiers():
    """Fields the candidate targets, e.g. « l'informatique ou la gestion de projet IT »."""
    return settings().get("metiers") or ""


def reseau_search():
    return settings()["reseau"].get("recherche") or ""


def reseau_example():
    return settings()["reseau"].get("exemple") or ""


def reseau_companies():
    """[(name, sector, LinkedIn keywords)] starting list for the 🤝 Réseau tab."""
    out = []
    for item in settings()["reseau"].get("entreprises") or []:
        if isinstance(item, str):
            out.append((item, "", ""))
        elif isinstance(item, dict) and item.get("nom"):
            out.append((str(item["nom"]), str(item.get("secteur") or ""), str(item.get("recherche") or "")))
        elif isinstance(item, (list, tuple)) and item:
            parts = [str(x) for x in item] + ["", ""]
            out.append(tuple(parts[:3]))
    return out
