"""Data layer of the local "Mes candidatures" app.

Offers come from two stores:
  - data/cdi_offers.json            HelloWork, written by GitHub Actions (git pull)
  - data/cdi_offers_linkedin.json   LinkedIn, written by the search on this PC
The user's follow-up (status, notes, letters) lives in data/suivi_candidatures.json,
which stays on this PC (data/* is git-ignored). Each entry keeps a snapshot of the
offer, so it survives after the offer expires from the stores.
"""
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .lang import guess_lang

ROOT = Path(__file__).resolve().parent.parent
GITHUB_STORE = ROOT / "data" / "cdi_offers.json"
VIE_STORE = ROOT / "data" / "offers.json"
VIE_URL = "https://mon-vie-via.businessfrance.fr/offres/{id}"
VIE_PREFIX = "vie_"
LOCAL_STORE = ROOT / "data" / "cdi_offers_linkedin.json"
SUIVI_PATH = ROOT / "data" / "suivi_candidatures.json"
SEEN_PATH = ROOT / "data" / "vues_app.json"   # offer id -> day it was first shown in the app
SCORES_PATH = ROOT / "data" / "notes_offres.json"  # offer id -> {score, reason}, scored by the app
DESC_CACHE_PATH = ROOT / "data" / "descriptions.json"  # offer id -> description already downloaded
DESC_UNAVAILABLE = ("(description complète indisponible pour le moment : le site limite les accès. "
                    "Base-toi sur l'intitulé, l'entreprise et le lieu, sans inventer de détails sur le poste.)")
LOG_PATH = ROOT / "logs" / "linkedin.log"
GITHUB_METRICS = ROOT / "docs" / "cdi_metrics.jsonl"
VIE_METRICS = ROOT / "docs" / "metrics.jsonl"
LOCAL_METRICS = ROOT / "logs" / "cdi_metrics_linkedin.jsonl"

PARIS = ZoneInfo("Europe/Paris")
STATUSES = ["À regarder", "Candidaté", "Entretien", "Refusé", "Pas intéressé"]
LEGACY_STATUS = {"Relance à faire": "Candidaté"}  # removed status, older follow-ups map to this
DEFAULT_STATUS = STATUSES[0]
SNAPSHOT_FIELDS = ("title", "company", "location", "contract", "url", "source",
                   "posted", "first_seen", "cv", "reason", "relevancy_check")

# Environment of a local LinkedIn run (same values as windows/run_linkedin.ps1)
LOCAL_RUN_ENV = {
    "CDI_SOURCES": "linkedin,apec",
    "CDI_STORE_PATH": str(Path("data") / "cdi_offers_linkedin.json"),
    "CDI_STATE_PATH": str(Path("data") / "cdi_state_linkedin.json"),
    "CDI_METRICS_PATH": str(Path("logs") / "cdi_metrics_linkedin.jsonl"),
    "FORCE_RUN": "1",
    "PYTHONUTF8": "1",
    "PYTHONUNBUFFERED": "1",
}


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def now_str():
    return datetime.now(PARIS).strftime("%Y-%m-%d %H:%M")


def load_suivi(path=None):
    return _read_json(path or SUIVI_PATH, {})


