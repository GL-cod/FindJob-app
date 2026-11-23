"""Working time wanted (cdi_search.yaml, `temps_de_travail`): plein, partiel or tous.

One setting drives every place that cares about it:
  - LinkedIn: the f_JT filter (F = full time, P = part time);
  - France Travail: the API's tempsPlein filter (true / false);
  - the offers' own "Temps plein" / "Temps partiel" label: an offer clearly on the wrong
    side is set aside without calling Gemini (saves quota);
  - the Gemini prompt, for the boards that cannot filter (HelloWork, APEC).
Without the setting, nothing changes (old cdi_search.yaml files keep working).
"""
import re
from pathlib import Path

import yaml

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "cdi_search.yaml"

PLEIN, PARTIEL, TOUS = "plein", "partiel", "tous"
VALUES = (PLEIN, PARTIEL, TOUS)
_ALIASES = {
    "plein": PLEIN, "temps plein": PLEIN, "full": PLEIN, "full time": PLEIN, "full-time": PLEIN,
    "partiel": PARTIEL, "temps partiel": PARTIEL, "part": PARTIEL, "part time": PARTIEL,
    "part-time": PARTIEL, "mi-temps": PARTIEL,
    "tous": TOUS, "les deux": TOUS, "all": TOUS, "": TOUS,
}
LABELS = {PLEIN: "temps plein", PARTIEL: "temps partiel", TOUS: "temps plein ou partiel"}

_PARTIEL_RE = re.compile(r"temps\s+partiel|mi[\s-]temps|part[\s-]time|\btemps\s+choisi\b", re.IGNORECASE)
_PLEIN_RE = re.compile(r"temps\s+plein|temps\s+complet|full[\s-]time", re.IGNORECASE)


def value(settings):
    """plein / partiel / tous, or None when the setting is absent (keep the old behaviour)."""
    if not isinstance(settings, dict) or "temps_de_travail" not in settings:
        return None
    raw = settings.get("temps_de_travail")
    if raw is None:
        return TOUS
    key = str(raw).strip().lower()
    if key not in _ALIASES:
        raise ValueError(f"cdi_search.yaml: temps_de_travail doit valoir plein, partiel ou tous (pas « {raw} »).")
    return _ALIASES[key]


def from_file(path=None):
    """value() read from cdi_search.yaml (None if the file or the setting is missing or wrong)."""
    try:
        with open(path or SETTINGS_PATH, encoding="utf-8") as f:
            return value(yaml.safe_load(f) or {})
    except (OSError, yaml.YAMLError, ValueError):
        return None


def linkedin_job_types(settings):
    """f_JT value for LinkedIn ("" = no filter)."""
    v = value(settings)
    if v is None:
        return (settings.get("linkedin") or {}).get("job_types") or ""
    return {PLEIN: "F", PARTIEL: "P", TOUS: ""}[v]


def francetravail_param(settings):
    """tempsPlein value for the France Travail API, or None for no filter."""
    return {PLEIN: "true", PARTIEL: "false"}.get(value(settings))


def detect(label):
    """'plein' / 'partiel' from a short label such as the offer's contract field, else None."""
    text = label or ""
    partiel, plein = bool(_PARTIEL_RE.search(text)), bool(_PLEIN_RE.search(text))
    if partiel and not plein:
        return PARTIEL
    if plein and not partiel:
        return PLEIN
    return None


def mismatch(offer, wanted):
    """Reason to set the offer aside when its own label says the other working time, else ''.

    Only the short contract label is read (not the description, where « possibilité de
    temps partiel » or « 35h » are too ambiguous): Gemini handles the rest.
    """
    if wanted not in (PLEIN, PARTIEL):
        return ""
    found = detect(offer.get("contract", ""))
    if found and found != wanted:
        return f"offre à {LABELS[found]} (tu cherches du {LABELS[wanted]})"
    return ""


def prompt_rule(wanted):
    """Line added to the Gemini relevance prompt ('' when there is nothing to say)."""
    if wanted == PARTIEL:
        return ("Le candidat cherche UNIQUEMENT un poste à temps partiel (mi-temps, quelques jours ou "
                "heures par semaine) : réponds NON si l'offre est clairement à temps plein.\n")
    if wanted == PLEIN:
        return "Le candidat cherche un poste à temps plein : réponds NON si l'offre est clairement à temps partiel.\n"
    return ""
