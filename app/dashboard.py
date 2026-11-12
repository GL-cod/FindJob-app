"""« Mes candidatures » — local app for the CDI watcher.

Start it with windows/start_app.ps1 (desktop shortcut), or:
    .venv\\Scripts\\python -m streamlit run app/dashboard.py
"""
import hashlib
import os
import time
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import reloader  # noqa: E402

reloader.reload_if_changed(ROOT / "src")  # code updated by a git pull while the app runs -> fresh modules

from src import candidat, cdi_main, feedback, gitsync, reseau, reseau_ui, sheets, stats, tracking  # noqa: E402
try:
    from src import letter_docx  # needs python-docx (requirements-app.txt)
except ImportError:
    letter_docx = None
try:
    from src import cv_pptx  # needs python-pptx (requirements-app.txt)
except ImportError:
    cv_pptx = None
from src.gemini_handler import GeminiHandler  # noqa: E402

SCHEDULE_TEXT = ("ainsi : VIE toutes les heures de 8h à 20h en semaine (GitHub), HelloWork et France Travail à 12h et 19h (GitHub), "
                 "LinkedIn et APEC à 12h05 et 19h05 (sur ce PC, allumé et session ouverte)")
STATUS_ICONS = {"À regarder": "🔵", "Candidaté": "📨", "Entretien": "🗓️",
                "Refusé": "❌", "Pas intéressé": "⚪"}
SOURCE_ICONS = {"HelloWork": "🟣", "France Travail": "🟢", "LinkedIn": "🔷", "VIE": "🌍", "APEC": "🟠"}
SOURCES = ["VIE", "HelloWork", "France Travail", "APEC", "LinkedIn"]
AUTO_REFRESH_MINUTES = 15
PAGE_SIZE = 25
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]
SORTS = ["Meilleure note d'abord", "Plus récentes d'abord", "Nouvelles dans l'application d'abord",
         "Entreprise (A → Z)"]
HIDE_AFTER_DAYS = 14  # offers left « À regarder » this long after first shown in the app are hidden

st.set_page_config(page_title="Mes candidatures", page_icon="💼", layout="wide")
# No greying of the page while it updates after a click
st.markdown("<style>[data-stale='true'], .stale-element { opacity: 1 !important; transition: none !important; "
            "filter: none !important; }</style>", unsafe_allow_html=True)
cdi_main.load_dotenv()
SHEETS_ON = sheets.configured()
IS_DARK = True  # the app only has a dark theme (.streamlit/config.toml)


# ----------------------------------------------------------------- helpers
@st.cache_resource
def update_state():
    """Shared by every run: set when a pull brought a new version of the app's code."""
    return {}


@st.cache_resource
def background():
    """Slow work (Google Sheets, git push) done after the click, so the page answers at once."""
    import queue
    import threading
    return {"queue": queue.Queue(), "done": [], "git_lock": threading.Lock(), "thread": None, "busy": 0}


def _background_worker(state):
    while True:
        fn, after = state["queue"].get()
        try:
            msg = fn()
        except Exception as e:
            msg = f"⚠️ {e}"
        try:
            if after:
                after()
        except Exception:
            pass
        state["busy"] -= 1
        if msg:
            state["done"].append(msg)


def run_later(fn, after=None):
    """fn() runs in the background (one task at a time, in order); its return value is shown as a toast."""
    import threading
    state = background()
    if state["thread"] is None or not state["thread"].is_alive():
        state["thread"] = threading.Thread(target=_background_worker, args=(state,), name="arriere-plan",
                                           daemon=True)
        state["thread"].start()
    state["busy"] += 1
    state["queue"].put((fn, after))


@st.fragment(run_every=2)
def background_watch():
    """Shows what the background tasks finished, and refreshes the page (counters, Sheets)."""
    state = background()
    if state["done"]:
        st.session_state.setdefault("toasts", []).extend(state["done"])
        state["done"].clear()
        st.rerun(scope="app")
    gen = SHEET["gen"]
    if st.session_state.setdefault("sheet_gen", gen) != gen:   # the Google Sheet was read again
        st.session_state.sheet_gen = gen
        st.rerun(scope="app")


@st.cache_resource
def repo_url():
    return gitsync.repo_url(ROOT)


@st.cache_data(ttl=900, show_spinner=False)
def app_version():
    return gitsync.last_update(ROOT)


def tracked_pull():
    """git pull, remembering when it brought new app code (not just new offers)."""
    with background()["git_lock"]:
        before = gitsync.head(ROOT)
        ok, out = gitsync.pull(ROOT)
        after = gitsync.head(ROOT)
        if gitsync.code_changed(ROOT, before, after):
            update_state()["pending"] = True
            app_version.clear()
    return ok, out


def startup_pull():
    """git pull done in the background when the window opens: the page shows the offers already
    on the PC at once, and reloads by itself if GitHub had new ones."""
    before = gitsync.head(ROOT)
    tracked_pull()
    return "🔄 Nouvelles données récupérées depuis GitHub" if gitsync.head(ROOT) != before else None


def restart_server():
    """Restart the app's server in the background; the open window reconnects by itself.

    The restart script must outlive the server it kills. A process started by the server
    would die with it (the venv's python.exe keeps its children in a Windows job object), so it
    is created through WMI (Win32_Process.Create), which makes it independent of the server."""
    update_state().pop("pending", None)
    if sys.platform != "win32":
        return True, ""
    import base64
    script = str(ROOT / "windows" / "start_app.ps1")
    inner = f'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{script}" -Restart'
    q = lambda t: t.replace("'", "''")
    ps = (f"$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments "
          f"@{{CommandLine = '{q(inner)}'; CurrentDirectory = '{q(str(ROOT))}'}}; exit [int]$r.ReturnValue")
    enc = base64.b64encode(ps.encode("utf-16-le")).decode()
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", enc],
                           capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode == 0:
            return True, ""
        err = (r.stderr or r.stdout or f"code {r.returncode}").strip()
    except Exception as e:
        err = str(e)
    # fallback: leave the job object explicitly
    try:
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                 | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000))
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
                          "-File", script, "-Restart"], cwd=str(ROOT), creationflags=flags, close_fds=True)
        return True, ""
    except Exception as e:
        return False, f"{err} / {e}"


def sync_github(show=True):
    ok, out = tracked_pull()
    if show:
        (st.success if ok else st.error)("Synchronisé avec GitHub." if ok else f"Échec de la synchronisation : {out}")
    return ok


@st.cache_resource
def gemini_and_profile():
    cdi_main.load_dotenv()
    import os
    settings = cdi_main.load_settings()
    key = os.environ.get("GEMINI_API_KEY")
    profile = os.environ.get("CDI_USER_DESCRIPTION") or cdi_main.read_profile_file()
    if not key or not profile:
        return None, None
    return GeminiHandler(key, [{"name": m} for m in settings["gemini_models"]]), profile