def save_suivi(suivi, path=None):
    path = Path(path or SUIVI_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(suivi, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def vie_offer(vie_id, o):
    """Business France VIE store entry -> the app's common offer shape."""
    desc = "\n\n".join(x for x in [o.get("missionDescription"), o.get("missionProfile")] if x)
    city = (o.get("cityName") or "").strip()
    city = " ".join(city.split())  # BF pads city names ("MIAMI        -FL-")
    return {
        "id": VIE_PREFIX + str(vie_id),
        "source": "VIE",
        "title": o.get("missionTitle") or "",
        "company": o.get("organizationName") or "",
        "location": ", ".join(x for x in [city, (o.get("countryName") or "").title()] if x),
        "contract": "VIE",
        "url": VIE_URL.format(id=vie_id),
        "posted": o.get("startBroadcastDate") or "",
        "description": desc,
        "relevancy_check": o.get("relevancy_check", "unchecked"),
        "reason": o.get("reason") or "",
        "score": o.get("score"),
        "cv": "vie_" + guess_lang(f"{o.get('missionTitle') or ''} {desc}"),
    }


def mark_seen(offer_ids, path=None, today=None):
    """Remember the first day each offer was shown in the app. Returns {id: 'YYYY-MM-DD'}."""
    path = Path(path or SEEN_PATH)
    seen = _read_json(path, {})
    day = (today or datetime.now(PARIS).date()).isoformat()
    new = {oid: day for oid in offer_ids if oid not in seen}
    if new:
        seen.update(new)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(seen, indent=0), encoding="utf-8")
        tmp.replace(path)
    return seen


_SCORES_LOCK = threading.Lock()


def load_scores(path=None):
    return _read_json(path or SCORES_PATH, {})


def save_score(oid, score, reason, path=None):
    """Store a score given by the app (kept apart from the follow-up, so scoring an offer
    does not count as having touched it)."""
    path = Path(path or SCORES_PATH)
    with _SCORES_LOCK:
        scores = _read_json(path, {})
        scores[oid] = {"score": score, "reason": reason or ""}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(scores, ensure_ascii=False, indent=0), encoding="utf-8")
        tmp.replace(path)


def load_offers(store_paths=None, suivi=None, vie_path=None, scores_path=None):
    """All offers (CDI stores + VIE store + followed offers that expired), newest first."""
    store_paths = (GITHUB_STORE, LOCAL_STORE) if store_paths is None else store_paths
    suivi = suivi if suivi is not None else load_suivi()
    offers = {}
    for p in store_paths:
        for oid, o in _read_json(p, {}).items():
            offers[oid] = {**o, "id": oid}
    for vid, o in _read_json(vie_path or VIE_STORE, {}).items():
        v = vie_offer(vid, o)
        offers[v["id"]] = v

    for oid, sc in load_scores(scores_path).items():
        if oid in offers and offers[oid].get("score") is None and sc.get("score") is not None:
            offers[oid]["score"] = sc["score"]
            offers[oid]["reason"] = sc.get("reason") or offers[oid].get("reason", "")

    for oid, entry in suivi.items():
        if oid not in offers and entry.get("offer"):
            offers[oid] = {**entry["offer"], "id": oid, "expired": True}

    for oid, o in offers.items():
        s = suivi.get(oid, {})
        o["status"] = LEGACY_STATUS.get(s.get("status"), s.get("status", DEFAULT_STATUS))
        o["note"] = s.get("note", "")
        o["letter"] = s.get("letter", "")
        o["prep"] = s.get("prep", "")
        if s.get("score") is not None:          # scored later from the app
            o["score"], o["reason"] = s["score"], s.get("score_reason") or o.get("reason", "")
        o["status_updated"] = s.get("updated", "")

    return sorted(offers.values(), key=lambda o: (o.get("posted") or o.get("first_seen") or ""), reverse=True)


def update_suivi(suivi, offer, **fields):
    """Set status / note / letter for an offer, keeping a snapshot of it."""
    entry = suivi.setdefault(offer["id"], {})
    entry.update({k: v for k, v in fields.items() if v is not None})
    entry["offer"] = {k: offer.get(k) for k in SNAPSHOT_FIELDS if offer.get(k) is not None}
    entry["updated"] = now_str()
    return entry


def read_metrics(path, source_label):
    rows = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return rows
    for line in lines:
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        new = r.get("new", 0)
        if isinstance(new, dict):
            new = sum(new.values())
        rows.append({
            "Date": (r.get("timestamp") or "")[:16].replace("T", " "),
            "Où": source_label,
            "Nouvelles offres": new,
            "Retenues": r.get("relevant", 0),
            "Envoyées": r.get("sent", r.get("relevant", 0)),
            "Bloqué": ", ".join(r.get("blocked", [])) or "",
            "Erreurs": r.get("errors", 0),
            "Durée (s)": r.get("total_time", ""),
        })
    return rows


