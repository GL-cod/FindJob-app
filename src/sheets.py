"""Link to the user's "Suivi candidatures" Google Sheet through its Apps Script web app
(google_sheets/apps_script.gs). Configured in .env: SHEETS_WEBAPP_URL, SHEETS_TOKEN."""
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

# app status -> "Retour" column; statuses not listed are not sent to the sheet
RETOUR = {
    "Candidaté": "En attente",
    "Entretien": "Positif",
    "Refusé": "Negatif",
}


def configured():
    return bool(os.environ.get("SHEETS_WEBAPP_URL") and os.environ.get("SHEETS_TOKEN"))


def norm_link(url):
    return re.sub(r"[?#].*$", "", (url or "").strip()).rstrip("/").lower()


def fetch_rows(timeout=20):
    """Rows already in the sheet: [{row, poste, entreprise, lien (normalized), retour}]."""
    r = requests.get(os.environ["SHEETS_WEBAPP_URL"], params={"token": os.environ["SHEETS_TOKEN"]}, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Google Sheets a refusé la demande : {data.get('error')}")
    return data["rows"]


def push(offer, status, note=None, timeout=30):
    """Add or update the offer's row. Returns the script's answer, or None if the status is not synced."""
    retour = RETOUR.get(status)
    if retour is None:
        return None
    payload = {
        "token": os.environ["SHEETS_TOKEN"],
        "lien": offer.get("url", ""),
        "poste": offer.get("title", ""),
        "entreprise": offer.get("company", ""),
        "date": datetime.now(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y"),
        "retour": retour,
        "commentaire": note,
    }
    r = requests.post(os.environ["SHEETS_WEBAPP_URL"], json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Google Sheets a refusé la demande : {data.get('error')}")
    return data


def update_comment(offer, note, timeout=30):
    payload = {"token": os.environ["SHEETS_TOKEN"], "lien": offer.get("url", ""), "commentaire": note}
    r = requests.post(os.environ["SHEETS_WEBAPP_URL"], json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------------ reading
# "Retour" column -> status in the app
RETOUR_TO_STATUS = {"en attente": "Candidaté", "positif": "Entretien", "négatif": "Refusé", "negatif": "Refusé"}


def fetch_sheet(timeout=20):
    """Whole answer of the script: {rows, sheet_url, version}. Older scripts send rows only."""
    r = requests.get(os.environ["SHEETS_WEBAPP_URL"], params={"token": os.environ["SHEETS_TOKEN"]}, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Google Sheets a refusé la demande : {data.get('error')}")
    data.setdefault("version", 1)
    data.setdefault("sheet_url", "")
    return data


def merged_status(app_status, retour):
    """Status to show for an offer that is in the sheet.

    The sheet's answer wins over a "waiting" status in the app (À regarder / Candidaté),
    but a status the user set beyond that (Entretien, Refusé, Pas intéressé) is kept.
    """
    target = RETOUR_TO_STATUS.get((retour or "").strip().lower(), "Candidaté")
    if app_status == "À regarder":
        return target
    if app_status == "Candidaté" and target in ("Entretien", "Refusé"):
        return target
    return app_status


def parse_date(value):
    m = re.match(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})", value or "")
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).date()
    except ValueError:
        return None


def summary(rows, today=None):
    """Counts for the header: total, en attente, positif, négatif, sans retour, this week, per week."""
    today = today or datetime.now(ZoneInfo("Europe/Paris")).date()
    week_start = today.toordinal() - today.weekday()
    out = {"total": len(rows), "en_attente": 0, "positif": 0, "negatif": 0, "sans_retour": 0,
           "cette_semaine": 0, "par_semaine": {}}
    for r in rows:
        retour = (r.get("retour") or "").strip().lower()
        if retour == "en attente":
            out["en_attente"] += 1
        elif retour == "positif":
            out["positif"] += 1
        elif retour in ("negatif", "négatif"):
            out["negatif"] += 1
        else:
            out["sans_retour"] += 1
        d = parse_date(r.get("date"))
        if d:
            monday = d.toordinal() - d.weekday()
            if monday == week_start:
                out["cette_semaine"] += 1
            key = datetime.fromordinal(monday).date()
            out["par_semaine"][key] = out["par_semaine"].get(key, 0) + 1
    return out


# ------------------------------------------------------------------ editing from the app
EDITABLE = {"Poste": "poste", "Entreprise": "entreprise", "Lien": "url", "Date": "date",
            "Retour": "retour", "Commentaire": "commentaire"}
RETOUR_CHOICES = ["En attente", "Positif", "Negatif", ""]


def update_row(row, expect_poste, fields, timeout=30):
    """Change cells of one row. Refused by the script if the row moved (its Poste changed)."""
    payload = {"token": os.environ["SHEETS_TOKEN"], "row": int(row), "expect_poste": expect_poste, "fields": fields}
    r = requests.post(os.environ["SHEETS_WEBAPP_URL"], json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError({"row_changed": "la ligne a bougé dans le Sheets, relis-le puis recommence",
                            "row_not_found": "ligne introuvable"}.get(data.get("error"), data.get("error")))
    return data


def add_row(poste, entreprise, url="", date="", retour="En attente", commentaire="", timeout=30):
    """Add an application made outside the app (spontaneous, agency...)."""
    payload = {"token": os.environ["SHEETS_TOKEN"], "lien": url or "", "poste": poste, "entreprise": entreprise,
               "date": date or datetime.now(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y"),
               "retour": retour or "En attente", "commentaire": commentaire or ""}
    r = requests.post(os.environ["SHEETS_WEBAPP_URL"], json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("error"))
    return data


def diff_rows(before, after):
    """Changed cells between two tables (lists of dicts with a '_row' key) -> [(row, poste_before, fields)]."""
    old = {r["_row"]: r for r in before}
    changes = []
    for r in after:
        o = old.get(r["_row"])
        if o is None:
            continue
        fields = {}
        for col, key in EDITABLE.items():
            a, b = (o.get(col) or ""), (r.get(col) or "")
            if str(a).strip() != str(b).strip():
                fields[key] = "" if b is None else str(b).strip()
        if fields:
            changes.append((r["_row"], o.get("Poste") or "", fields))
    return changes


# ------------------------------------------------------------------ colours (same as miseEnCouleur in the sheet)
RETOUR_COLORS = {
    "positif": ("#d9ead3", "#1e5631"),
    "negatif": ("#f4cccc", "#7f1d1d"),
    "négatif": ("#f4cccc", "#7f1d1d"),
    "en attente": ("#fff2cc", "#6b5200"),
}
RETOUR_COLORS_DARK = {
    "positif": ("#16301f", "#86efac"),
    "negatif": ("#3a1a1a", "#fca5a5"),
    "négatif": ("#3a1a1a", "#fca5a5"),
    "en attente": ("#33290d", "#fde68a"),
}


def row_style(row, dark=False):
    """pandas Styler row function: colour the whole row from its Retour (light or dark theme)."""
    palette = RETOUR_COLORS_DARK if dark else RETOUR_COLORS
    bg_fg = palette.get(str(row.get("Retour") or "").strip().lower())
    css = f"background-color: {bg_fg[0]}; color: {bg_fg[1]}" if bg_fg else ""
    return [css] * len(row)