SHEET_CACHE = ROOT / "data" / "sheet_cache.json"   # last copy of the Google Sheet (this PC only)
SHEET_TTL = 300


@st.cache_resource
def sheet_store():
    """Last copy of the Google Sheet, shared by every run; refreshed in a background thread."""
    import threading
    return {"data": None, "fetched_at": 0.0, "fetching": False, "gen": 0, "lock": threading.Lock()}


SHEET = sheet_store()


def _fetch_sheet():
    read_at = tracking.now_str()[-5:]
    if not SHEETS_ON:
        return {"rows": [], "sheet_url": "", "version": 0, "error": None, "read_at": read_at}
    try:
        data = sheets.fetch_sheet()
        return {"rows": data["rows"], "sheet_url": data["sheet_url"], "version": data["version"],
                "error": None, "read_at": read_at}
    except Exception as e:
        return {"rows": [], "sheet_url": "", "version": 0, "error": str(e), "read_at": read_at}


def _store_sheet(store, data):
    import json
    if data["error"] and store["data"] and not store["data"].get("error") and store["data"]["rows"]:
        data = {**store["data"], "error": None}   # Google hiccup: keep the last good copy
    else:
        try:
            if not data["error"]:
                SHEET_CACHE.parent.mkdir(parents=True, exist_ok=True)
                tmp = SHEET_CACHE.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                tmp.replace(SHEET_CACHE)
        except OSError:
            pass
    store["data"] = data
    store["fetched_at"] = time.time()
    store["gen"] += 1


def _refresh_sheet(store):
    try:
        _store_sheet(store, _fetch_sheet())
    finally:
        store["fetching"] = False


def read_sheet():
    """The whole Google Sheet: {rows, sheet_url, version, error, read_at}.

    Never waits for Google: answers with the last copy (kept on disk, so the window opens at
    once), and reads the sheet again in the background when that copy is older than SHEET_TTL;
    the page reloads by itself when the new copy arrives (background_watch)."""
    store = SHEET
    if store["data"] is None:
        import json
        try:
            store["data"] = {**json.loads(SHEET_CACHE.read_text(encoding="utf-8")), "error": None}
        except (OSError, ValueError):
            store["data"] = {"rows": [], "sheet_url": "", "version": 0, "error": None, "read_at": "…",
                             "loading": True}
    if SHEETS_ON and time.time() - store["fetched_at"] > SHEET_TTL:
        import threading
        with store["lock"]:
            if not store["fetching"]:
                store["fetching"] = True
                threading.Thread(target=_refresh_sheet, args=(store,), name="lecture-sheets", daemon=True).start()
    return store["data"]


def _clear_sheet(wait=False):
    """Read the Google Sheet again: in the background, or at once with wait=True."""
    store = SHEET
    if wait:
        _store_sheet(store, _fetch_sheet())
    else:
        store["fetched_at"] = 0.0
        read_sheet()


read_sheet.clear = _clear_sheet


@st.cache_data(max_entries=300, show_spinner=False)
def letter_file(offer, letter, english, contact_stamp):
    return letter_docx.build(offer, letter, english=english)


@st.cache_data(max_entries=100, show_spinner=False)
def cv_file(path, stamp, changes):
    return cv_pptx.build(Path(path).read_bytes(), changes)


@st.cache_data(max_entries=100, show_spinner=False)
def cv_diff(path, stamp, changes):
    return cv_pptx.diff(Path(path).read_bytes(), changes)


def file_stamp(path):
    try:
        s = Path(path).stat()
        return s.st_size, s.st_mtime_ns
    except OSError:
        return None


def push_feedback():
    """Commit data/feedback.json and push it, so the GitHub runs (VIE, HelloWork) learn too."""
    if os.environ.get("MES_CANDIDATURES_NO_PUSH") == "1":  # tests
        return False, "push disabled"
    with background()["git_lock"]:
        return gitsync.push_file(ROOT, "data/feedback.json", "Update feedback from the app [skip ci]")


def save_rejection(offer, reason):
    feedback.record(offer, reason)
    st.toast("Noté : le filtre évitera ce genre d'offres (VIE, HelloWork, LinkedIn et APEC).")

    def send():
        ok, _ = push_feedback()
        return None if ok else ("Ton refus est noté sur ce PC ; l'envoi à GitHub sera retenté au prochain refus.")
    run_later(send)


@st.dialog("Pourquoi cette offre ne t'intéresse pas ?")
def ask_reason(offer):
    st.markdown(f"**{offer.get('title', '')}** — {offer.get('company', '')}")
    st.caption("Ta réponse aide le filtre à écarter les offres du même genre (VIE, HelloWork et LinkedIn).")
    why = st.text_input("Raison", key="dialog_reason",
                        placeholder="Ex. : trop commercial, que du support, trop loin, trop senior...")
    c1, c2 = st.columns(2)
    if c1.button("Enregistrer", type="primary", width="stretch"):
        st.session_state.pop("ask_reason", None)
        save_rejection(offer, why)
        st.rerun()
    if c2.button("Passer", width="stretch"):
        st.session_state.pop("ask_reason", None)
        save_rejection(offer, "")
        st.rerun()


def open_external(url):
    """Open a link in the PC's default browser , not in the app window."""
    if not url:
        return
    try:
        if sys.platform == "win32":
            os.startfile(url)  # same as double-clicking a link: default browser
        else:
            webbrowser.open(url)
        st.toast("Ouvert dans ton navigateur ↗")
    except Exception as e:
        st.toast(f"⚠️ Impossible d'ouvrir le lien : {e}")


def save_field(offer, **fields):
    suivi = tracking.load_suivi()
    tracking.update_suivi(suivi, offer, **fields)
    tracking.save_suivi(suivi)