def tail(path, n=80):
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return ""
    return "\n".join(lines[-n:])


def local_run_env():
    env = dict(os.environ)
    env.update(LOCAL_RUN_ENV)
    return env


def fetch_description(offer, cache_path=None):
    """Description of an offer: from the local cache, else downloaded again (the public store
    does not keep it) and cached. Returns "" when the site refuses (LinkedIn 429...)."""
    cache_path = Path(cache_path or DESC_CACHE_PATH)
    cache = _read_json(cache_path, {})
    if cache.get(offer["id"]):
        return cache[offer["id"]]
    try:
        desc = _download_description(offer)
    except Exception:
        return ""
    if desc:
        cache[offer["id"]] = desc
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cache_path)
    return desc


def _download_description(offer):
    from .sources import apec, francetravail, hellowork, linkedin
    from .sources.common import get_html, new_session

    session = new_session()
    oid = offer["id"]
    if oid.startswith(hellowork.PREFIX):
        html = get_html(session, offer["url"])
        return hellowork.parse_offer_page(html)[0] if html else ""
    if oid.startswith(francetravail.PREFIX):
        try:
            return francetravail.fetch_description(session, oid[len(francetravail.PREFIX):])
        except Exception:
            return ""
    if oid.startswith(apec.PREFIX):
        return apec.parse_detail(apec._get_json(session, apec.DETAIL_URL, {"numeroOffre": oid[len(apec.PREFIX):]}))
    if oid.startswith(linkedin.PREFIX):
        html = get_html(session, linkedin.DETAIL_URL.format(id=oid[len(linkedin.PREFIX):]))
        if not html:
            return ""
        desc, criteria = linkedin.parse_detail_page(html)
        return (desc + "\n\n" + "\n".join(criteria)).strip()
    return ""


def generate_letter(offer, handler, profile, description=None):
    from .cdi_relevance import letter_prompt

    if description is None:
        description = offer.get("description") or fetch_description(offer)
    full = {**offer, "description": description or DESC_UNAVAILABLE}
    from . import candidat
    cv = offer.get("cv") or candidat.default_cv()
    if cv.startswith("vie_") or cv not in candidat.cvs():
        cv = candidat.default_cv()  # VIE offers: the angle of the first (main) CV
    letter = letter_prompt(full, profile, cv)
    if offer.get("source") == "VIE" and offer.get("cv") == "vie_en":
        letter = letter.replace("Rédige en français", "Write in English", 1) + (
            "\n\nIMPORTANT: the offer is in English, so write the whole letter in English "
            f"(start with \"Dear Hiring Manager,\" and {candidat.signature_rule('en')}).")
    best = ""
    for _ in range(3):   # an answer cut short (Gemini hiccup) is asked again
        text = handler.generate(letter).strip()
        if len(text) > len(best):
            best = text
        if letter_is_complete(text):
            return text
    if len(best) < 300:
        raise RuntimeError("Gemini a renvoyé une lettre incomplète, réessaie dans un instant.")
    return best


def letter_is_complete(text):
    from . import candidat
    t = text.strip()
    if len(t) < 600:
        return False
    words = [w for w in candidat.nom().split() if len(w) > 1]
    if words:
        return any(w in t[-120:] for w in words)
    return t[-1:] not in (",", ":", ";") and len(t.splitlines()[-1]) < 80  # ends on a short closing line



