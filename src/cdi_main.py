"""CDI Watcher: HelloWork + France Travail + APEC + LinkedIn -> Gemini filter -> Telegram (+ cover letter draft).

Runs independently from the VIE watcher (src/main.py) and keeps its own store
(data/cdi_offers.json) and metrics (docs/cdi_metrics.jsonl).
Secrets come from environment variables (set by the GitHub workflow):
  GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
  CDI_USER_DESCRIPTION (falls back to USER_DESCRIPTION).
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

from . import dedupe, feedback
from .cdi_relevance import check_offers, cv_text
from .gemini_handler import GeminiHandler
from .metrics import ErrorCounter
from .sources import apec, francetravail, hellowork, linkedin
from .sources.common import SourceBlocked, new_session
from .store import load_offers, save_offers
from .telegram import enabled as telegram_enabled, escape_html, send_message

log = logging.getLogger(__name__)

PARIS = ZoneInfo("Europe/Paris")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "cdi_search.yaml"
STORE_PATH = PROJECT_ROOT / "data" / "cdi_offers.json"
STATE_PATH = PROJECT_ROOT / "data" / "cdi_state.json"
METRICS_PATH = PROJECT_ROOT / "docs" / "cdi_metrics.jsonl"

TELEGRAM_MAX_RETRIES = 5
TELEGRAM_DELAY = 5
TELEGRAM_LIMIT = 4000

SOURCES = {"hellowork": hellowork, "francetravail": francetravail, "apec": apec, "linkedin": linkedin}
error_counter = ErrorCounter()


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger().addHandler(error_counter)


def load_settings(path=SETTINGS_PATH):
    with open(path, encoding="utf-8") as f:
        settings = yaml.safe_load(f)
    if not settings.get("keywords"):
        raise ValueError("cdi_search.yaml: 'keywords' must list at least one keyword.")
    return settings


def load_dotenv(path=None):
    """Minimal .env reader for local (Windows) runs: KEY=value lines, # comments."""
    path = path or PROJECT_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def apply_local_overrides():
    """Let a local run use its own store/state/metrics files (see windows/)."""
    global STORE_PATH, STATE_PATH, METRICS_PATH
    load_dotenv()
    for var, name in (("CDI_STORE_PATH", "STORE_PATH"), ("CDI_STATE_PATH", "STATE_PATH"),
                      ("CDI_METRICS_PATH", "METRICS_PATH")):
        if os.environ.get(var):
            p = Path(os.environ[var])
            globals()[name] = p if p.is_absolute() else PROJECT_ROOT / p


def read_profile_file():
    path = Path(os.environ.get("CDI_PROFILE_FILE") or PROJECT_ROOT / "profile_cdi.txt")
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if path.exists():
        return path.read_text(encoding="utf-8-sig").strip() or None
    return None


def selected_sources(settings):
    """CDI_SOURCES=linkedin (comma list) forces the sources; otherwise the 'enabled' flags."""
    forced = os.environ.get("CDI_SOURCES")
    if forced:
        names = [n.strip().lower() for n in forced.split(",") if n.strip()]
        unknown = [n for n in names if n not in SOURCES]
        if unknown:
            raise ValueError(f"Unknown source(s) in CDI_SOURCES: {unknown}")
        return names
    return [n for n in SOURCES if settings.get(n, {}).get("enabled", True)]


def load_env():
    profile = (os.environ.get("CDI_USER_DESCRIPTION") or read_profile_file()
               or os.environ.get("USER_DESCRIPTION"))
    env = {
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY"),
        "TELEGRAM_BOT_TOKEN": os.environ.get("TELEGRAM_BOT_TOKEN"),
        "TELEGRAM_CHAT_ID": os.environ.get("TELEGRAM_CHAT_ID"),
        "USER_PROFILE": profile,
    }
    optional = () if telegram_enabled() else ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
    missing = [k for k, v in env.items() if not v and k not in optional]
    if missing:
        raise ValueError(f"Missing environment variables: {', '.join(missing)}")
    return env


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def should_run(settings, state, now):
    """Run once per configured hour, on weekdays."""
    if now.weekday() >= 5 or now.hour not in settings.get("run_hours", []):
        return False
    slot = now.strftime("%Y-%m-%dT%H")
    return state.get("last_slot") != slot


def drop_old(offers, since):
    kept = {}
    for oid, o in offers.items():
        ref = o.get("posted") or o.get("first_seen")
        try:
            d = datetime.fromisoformat(ref).date() if ref else None
        except ValueError:
            d = None
        if d is None or d >= since:
            kept[oid] = o
    return kept


def format_offer(offer):
    lines = [
        f"<b>{escape_html(offer['title'])}</b>",
        " — ".join(x for x in [escape_html(offer["company"]), escape_html(offer["location"])] if x),
        " · ".join(x for x in [escape_html(offer.get("contract")), offer["source"],
                               ("publiée le " + offer["posted"]) if offer.get("posted") else ""] if x),
    ]
    if offer.get("reason"):
        lines.append("✅ " + escape_html(offer["reason"]))
    lines.append("📄 " + escape_html(cv_text(offer.get("cv"))))
    lines.append(offer["url"])
    return "\n".join(l for l in lines if l)


def format_letter(offer):
    letter = offer.get("letter") or ""
    if not letter:
        return None
    header = "✉️ <b>Brouillon de lettre</b> (à relire et adapter)\n"
    body = escape_html(letter)
    room = TELEGRAM_LIMIT - len(header) - len("<pre></pre>")
    if len(body) > room:
        body = body[:room - 3] + "..."
    return header + "<pre>" + body + "</pre>"


