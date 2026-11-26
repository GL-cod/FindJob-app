"""Contract types wanted (cdi_search.yaml, `contrats`): any of CDI, CDD, interim.

One setting drives every source:
  - HelloWork: the c= filter (CDI, CDD, Travail_temp);
  - France Travail: typeContrat (CDI, CDD, MIS = intérim);
  - APEC: CDI only when only CDI is wanted, else no filter (the APEC lists few other contracts);
  - LinkedIn: f_JT gets C (contrat) and T (temporaire) on top of F (temps plein);
  - Adecco: the contract shown on each offer.
Without the setting, each source keeps its own old setting (old cdi_search.yaml files keep working).
"""
import unicodedata

CDI, CDD, INTERIM = "CDI", "CDD", "interim"
_ALIASES = {"cdi": CDI, "cdd": CDD, "interim": INTERIM, "intérim": INTERIM, "interimaire": INTERIM,
            "travail temporaire": INTERIM, "mission": INTERIM, "mis": INTERIM, "travail_temp": INTERIM}

HELLOWORK = {CDI: "CDI", CDD: "CDD", INTERIM: "Travail_temp"}
FRANCETRAVAIL = {CDI: "CDI", CDD: "CDD", INTERIM: "MIS"}


def _key(value):
    text = unicodedata.normalize("NFC", str(value or "")).strip().lower()
    if text not in _ALIASES:
        raise ValueError(f"cdi_search.yaml: contrats accepte CDI, CDD et interim (pas « {value} »).")
    return _ALIASES[text]


def value(settings):
    """Ordered list of wanted contracts, or None when the setting is absent or empty (= no filter)."""
    raw = (settings or {}).get("contrats") if isinstance(settings, dict) else None
    if not raw:
        return None
    if isinstance(raw, str):
        raw = [x for x in raw.replace(";", ",").split(",")]
    out = []
    for item in raw:
        if str(item).strip():
            k = _key(item)
            if k not in out:
                out.append(k)
    return out or None


def hellowork_param(settings):
    """Value(s) for HelloWork's c= filter: a list, a string (old setting) or '' for all."""
    wanted = value(settings)
    if wanted is None:
        return (settings.get("hellowork") or {}).get("contracts") or ""
    return [HELLOWORK[k] for k in wanted]


def francetravail_param(settings):
    wanted = value(settings)
    if wanted is None:
        return (settings.get("francetravail") or {}).get("contrat", "CDI")
    return ",".join(FRANCETRAVAIL[k] for k in wanted)


def apec_param(settings):
    wanted = value(settings)
    if wanted is None:
        return (settings.get("apec") or {}).get("contrat", "101888")
    return "101888" if wanted == [CDI] else ""


def linkedin_job_types(base, settings):
    """Add LinkedIn's « contrat » (C) and « temporaire » (T) types when CDD or intérim is wanted."""
    wanted = value(settings)
    if not base or wanted is None or wanted == [CDI]:
        return base
    types = [t for t in base.split(",") if t]
    for extra in ("C", "T"):
        if extra not in types:
            types.append(extra)
    return ",".join(types)


def label(settings):
    """« CDI, CDD ou intérim » for messages."""
    wanted = value(settings)
    if wanted is None:
        return ""
    names = ["intérim" if k == INTERIM else k for k in wanted]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " ou " + names[-1]