def render_cv(o, handler, profile):
    """CV section of an offer: model choice, generation by Gemini, download and changes."""
    models = cv_pptx.available_models()
    done = o.get("cv_adapte") or {}
    default = done.get("modele") if done.get("modele") in models else cv_pptx.model_for_offer(o)
    model = default
    if len(models) > 1:
        model = st.radio("Modèle", models, index=models.index(default), horizontal=True,
                         format_func=lambda k: candidat.cv_label(k) or k, key=f"cvmodel_{o['id']}",
                         label_visibility="collapsed")
    path = cv_pptx.model_path(done.get("modele")) if done else None
    if done and path:
        changes = done.get("modifications") or {}
        c1, c2 = st.columns([1, 2])
        c1.download_button(
            "⬇️ Télécharger le CV (.pptx)", data=cv_file(str(path), file_stamp(path), changes),
            file_name=cv_pptx.file_name(o, candidat.nom()), mime=cv_pptx.MIME,
            key=f"cvdl_{o['id']}", width="stretch")
        c2.caption(f"À partir de « {candidat.cv_label(done['modele']) or done['modele']} ». Ouvre-le dans "
                   "PowerPoint, relis-le, puis Fichier → Exporter en PDF avant d'envoyer.")
        if done.get("resume"):
            st.markdown(f"💬 _{done['resume']}_")
        with st.popover(f"Voir les {len(changes)} modification(s)"):
            for before, after in cv_diff(str(path), file_stamp(path), changes):
                st.markdown(f"~~{before}~~  \n→ {after}")
    elif done:
        st.caption("Le modèle utilisé pour ce CV a été supprimé : génère-le à nouveau.")
    if handler is not None and st.button("Régénérer le CV" if done else "Générer le CV adapté", key=f"cvgen_{o['id']}"):
        with st.spinner("Adaptation du CV à l'offre..."):
            try:
                desc = o.get("description") or tracking.fetch_description(o)
                save_field(o, cv_adapte=tracking.generate_cv(o, handler, profile, model, description=desc))
                st.rerun()
            except Exception as e:
                st.error(f"Impossible d'adapter le CV : {e}")


def mark_todo(offer):
    st.session_state[f"status_{offer['id']}"] = "À regarder"
    on_status_change(offer)


def mark_rejected(offer):
    st.session_state[f"status_{offer['id']}"] = "Pas intéressé"
    on_status_change(offer)


def mark_applied(offer):
    st.session_state[f"status_{offer['id']}"] = "Candidaté"
    on_status_change(offer)


def on_status_change(offer):
    new = st.session_state[f"status_{offer['id']}"]
    previous = offer.get("status")
    save_field(offer, status=new)
    if new == "Pas intéressé":
        feedback.record(offer, "")              # kept locally at once; reason + push from the dialog
        st.session_state.ask_reason = offer
    elif previous == "Pas intéressé":
        feedback.forget(offer["id"])
        run_later(lambda: (push_feedback(), None)[1])
    title = offer["title"][:40]
    st.toast(f"« {title} » → {new}")
    if SHEETS_ON and new in sheets.RETOUR:
        note = offer.get("note") or None
        snapshot = dict(offer)

        def send():
            try:
                res = sheets.push(snapshot, new, note=note)
            except Exception as e:
                return f"⚠️ « {title} » : Google Sheets non mis à jour ({e})"
            return f"📗 « {title} » " + ("ajoutée au Google Sheets" if res.get("created") else "mise à jour dans Google Sheets")
        run_later(send, after=read_sheet.clear)