def send_with_retry(text, env):
    for attempt in range(1, TELEGRAM_MAX_RETRIES + 1):
        try:
            send_message(text, env)
            return True
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            log.warning(f"TELEGRAM WARNING - HTTP {status} (attempt {attempt}/{TELEGRAM_MAX_RETRIES})")
        except requests.exceptions.RequestException as e:
            log.warning(f"TELEGRAM WARNING - {e} (attempt {attempt}/{TELEGRAM_MAX_RETRIES})")
        time.sleep(TELEGRAM_DELAY)
    log.error("TELEGRAM ERROR - message could not be sent.")
    return False


def notify(relevant, env):
    sent = 0
    for offer in relevant.values():
        if send_with_retry(format_offer(offer), env):
            sent += 1
            letter = format_letter(offer)
            if letter:
                time.sleep(1)
                send_with_retry(letter, env)
        time.sleep(1)
    return sent


PUBLIC_STORE = PROJECT_ROOT / "data" / "cdi_offers.json"


def slim(offers, keep_descriptions=False):
    """Keep the public store small and free of personal text (letters). The PC's own store
    (not on GitHub) keeps descriptions, so letters never need to download them again."""
    for o in offers.values():
        if o.get("relevancy_check") != "unchecked" and not keep_descriptions:
            o.pop("description", None)
        o.pop("letter", None)
    return offers


def append_metrics(record, path=None):
    path = path or METRICS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run():
    t0 = time.time()
    setup_logging()
    apply_local_overrides()
    force = os.environ.get("FORCE_RUN") == "1"
    now = datetime.now(PARIS)

    settings = load_settings()
    state = load_state()
    if not force and not should_run(settings, state, now):
        log.info("CDI watcher: outside its run hours (or already ran this hour), skipping.")
        return

    env = load_env()
    today = now.date()
    since = today - timedelta(days=settings.get("max_days", 21))
    stored = load_offers(STORE_PATH)
    log.info(f"{len(stored)} CDI offers already known.")

    # ---------------- Scraping
    session = new_session()
    scraped, per_source, blocked = {}, {}, []
    for name in selected_sources(settings):
        module = SOURCES[name]
        try:
            found = module.scrape(session, settings, stored.keys() | scraped.keys(), since, today=today)
        except SourceBlocked as e:
            log.warning(f"{name}: blocked by the site ({e}); skipping it this run.")
            blocked.append(name)
            found = {}
        except Exception:
            log.exception(f"SCRAPING ERROR - {name} failed")
            found = {}
        for o in found.values():
            o["first_seen"] = today.isoformat()
        per_source[name] = len(found)
        scraped.update(found)
    log.info(f"New offers: {per_source}")

    # Same job from several boards (or already in the other store, GitHub <-> PC): judge it once
    known = dict(stored)
    for other in (PROJECT_ROOT / "data" / "cdi_offers.json", PROJECT_ROOT / "data" / "cdi_offers_linkedin.json"):
        if other.exists() and other.resolve() != STORE_PATH.resolve():
            known.update(load_offers(other))
    n_dup = dedupe.mark_duplicates(scraped, known)
    if n_dup:
        log.info(f"{n_dup} duplicate offer(s) already seen on another board: not judged again.")

    merged = {**stored, **scraped}

    # ---------------- Relevance (+ letters)
    handler = GeminiHandler(env["GEMINI_API_KEY"], [{"name": m} for m in settings["gemini_models"]])
    relevant = check_offers(
        merged, env["USER_PROFILE"], handler,
        max_checks=settings.get("max_checks_per_run", 120),
        save_func=lambda offers: save_offers(offers, STORE_PATH),
        draft_letters=settings.get("draft_cover_letter", True),
        max_years=settings.get("max_experience_years", 3),
        excluded_domains=settings.get("excluded_domains") or [],
        feedback_block=feedback.prompt_block(lang="fr"),
    )
    log.info(f"{len(relevant)} relevant offer(s).")

    # ---------------- Telegram
    sent = notify(relevant, env) if relevant and telegram_enabled() else 0

    # CDI_STORE_PATH is only set by the PC runs (windows/), whose store never goes to GitHub
    merged = slim(drop_old(merged, since), keep_descriptions=bool(os.environ.get("CDI_STORE_PATH"))
                  and STORE_PATH.resolve() != PUBLIC_STORE.resolve())
    save_offers(merged, STORE_PATH)
    state["last_slot"] = now.strftime("%Y-%m-%dT%H")
    save_state(state)

    append_metrics({
        "timestamp": now.isoformat(timespec="seconds"),
        "new": per_source,
        "duplicates": n_dup,
        "blocked": blocked,
        "relevant": len(relevant),
        "sent": sent,
        "stored": len(merged),
        "unchecked": sum(1 for o in merged.values() if o.get("relevancy_check") == "unchecked"),
        "errors": error_counter.count,
        "total_time": round(time.time() - t0, 1),
    })
    log.info(f"CDI run complete: {sum(per_source.values())} new, {len(relevant)} relevant, {sent} sent.")

    if sys.platform == "win32":   # on the PC: Windows notification for everything new (all sources)
        try:
            from . import winnotify
            n = winnotify.notify_new_offers()
            if n:
                log.info(f"Windows notification: {n} new offer(s).")
        except Exception as e:
            log.warning(f"Windows notification failed: {e}")


if __name__ == "__main__":
    run()