def interview_prompt(offer, profile, description=""):
    from .cdi_relevance import offer_text
    full = {**offer, "description": description or offer.get("description") or "(pas de description disponible)"}
    return (
        "Tu prépares un jeune diplômé à un entretien d'embauche. Réponds en français, en markdown, "
        "de façon concrète et concise (une page maximum).\n"
        "Règles : n'invente RIEN sur l'entreprise au-delà de ce que dit l'offre (si l'offre est vague, dis "
        "ce qu'il faut aller vérifier sur son site) ; n'invente aucune expérience au candidat, appuie-toi "
        "uniquement sur son profil.\n\n"
        "Structure :\n"
        "### Le poste en bref\n(3 à 5 puces : missions, attentes, ce qui compte vraiment pour eux)\n"
        "### Les 8 questions probables\n(pour chacune, une piste de réponse en 1 à 2 phrases tirée de son parcours)\n"
        "### Tes 3 atouts à mettre en avant\n"
        "### Les points faibles qu'on risque de te pointer, et quoi répondre\n"
        "### 3 questions à poser au recruteur\n"
        "### À vérifier avant l'entretien\n(sur le site de l'entreprise, LinkedIn...)\n\n"
        "=== PROFIL DU CANDIDAT ===\n" + profile + "\n\n=== OFFRE ===\n" + offer_text(full)
    )


def generate_interview_prep(offer, handler, profile, description=None):
    if description is None:
        description = offer.get("description") or ""
        if not description and offer.get("id", "").split("_")[0] in ("hw", "li", "apec", "ft"):
            try:
                description = fetch_description(offer)
            except Exception:
                description = ""
    return handler.generate(interview_prompt(offer, profile, description)).strip()


def check_for_updates(state, signature, pull, clear, now=None):
    """One auto-refresh tick. First call only records the current state; later calls fetch
    updates (pull, clear caches) and return True when the data signature changed."""
    if "data_sig" not in state:
        state["data_sig"] = signature()
        return False
    pull()
    clear()
    state["last_auto_check"] = (now or now_str)()[-5:]
    sig = signature()
    if sig != state["data_sig"]:
        state["data_sig"] = sig
        return True
    return False


def score_offer(offer, handler, profile, description=None):
    """Score an offer already in the app (offers found before scores existed). Returns (score, reason)."""
    from . import feedback
    from .cdi_relevance import parse_score, parse_verdict, relevance_prompt
    if description is None:
        description = offer.get("description") or ""
        if not description and offer.get("id", "").split("_")[0] in ("hw", "li", "apec", "ft"):
            try:
                description = fetch_description(offer)
            except Exception:
                description = ""
    answer = handler.generate(relevance_prompt({**offer, "description": description}, profile,
                                               feedback_block=feedback.prompt_block(lang="fr")))
    return parse_score(answer), parse_verdict(answer)[2]


def needs_score(offer):
    return offer.get("score") is None and offer.get("status", DEFAULT_STATUS) == DEFAULT_STATUS


def score_missing(offers, handler, profile, state, save=None, pause=1.0):
    """Background job: give a score to every offer that has none. `state` (a dict shared with
    the app) gets running / done / total / failed so the page can show progress."""
    save = save or save_score
    todo = [o for o in offers if needs_score(o) and o["id"] not in state.setdefault("failed", set())]
    state.update(running=True, done=0, total=len(todo))
    try:
        for o in todo:
            try:
                score, why = score_offer(o, handler, profile)
                if score is None:
                    state["failed"].add(o["id"])
                else:
                    save(o["id"], score, why)
            except Exception:
                state["failed"].add(o["id"])
            state["done"] += 1
            if pause:
                import time
                time.sleep(pause)
    finally:
        state["running"] = False
        state["finished"] = state.get("finished", 0) + 1


def start_scoring(offers, handler, profile, state):
    """Start score_missing in a thread unless one is already running. Returns True if started."""
    with state.setdefault("lock", threading.Lock()):
        if state.get("running") or not any(needs_score(o) and o["id"] not in state.get("failed", set())
                                           for o in offers):
            return False
        state["running"] = True
    threading.Thread(target=score_missing, args=(offers, handler, profile, state),
                     name="notation-auto", daemon=True).start()
    return True