def run_search_live(placeholder):
    """Run the LinkedIn search and stream its output into the page and the log file."""
    tracking.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    with open(tracking.LOG_PATH, "a", encoding="utf-8") as log:
        header = f"\n===== {tracking.now_str()} (lancé depuis l'application) ====="
        log.write(header + "\n")
        proc = subprocess.Popen(
            [sys.executable, "-m", "src.cdi_main"], cwd=ROOT, env=tracking.local_run_env(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        )
        for line in proc.stdout:
            log.write(line)
            log.flush()
            lines.append(line.rstrip())
            placeholder.code("\n".join(lines[-40:]), language=None)
        proc.wait()
    return proc.returncode


def data_signature():
    """Fingerprint of everything the page shows: offer stores, follow-up file, Google Sheet."""
    h = hashlib.sha1()
    for p in (tracking.GITHUB_STORE, tracking.LOCAL_STORE, tracking.VIE_STORE, tracking.SUIVI_PATH,
              tracking.SCORES_PATH):
        try:
            stat = p.stat()
            h.update(f"{p.name}:{stat.st_size}:{stat.st_mtime_ns};".encode())
        except FileNotFoundError:
            h.update(f"{p.name}:none;".encode())
    data = read_sheet()
    h.update(str([(r.get("row"), r.get("retour"), r.get("commentaire")) for r in data["rows"]]).encode())
    return h.hexdigest()


@st.cache_resource
def scoring_state():
    """Progress of the background scoring, shared by every run of the page."""
    return {}


@st.fragment(run_every=5)
def scoring_progress():
    """While offers are being scored in the background: a progress line, then one reload when done."""
    state = scoring_state()
    if state.get("running"):
        st.caption(f"⭐ Notation automatique des nouvelles offres... {state.get('done', 0)}/{state.get('total', 0)}")
    elif state.get("finished", 0) != st.session_state.get("scoring_seen", 0):
        st.session_state.scoring_seen = state.get("finished", 0)
        if state.get("total"):
            st.rerun(scope="app")


@st.fragment(run_every=AUTO_REFRESH_MINUTES * 60)
def auto_refresh():
    """Every AUTO_REFRESH_MINUTES: fetch what's new and reload the page only if something changed."""
    # The fragment also runs with every full page run (each click): only fetch when the
    # timer really fired, and treat the user's own changes as already known.
    now = time.time()
    last_tick = st.session_state.get("last_check_ts")
    if last_tick is None or now - last_tick < AUTO_REFRESH_MINUTES * 60 - 30:
        st.session_state.setdefault("last_check_ts", now)
        st.session_state.data_sig = data_signature()
    else:
        st.session_state.last_check_ts = now
        changed = tracking.check_for_updates(st.session_state, signature=data_signature,
                                             pull=tracked_pull, clear=read_sheet.clear)
        if changed:
            st.session_state.auto_refreshed = True
            st.rerun(scope="app")
    last = st.session_state.get("last_auto_check")
    st.caption(f"🔄 Actualisation automatique toutes les {AUTO_REFRESH_MINUTES} min"
               + (f" · dernière vérification à {last}" if last else ""))


# ----------------------------------------------------------------- first load
if "synced" not in st.session_state:
    st.session_state.synced = True
    run_later(startup_pull)   # in the background: the page shows what is already on the PC at once

for _msg in st.session_state.pop("toasts", []):
    st.toast(_msg)
background_watch()

suivi = tracking.load_suivi()
offers = tracking.load_offers(suivi=suivi)
sheet = read_sheet()
sheet_error = sheet["error"]
in_sheet = {r["lien"]: r.get("retour") or "" for r in sheet["rows"] if r.get("lien")}
if sheet.get("loading") and SHEETS_ON:
    st.caption("⏳ Lecture de ton Google Sheets…")
if st.session_state.pop("sheet_reloaded", False):
    if sheet_error:
        st.toast(f"⚠️ Lecture du Google Sheets impossible : {sheet_error}")
    else:
        st.toast(f"📗 Google Sheets relu à {sheet['read_at']} : {len(sheet['rows'])} candidature(s)")
for _o in offers:
    _o["in_sheet"] = in_sheet.get(sheets.norm_link(_o.get("url")))
    if _o["in_sheet"] is not None:
        _o["status"] = sheets.merged_status(_o["status"], _o["in_sheet"])
retained = [o for o in offers
            if o.get("relevancy_check") == "relevant" or o["id"] in suivi or o["in_sheet"] is not None]


seen_on = tracking.mark_seen([o["id"] for o in retained])


def is_stale(o):
    """Still « À regarder » HIDE_AFTER_DAYS days after it was first shown in the app, never touched,
    not in the Sheet."""
    if o["status"] != "À regarder" or o["id"] in suivi or o.get("in_sheet") is not None:
        return False
    try:
        first_shown = datetime.fromisoformat(seen_on[o["id"]]).date()
    except (KeyError, ValueError):
        return False
    return (datetime.now(tracking.PARIS).date() - first_shown).days > HIDE_AFTER_DAYS


stale_ids = {o["id"] for o in retained if is_stale(o)}
active = [o for o in retained if o["id"] not in stale_ids]

_ids = {o["id"] for o in active}
if st.session_state.pop("auto_refreshed", False):
    new_ids = _ids - st.session_state.get("known_ids", _ids)
    st.toast(f"🆕 {len(new_ids)} nouvelle(s) offre(s)" if new_ids else "🔄 Données mises à jour")
    if new_ids:
        try:
            from src import winnotify
            winnotify.notify_new_offers()
        except Exception:
            pass
st.session_state.known_ids = _ids

_now = datetime.now(tracking.PARIS)
_today = _now.date()
_hello = "Bonsoir" if _now.hour >= 18 else "Bonjour"
st.title("💼 Mes candidatures")
_prenom = candidat.prenom()
st.markdown(f"{_hello}{' ' + _prenom if _prenom else ''} 👋 · {JOURS[_today.weekday()]} {_today.day} {MOIS[_today.month - 1]}")
auto_refresh()


def is_new(o):
    """Shown for the first time in the app today or yesterday."""
    try:
        return (_today - datetime.fromisoformat(seen_on.get(o["id"], "")).date()).days <= 1
    except ValueError:
        return False


def fr_date(iso):
    try:
        return datetime.fromisoformat((iso or "")[:10]).strftime("%d/%m")
    except ValueError:
        return ""


with st.sidebar:
    st.markdown("### 📌 En bref")
    n_new = sum(is_new(o) and o["status"] == "À regarder" for o in active)
    n_interview = sum(o["status"] == "Entretien" for o in retained)
    st.markdown(
        f"🆕 **{n_new}** nouvelle(s) offre(s) à regarder  \n"
        f"🗓️ **{n_interview}** entretien(s) en cours"
    )
    st.divider()
    st.markdown("### ⚡ Raccourcis")
    if SHEETS_ON and not sheet_error and sheet.get("sheet_url"):
        st.button("📗 Ouvrir mon Google Sheets", on_click=open_external, args=(sheet["sheet_url"],), width="stretch")
    if st.button("🔄 Synchroniser maintenant", width="stretch",
                 help="Récupère tout de suite les nouvelles offres VIE / HelloWork et relit ton Google Sheets"):
        with st.spinner("Synchronisation..."):
            tracked_pull()
            read_sheet.clear(wait=True)
        st.session_state.auto_refreshed = True
        st.rerun()
    st.caption("La recherche LinkedIn + APEC se lance depuis l'onglet ⚙️ Activité.")
    st.divider()
    st.markdown("### ⬆️ Application")
    pending = update_state().get("pending")
    if pending:
        st.success("✨ Une nouvelle version a été téléchargée.")
    if st.button("⬆️ Mettre à jour l'application", width="stretch", type="primary" if pending else "secondary",
                 help="Récupère la dernière version depuis GitHub et redémarre l'application (10 secondes environ)"):
        with st.spinner("Téléchargement de la dernière version..."):
            ok, out = tracked_pull()
        if ok:
            started, err = restart_server()
            if started:
                st.info("🔄 L'application redémarre : la fenêtre se recharge toute seule dans 10 à 20 secondes. "
                        "Si rien ne se passe au bout d'une minute, ferme la fenêtre et rouvre l'icône.")
            else:
                st.error(f"Redémarrage automatique impossible ({err[-200:]}). La mise à jour est téléchargée : "
                         "ferme la fenêtre, lance windows\\stop_app.ps1 puis rouvre l'icône.")
        else:
            st.error(f"Mise à jour impossible : {out[-300:]}")
    _version = app_version()
    if _version:
        st.caption(f"Version du {_version}")
    st.divider()
    with st.expander("ℹ️ Légende des statuts"):
        for name, icon in STATUS_ICONS.items():
            st.markdown(f"{icon} {name}")
        st.markdown("🆕 nouvelle (arrivée aujourd'hui ou hier)  \n📗 déjà dans ton Google Sheets")
n_retained = len(active)
n_todo = sum(o["status"] == "À regarder" for o in active)
if SHEETS_ON and not sheet_error:
    summ = sheets.summary(sheet["rows"])
    sent, pending, positive, negative = summ["total"], summ["en_attente"], summ["positif"], summ["negatif"]
    week = summ["cette_semaine"]
else:
    sent = sum(o["status"] in ("Candidaté", "Entretien", "Refusé") for o in retained)
    pending = sum(o["status"] == "Candidaté" for o in retained)
    positive = sum(o["status"] == "Entretien" for o in retained)
    negative = sum(o["status"] == "Refusé" for o in retained)
    week = 0
    if sheet_error:
        st.warning(f"Google Sheets illisible pour l'instant : {sheet_error}")

m = st.columns(6)
m[0].metric("🎯 Offres retenues", n_retained, help="Offres VIE, HelloWork, France Travail, APEC et LinkedIn jugées pertinentes")
m[1].metric("🔵 À regarder", n_todo)
m[2].metric("📨 Candidatures", sent, delta=f"+{week} cette semaine" if week else None,
            help="Toutes les lignes de ton Google Sheets" if SHEETS_ON and not sheet_error else None)
m[3].metric("⏳ En attente", pending)
m[4].metric("✅ Positifs", positive)
m[5].metric("❌ Négatifs", negative)

tab_offres, tab_sheet, tab_reseau, tab_stats, tab_activite, tab_reglages = st.tabs(
    ["📋 Offres", "📗 Mes candidatures", "🤝 Réseau", "📊 Statistiques", "⚙️ Activité", "🔎 Réglages"])

# ----------------------------------------------------------------- Offres
with tab_offres:
    query = st.text_input("Rechercher", placeholder="🔍 Intitulé, entreprise, ville...", label_visibility="collapsed")
    f1, f2, f3, f4 = st.columns([3, 3, 2, 1])
    sources = f1.multiselect("Source", SOURCES, default=SOURCES)
    statuses = f2.multiselect("Statut", tracking.STATUSES, default=["À regarder", "Entretien"],
                              help="Les offres où tu as postulé sont masquées par défaut : ajoute « Candidaté » "
                                   "pour les revoir, ou va dans l'onglet 📗 Mes candidatures.")
    sort_by = f3.selectbox("Trier", SORTS)
    with f4.popover("⚙️ Plus", width="stretch"):
        show_old = st.toggle(f"Offres de plus de {HIDE_AFTER_DAYS} jours",
                             help=f"Affiche aussi les offres restées « À regarder » plus de {HIDE_AFTER_DAYS} jours "
                                  "après leur arrivée dans l'application")

    pool = retained
    if not show_old:
        pool = [o for o in pool if o["id"] not in stale_ids]
    q = query.lower().strip()
    shown = [
        o for o in pool
        if o.get("source") in sources and o["status"] in statuses
        and (not q or q in f"{o.get('title','')} {o.get('company','')} {o.get('location','')}".lower())
    ]
    if sort_by == SORTS[0]:
        shown.sort(key=lambda o: (o.get("score") is not None, o.get("score") or 0, o.get("posted") or ""),
                   reverse=True)
    elif sort_by == SORTS[2]:
        shown.sort(key=lambda o: (seen_on.get(o["id"], ""), o.get("posted") or ""), reverse=True)
    elif sort_by == SORTS[3]:
        shown.sort(key=lambda o: (o.get("company") or "").lower())

    # reset the page when filters change
    _filters = (tuple(sources), tuple(statuses), sort_by, q, show_old)
    if st.session_state.get("offer_filters") != _filters:
        st.session_state.offer_filters = _filters
        st.session_state.offer_limit = PAGE_SIZE
    limit = st.session_state.get("offer_limit", PAGE_SIZE)

    st.caption(f"{len(shown)} offre(s)"
               + (f" · {len(stale_ids)} ancienne(s) non traitée(s) masquée(s) (⚙️ Plus pour les voir)"
                  if stale_ids and not show_old else ""))
    if not shown:
        st.info("Aucune offre ne correspond à tes filtres. Essaie d'élargir la recherche ou les statuts.")
    if set(statuses) == {"À regarder", "Entretien"}:
        st.caption("Les offres où tu as postulé, refusées ou marquées « pas intéressé » sont masquées : ajoute leur statut dans "
                   "le filtre « Statut » pour les revoir.")

    rejections = feedback.load()
    handler, profile = gemini_and_profile()

    unscored = [o for o in retained if tracking.needs_score(o) and o["id"] not in stale_ids]
    if unscored and handler is not None:
        tracking.start_scoring(unscored, handler, profile, scoring_state())
    scoring_progress()
    if handler is None:
        st.sidebar.warning("Lettres et préparations d'entretien indisponibles : il manque ta clé Gemini (.env) "
                           "ou ton profil (profile_cdi.txt).")

    for o in shown[:limit]:
        badge = STATUS_ICONS.get(o["status"], "")
        src = SOURCE_ICONS.get(o.get("source"), "")
        date = fr_date(o.get("posted") or o.get("first_seen"))
        stars = f"⭐ {o['score']}/10 · " if o.get("score") is not None else ""
        label = (("🆕 " if is_new(o) and o["status"] == "À regarder" else "")
                 + f"{badge} {stars}**{o.get('title','')}** · {o.get('company','')}  —  {src} {o.get('source','')}"
                 + (f" · {date}" if date else ""))
        if o.get("expired"):
            label += " · _expirée_"
        if o.get("in_sheet") is not None:
            label += f" · 📗 déjà dans ton Sheets ({o['in_sheet'] or 'sans retour'})"

        with st.expander(label):
            left, right = st.columns([3, 2])
            with left:
                st.markdown(
                    f"📍 {o.get('location') or '—'}  \n"
                    f"📝 {o.get('contract') or 'contrat non précisé'}  \n"
                    + (f"📄 CV conseillé : **{candidat.cv_label(o['cv'])}**" if candidat.cv_label(o.get("cv")) else "")
                )
                if o.get("reason"):
                    st.markdown(f"💬 _{o['reason']}_")
                b_open, b_applied, b_no = st.columns(3)
                b_open.button("↗ Ouvrir l'offre", key=f"open_{o['id']}", on_click=open_external, args=(o["url"],),
                              type="primary", width="stretch")
                if o["status"] == "À regarder":
                    b_applied.button("✅ J'ai postulé", key=f"applied_{o['id']}", on_click=mark_applied, args=(o,),
                                     help="Passe l'offre en « Candidaté » et l'ajoute à ton Google Sheets",
                                     width="stretch")
                    b_no.button("❌ Pas intéressé", key=f"no_{o['id']}", on_click=mark_rejected, args=(o,),
                                help="Écarte l'offre ; le filtre apprendra de ta raison", width="stretch")
            with right:
                if o["status"] != "À regarder":
                    st.markdown(f"{STATUS_ICONS.get(o['status'], '')} **{o['status']}**"
                                + (f" · le {o['status_updated']}" if o.get("status_updated") else ""))
                    if o["status"] in ("Candidaté", "Pas intéressé"):
                        st.button("↩️ Annuler", key=f"undo_{o['id']}", on_click=mark_todo, args=(o,),
                                  help="Remet l'offre « À regarder ». Une ligne déjà ajoutée au Google Sheets y reste.")
                if o["status"] == "Pas intéressé":
                    known = next((e.get("reason", "") for e in rejections if e.get("id") == o["id"]), "")
                    why = st.text_input("Pourquoi ? (le filtre apprend de ta réponse)", value=known,
                                        key=f"why_{o['id']}", placeholder="Ex. : trop commercial, trop loin, que du support...")
                    if why != known and st.button("Enregistrer la raison", key=f"savewhy_{o['id']}"):
                        save_rejection(o, why)
                        st.rerun()
                note = st.text_area("Notes", value=o["note"], key=f"note_{o['id']}", height=90,
                                    placeholder="Contact, date de relance, retour du recruteur...")
                if note != o["note"] and st.button("Enregistrer la note", key=f"savenote_{o['id']}"):
                    save_field(o, note=note)
                    if SHEETS_ON and o["status"] in sheets.RETOUR:
                        try:
                            sheets.update_comment(o, note)
                        except Exception as e:
                            st.warning(f"Note enregistrée ici, mais pas dans le Google Sheets : {e}")
                    st.rerun()

            st.markdown("**✉️ Lettre de motivation**")
            if o["letter"]:
                st.code(o["letter"], language=None, wrap_lines=True)
                if letter_docx is not None:
                    d1, d2 = st.columns([1, 2])
                    d1.download_button(
                        "⬇️ Télécharger en Word (.docx)",
                        data=letter_file({k: o.get(k) for k in ("title", "company", "location", "url", "source")},
                                         o["letter"], o.get("cv") == "vie_en", file_stamp(letter_docx.CONTACT_PATH)),
                        file_name=letter_docx.file_name(o), key=f"docx_{o['id']}", width="stretch",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                    if not letter_docx.load_contact().get("telephone"):
                        d2.caption("Ajoute ton téléphone et ton e-mail dans 🔎 Réglages pour qu'ils figurent en haut "
                                   "de la lettre.")
                    else:
                        d2.caption("Relis et adapte avant d'envoyer. Le fichier arrive dans ton dossier Téléchargements.")
                else:
                    st.caption("Téléchargement Word indisponible : relance windows\\start_app.ps1 (installe python-docx).")
            if st.session_state.get("letter_warning") == o["id"]:
                st.warning(f"{o.get('source', 'Le site')} limite les accès en ce moment : la lettre a été écrite "
                           "sans la description complète de l'offre. Relis-la bien, ou régénère-la plus tard.")
            if handler is not None and st.button("Régénérer la lettre" if o["letter"] else "Générer la lettre", key=f"letter_{o['id']}"):
                st.session_state.pop("letter_warning", None)
                with st.spinner("Récupération de l'offre et rédaction..."):
                    try:
                        desc = o.get("description") or tracking.fetch_description(o)
                        letter = tracking.generate_letter(o, handler, profile, description=desc)
                        save_field(o, letter=letter)
                        if not desc:
                            st.session_state["letter_warning"] = o["id"]
                        st.rerun()
                    except Exception as e:
                        st.error(f"Impossible de générer la lettre : {e}")

            st.markdown("**📄 CV adapté à l'offre**")
            if cv_pptx is None:
                st.caption("Indisponible : relance windows\\start_app.ps1 (installe python-pptx).")
            elif not cv_pptx.available_models():
                st.caption("Ajoute tes CV PowerPoint dans l'onglet 🔎 Réglages pour pouvoir les adapter à chaque offre.")
            else:
                render_cv(o, handler, profile)

            if o["status"] == "Entretien" or o.get("prep"):
                st.markdown("**🎯 Préparation d'entretien**")
                if o.get("prep"):
                    with st.container(border=True):
                        st.markdown(o["prep"])
                if handler is not None and st.button("Régénérer la préparation" if o.get("prep") else
                                                     "Préparer l'entretien", key=f"prep_{o['id']}"):
                    with st.spinner("Préparation de l'entretien..."):
                        try:
                            save_field(o, prep=tracking.generate_interview_prep(o, handler, profile))
                            st.rerun()
                        except Exception as e:
                            st.error(f"Impossible de préparer l'entretien : {e}")

    if len(shown) > limit:
        if st.button(f"Afficher plus ({len(shown) - limit} restante(s))", width="stretch"):
            st.session_state.offer_limit = limit + PAGE_SIZE
            st.rerun()

# ----------------------------------------------------------------- Mes candidatures (Sheets)
with tab_sheet:
    if not SHEETS_ON:
        st.info("Ton Google Sheets n'est pas relié. Lance windows\\setup.ps1 et réponds O à l'étape Google Sheets "
                "(voir windows/LISEZMOI.md).")
    elif sheet_error:
        st.error(f"Impossible de lire ton Google Sheets : {sheet_error}")
        if st.button("🔄 Réessayer", key="retry_sheet"):
            with st.spinner("Lecture du Google Sheets..."):
                read_sheet.clear(wait=True)
            st.session_state.sheet_reloaded = True
            st.rerun()
    else:
        rows = sheet["rows"]
        top1, top2, top3 = st.columns([3, 1, 1])
        top1.caption(f"{len(rows)} candidature(s) · lu à {sheet['read_at']} (relu toutes les 5 minutes et "
                     "après chaque « J'ai postulé »)")
        if sheet["sheet_url"]:
            top2.button("Ouvrir le Google Sheets ↗", on_click=open_external, args=(sheet["sheet_url"],))
        if top3.button("🔄 Relire maintenant"):
            with st.spinner("Lecture du Google Sheets..."):
                read_sheet.clear(wait=True)
            st.session_state.sheet_reloaded = True
            st.rerun()
        if sheet["version"] < 2:
            st.warning("Ton script Google est une ancienne version : les dates et commentaires n'arrivent pas. "
                       "Mets-le à jour (voir le message de Claude ou google_sheets/apps_script.gs), puis "
                       "Déployer > Gérer les déploiements > crayon > Nouvelle version.")

        retours = sorted({(r.get("retour") or "Sans retour") for r in rows})
        g1, g2 = st.columns([2, 3])
        pick = g1.multiselect("Retour", retours, default=retours)
        q2 = g2.text_input("Rechercher (poste, entreprise, commentaire)", key="sheet_q").lower().strip()
        table = [
            {"_row": r.get("row"), "N": r.get("n", ""), "Poste": r.get("poste", ""),
             "Entreprise": r.get("entreprise", ""), "Date": r.get("date", ""), "Retour": r.get("retour") or "",
             "Lien": r.get("url") or r.get("lien") or "", "Commentaire": r.get("commentaire", "")}
            for r in rows
            if (r.get("retour") or "Sans retour") in pick
            and (not q2 or q2 in f"{r.get('poste','')} {r.get('entreprise','')} {r.get('commentaire','')}".lower())
        ]
        table.sort(key=lambda r: int(r["N"]) if str(r["N"]).isdigit() else 0, reverse=True)
        columns = ["N", "Poste", "Entreprise", "Date", "Retour", "Lien", "Commentaire"]

        can_edit = sheet["version"] >= 3
        edit_mode = st.toggle("✏️ Modifier", key="sheet_edit_mode", disabled=not can_edit,
                              help="Modifie les cases directement, puis enregistre : ton Google Sheets est mis à jour."
                              if can_edit else "Mets d'abord ton script Google à jour (version 3).")
        if not can_edit:
            st.caption("Pour modifier ton Sheets depuis ici, mets à jour ton script Google "
                       "(google_sheets/apps_script.gs) puis Déployer > Gérer les déploiements > Nouvelle version.")

        if edit_mode:
            import pandas as pd
            before = pd.DataFrame(table, columns=["_row"] + columns)
            choices = sorted(set(sheets.RETOUR_CHOICES) | {r["Retour"] for r in table})
            edited = st.data_editor(
                before, key="sheet_editor", hide_index=True, width="stretch", height=480, num_rows="fixed",
                column_order=columns, disabled=["N"],
                column_config={
                    "N": st.column_config.TextColumn("N", width="small"),
                    "Retour": st.column_config.SelectboxColumn("Retour", options=choices, width="small"),
                    "Date": st.column_config.TextColumn("Date", width="small", help="jj/mm/aaaa"),
                    "Lien": st.column_config.TextColumn("Lien", width="medium"),
                    "Commentaire": st.column_config.TextColumn("Commentaire", width="large"),
                },
            )
            changes = sheets.diff_rows(table, edited.fillna("").to_dict("records"))
            s1, s2 = st.columns([2, 3])
            if s1.button(f"💾 Enregistrer ({len(changes)} modification(s))", type="primary", disabled=not changes):
                done, failed = 0, []
                with st.spinner("Mise à jour du Google Sheets..."):
                    for row_n, poste, fields in changes:
                        try:
                            sheets.update_row(row_n, poste, fields)
                            done += 1
                        except Exception as e:
                            failed.append(f"ligne {row_n} ({poste[:30]}) : {e}")
                    read_sheet.clear(wait=True)
                st.session_state.pop("sheet_editor", None)
                st.session_state.sheet_save_result = (done, failed)
                st.rerun()
            if changes:
                s2.caption("Modifications pas encore envoyées : clique sur Enregistrer.")
        else:
            st.caption("Clique sur une ligne pour la sélectionner, puis sur « Ouvrir l'annonce ».")
            import pandas as pd
            view = pd.DataFrame(table, columns=["_row"] + columns)
            event = st.dataframe(
                view.style.apply(sheets.row_style, axis=1, dark=IS_DARK), hide_index=True, width="stretch", height=480,
                key="sheet_table",
                column_order=columns, on_select="rerun", selection_mode="single-row",
                column_config={
                    "N": st.column_config.TextColumn("N", width="small"),
                    "Lien": st.column_config.TextColumn("Lien", width="medium"),
                    "Retour": st.column_config.TextColumn("Retour", width="small"),
                    "Date": st.column_config.TextColumn("Date", width="small"),
                },
            )
            picked = event.selection.rows if event and event.selection else []
            if picked:
                row = table[picked[0]]
                label = f"{row['Poste']} — {row['Entreprise']}"
                if row["Lien"]:
                    st.button(f"Ouvrir l'annonce ↗  ({label[:70]})", key="open_sheet_row",
                              on_click=open_external, args=(row["Lien"],), type="primary")
                else:
                    st.caption(f"« {label[:70]} » n'a pas de lien dans ton Sheets.")
                hp, pf = gemini_and_profile()
                prep_key = f"sheetprep_{row['_row']}"
                if hp is not None and st.button(f"🎯 Préparer l'entretien ({label[:50]})", key=f"btn_{prep_key}"):
                    with st.spinner("Préparation de l'entretien..."):
                        try:
                            pseudo = {"id": f"sheet_{row['_row']}", "title": row["Poste"], "company": row["Entreprise"],
                                      "url": row["Lien"], "source": stats.source_of(row["Lien"])}
                            st.session_state[prep_key] = tracking.generate_interview_prep(pseudo, hp, pf, description="")
                        except Exception as e:
                            st.error(f"Impossible de préparer l'entretien : {e}")
                if st.session_state.get(prep_key):
                    with st.container(border=True):
                        st.markdown(st.session_state[prep_key])
                    st.caption("Préparation faite à partir du seul intitulé : ajoute l'annonce dans l'application "
                               "pour une fiche plus précise.")

        result = st.session_state.pop("sheet_save_result", None)
        if result:
            done, failed = result
            if done:
                st.success(f"{done} ligne(s) mise(s) à jour dans ton Google Sheets.")
            for f in failed:
                st.error(f"Non enregistré — {f}")

        with st.expander("➕ Ajouter une candidature faite ailleurs (spontanée, intérim, salon...)"):
            with st.form("add_application", clear_on_submit=True):
                a1, a2 = st.columns(2)
                new_poste = a1.text_input("Poste *")
                new_ent = a2.text_input("Entreprise *")
                a3, a4, a5 = st.columns([3, 1, 1])
                new_url = a3.text_input("Lien (facultatif)")
                new_date = a4.date_input("Date", format="DD/MM/YYYY")
                new_retour = a5.selectbox("Retour", ["En attente", "Positif", "Negatif"])
                new_com = st.text_input("Commentaire (facultatif)")
                if st.form_submit_button("Ajouter au Google Sheets", type="primary"):
                    if not new_poste.strip() or not new_ent.strip():
                        st.error("Le poste et l'entreprise sont obligatoires.")
                    else:
                        try:
                            res = sheets.add_row(new_poste.strip(), new_ent.strip(), new_url.strip(),
                                                 new_date.strftime("%d/%m/%Y"), new_retour, new_com.strip())
                            read_sheet.clear()
                            st.toast(f"Ajoutée au Google Sheets (ligne {res.get('row')})")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Impossible d'ajouter la ligne : {e}")

        weeks = sheets.summary(rows)["par_semaine"]
        if weeks:
            st.markdown("**Candidatures par semaine**")
            last = sorted(weeks)[-16:]
            st.bar_chart({"Semaine du": [d.isoformat() for d in last],
                          "Candidatures": [weeks[d] for d in last]},
                         x="Semaine du", y="Candidatures", height=220)

# ----------------------------------------------------------------- Statistiques
with tab_stats:
    srows = sheet["rows"] if SHEETS_ON and not sheet_error else []
    if not srows:
        st.info("Les statistiques se calculent à partir de ton Google Sheets : relie-le pour les voir.")
    else:
        st.markdown("#### Ce qu'il faut retenir")
        for line in stats.insights(srows):
            st.markdown(f"- {line}")
        st.caption("« Taux de réponse » = positifs + négatifs ; « Taux positif » = entretiens ou suites favorables. "
                   "Les groupes de moins de 5 candidatures sont à prendre avec prudence.")

        rate_cols = {
            "Taux de réponse": st.column_config.ProgressColumn("Taux de réponse", format="%d %%", min_value=0, max_value=100),
            "Taux positif": st.column_config.ProgressColumn("Taux positif", format="%.1f %%", min_value=0, max_value=20),
        }
        st.markdown("#### Par type de poste")
        fam = stats.breakdown(srows, lambda r: stats.family(r.get("poste")))
        st.dataframe(fam, hide_index=True, width="stretch", column_config=rate_cols)

        left, right = st.columns(2)
        with left:
            st.markdown("#### Par source")
            src = stats.breakdown(srows, lambda r: stats.source_of(r.get("url") or r.get("lien")))
            st.dataframe(src, hide_index=True, width="stretch", column_config=rate_cols)
        with right:
            st.markdown("#### Offres trouvées par l'application")
            found = {}
            for o in offers:
                if o.get("relevancy_check") == "duplicate":
                    continue
                f = found.setdefault(o.get("source") or "?", {"Source": o.get("source") or "?", "Trouvées": 0,
                                                              "Retenues": 0, "Candidatées": 0})
                f["Trouvées"] += 1
                f["Retenues"] += o in retained
                f["Candidatées"] += o["status"] in ("Candidaté", "Entretien", "Refusé")
            st.dataframe(sorted(found.values(), key=lambda f: -f["Trouvées"]), hide_index=True, width="stretch")

        months = stats.by_month(srows)
        if months:
            st.markdown("#### Candidatures et retours positifs par mois")
            st.bar_chart(months, x="Mois", y=["Candidatures", "Positifs"], stack=False, height=260)

# ----------------------------------------------------------------- Activité
with tab_activite:
    st.markdown(f"Les recherches tournent automatiquement {SCHEDULE_TEXT}.")
    b1, b2 = st.columns(2)
    run_now = b1.button("🔎 Lancer la recherche LinkedIn + APEC maintenant", type="primary")
    if b2.button("🔄 Synchroniser VIE + HelloWork (GitHub)"):
        sync_github()

    live = st.empty()
    if run_now:
        with st.spinner("Recherche LinkedIn + APEC en cours, ça prend quelques minutes..."):
            code = run_search_live(live)
        if code == 0:
            st.success("Recherche terminée. Les nouvelles offres retenues sont dans l'onglet Offres et sur Telegram.")
        else:
            st.error("La recherche s'est terminée avec une erreur : regarde le journal ci-dessous.")

    if SHEETS_ON and not sheet_error:
        st.caption(f"Google Sheets relié (lu à {sheet['read_at']}) : voir l'onglet 📗 Mes candidatures.")

    st.subheader("Historique des passages")
    rows = tracking.read_metrics(tracking.LOCAL_METRICS, "PC (LinkedIn + APEC)") + \
        tracking.read_metrics(tracking.GITHUB_METRICS, "GitHub (HelloWork)") + \
        tracking.read_metrics(tracking.VIE_METRICS, "GitHub (VIE)")
    rows.sort(key=lambda r: r["Date"], reverse=True)
    if rows:
        st.dataframe(rows[:100], width="stretch", hide_index=True)
    else:
        st.caption("Aucun passage enregistré pour l'instant.")

    st.subheader("Journal de la recherche LinkedIn + APEC (sur ce PC)")
    log = tracking.tail(tracking.LOG_PATH, 120)
    st.code(log or "Journal vide pour l'instant.", language=None)

# ----------------------------------------------------------------- Réseau
with tab_reseau:
    _me = letter_docx.load_contact() if letter_docx else {}
    reseau_ui.render_fragment(handler, profile, offers, reseau.signature_text(_me), open_external)

# ----------------------------------------------------------------- Réglages
with tab_reglages:
    settings = cdi_main.load_settings()
    st.markdown(
        "Les réglages sont dans **cdi_search.yaml**. Modifie-les sur GitHub : le PC et GitHub "
        "les récupèrent au passage suivant."
    )
    st.markdown("#### ✉️ Tes coordonnées pour les lettres Word")
    if letter_docx is None:
        st.caption("Indisponible : relance windows\\start_app.ps1 (installe python-docx).")
    else:
        contact = letter_docx.load_contact()
        with st.form("contact_form"):
            c1, c2 = st.columns(2)
            values = {
                "nom": c1.text_input("Nom", contact.get("nom", "")),
                "telephone": c2.text_input("Téléphone", contact.get("telephone", "")),
                "email": c1.text_input("E-mail", contact.get("email", "")),
                "ville": c2.text_input("Ville (pour « Ville, le 10 novembre 2026 »)", contact.get("ville", "")),
                "linkedin": c1.text_input("LinkedIn (facultatif)", contact.get("linkedin", "")),
            }
            if st.form_submit_button("Enregistrer", type="primary"):
                letter_docx.save_contact({k: v.strip() for k, v in values.items()})
                st.toast("Coordonnées enregistrées (sur ce PC uniquement).")
        st.caption("Gardées uniquement sur ce PC (data/coordonnees.json), jamais envoyées sur GitHub.")
    st.divider()
    st.markdown("#### 📄 Tes CV PowerPoint (modèles pour les CV adaptés)")
    if cv_pptx is None:
        st.caption("Indisponible : relance windows\\start_app.ps1 (installe python-pptx).")
    else:
        st.caption("Un fichier .pptx d'une page par CV. Gemini ne réécrit que l'intitulé, le profil, les compétences "
                   "et les descriptions, sans rien inventer ; la mise en page, la photo, les dates et tes coordonnées "
                   "restent telles quelles. Gardés uniquement sur ce PC (data/cv_modeles), jamais envoyés sur GitHub.")
        for key in cv_pptx.model_keys():
            label = candidat.cv_label(key) or key
            c1, c2, c3 = st.columns([2, 3, 1])
            have = cv_pptx.model_path(key) is not None
            c1.markdown(f"{'✅' if have else '⬜'} **{label}**")
            up = c2.file_uploader(f"Modèle {label}", type=["pptx"], key=f"cvup_{key}",
                                  label_visibility="collapsed")
            if up is not None and st.session_state.get(f"cvup_done_{key}") != up.file_id:
                try:
                    cv_pptx.save_model(key, up.getvalue())
                    st.session_state[f"cvup_done_{key}"] = up.file_id
                    st.toast(f"Modèle « {label} » enregistré.")
                    st.rerun()
                except ValueError as e:
                    c2.error(f"Fichier refusé : {e}")
            if have and c3.button("Retirer", key=f"cvdel_{key}"):
                cv_pptx.delete_model(key)
                st.rerun()
    st.divider()
    st.button("Modifier cdi_search.yaml sur GitHub ↗", on_click=open_external,
              args=(f"{repo_url()}/edit/main/cdi_search.yaml",))
    r1, r2 = st.columns(2)
    with r1:
        st.markdown("**Mots-clés**")
        st.write(", ".join(settings.get("keywords", [])))
        st.markdown(f"**Expérience maximale exigée :** {settings.get('max_experience_years', 3)} ans")
        st.markdown(f"**Ancienneté max des offres :** {settings.get('max_days', 21)} jours")
    with r2:
        st.markdown("**Mots exclus dans l'intitulé**")
        st.write(", ".join(settings.get("excluded_title_words", [])))
        st.markdown("**Domaines refusés**")
        for d in settings.get("excluded_domains", []):
            st.write(f"- {d}")


# ----------------------------------------------------------------- dialogs (drawn last)
if st.session_state.get("ask_reason"):
    ask_reason(st.session_state["ask_reason"])
else:
    reseau_ui.draw_dialogs()
