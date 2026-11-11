"""What the user turned down (« Pas intéressé ») and why, so the Gemini filters learn from it.

Written by the local app (data/feedback.json, committed to the repo so the GitHub runs
read it too), read by the CDI filter (cdi_relevance) and the VIE filter (relevance).
"""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
FEEDBACK_PATH = ROOT / "data" / "feedback.json"
MAX_IN_PROMPT = 40


def load(path=None):
    try:
        data = json.loads(Path(path or FEEDBACK_PATH).read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save(entries, path=None):
    path = Path(path or FEEDBACK_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record(offer, reason="", path=None):
    """Add or update the rejection of one offer. Returns the entries."""
    entries = [e for e in load(path) if e.get("id") != offer.get("id")]
    entries.append({
        "id": offer.get("id"),
        "source": offer.get("source", ""),
        "title": (offer.get("title") or "")[:150],
        "company": (offer.get("company") or "")[:80],
        "reason": (reason or "").strip()[:300],
        "date": datetime.now(ZoneInfo("Europe/Paris")).strftime("%Y-%m-%d"),
    })
    save(entries, path)
    return entries


def forget(offer_id, path=None):
    entries = [e for e in load(path) if e.get("id") != offer_id]
    save(entries, path)
    return entries


def prompt_block(entries=None, lang="fr"):
    """Text appended to a Gemini prompt; empty when there is no feedback yet."""
    entries = (entries if entries is not None else load())[-MAX_IN_PROMPT:]
    if not entries:
        return ""
    lines = []
    for e in entries:
        line = f"- {e.get('title', '')} ({e.get('company', '')})"
        if e.get("reason"):
            line += f" : {e['reason']}"
        lines.append(line)
    head = ("Offres que le candidat a déjà refusées, avec sa raison quand il l'a donnée. "
            "Réponds NON aux offres du même genre (même type de poste, même raison) :\n") if lang == "fr" else (
            "Offers the candidate has already turned down, with his reason when given. "
            "Answer NO to offers of the same kind (same type of role, same reason):\n")
    return head + "\n".join(lines) + "\n\n"
