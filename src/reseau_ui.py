"""Streamlit tab « 🤝 Réseau » (drawn by app/dashboard.py). Data: src/reseau.py."""
import os

import streamlit as st

from . import reseau

ICON = reseau.STATUT_ICONS


SYNC_SECONDS = 30   # how often the Google Sheet is read again in the background

# ------------------------------------------------------------------ data store
# The sheet is read and written in background threads, so the tab never waits for Google:
#  - a poller re-reads the sheet every SYNC_SECONDS (changes made directly in the sheet);
#  - writes are applied at once to the local copy, then sent in order by a writer thread
#    (a contact added here gets a temporary id until the sheet gives it its real one).


def data_sig(data):
    import hashlib
    import json
    return hashlib.md5(json.dumps([data.get("contacts"), data.get("companies")], sort_keys=True,
                                  ensure_ascii=False).encode("utf-8")).hexdigest()


def clean(data):
    """Ignore lines without a name (left-overs of rows emptied by hand in the sheet)."""
    data = dict(data)
    data["contacts"] = [c for c in data.get("contacts", []) if (c.get("nom") or "").strip()]
    data["companies"] = [c for c in data.get("companies", []) if (c.get("entreprise") or "").strip()]
    return data


@st.cache_resource
def _store():
    import queue
    import threading
    return {"data": None, "sig": None, "error": None, "write_errors": [], "queue": queue.Queue(),
            "pending": 0, "lock": threading.RLock(), "threads": {}, "idmap": {}, "tmp": 0}


CACHE_PATH = reseau.ROOT / "data" / "reseau_cache.json"   # last copy of the sheet (this PC only)


def _read_cache():
    import json
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and "contacts" in data else None
    except (OSError, ValueError):
        return None


def _write_cache(data):
    import json
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(CACHE_PATH)
    except OSError:
        pass


def _fetch_into(store):
    data = clean(reseau.fetch())
    with store["lock"]:
        if store["pending"]:          # local changes not sent yet: the sheet is behind, keep ours
            return
        store["data"], store["sig"], store["error"] = data, data_sig(data), None
    _write_cache(data)


def _first_fetch(store):
    try:
        _fetch_into(store)
    except Exception as e:
        store["error"] = str(e)
    finally:
        store["loading"] = False


def _poller(store):
    import time
    while True:
        time.sleep(SYNC_SECONDS)
        try:
            if reseau.configured():
                _fetch_into(store)
        except Exception as e:
            store["error"] = str(e)


API = {
    "add_contact": lambda a: reseau.add_contact(*a),
    "update_contact": lambda a: reseau.update_contact(*a),
    "delete_contact": lambda a: reseau.delete_contact(*a),
    "add_companies": lambda a: reseau.add_companies(*a),
    "update_company": lambda a: reseau.update_company(*a),
    "delete_company": lambda a: reseau.delete_company(*a),
}


def _writer(store):
    q = store["queue"]
    while True:
        op, args, tmp_id = q.get()
        try:
            if op in ("update_contact", "delete_contact"):
                args = (store["idmap"].get(args[0], args[0]),) + tuple(args[1:])
                if str(args[0]).startswith("tmp"):
                    raise RuntimeError("contact pas encore créé dans le Sheets")
            result = API[op](args)
            if op == "add_contact" and tmp_id:
                real = str(result.get("id"))
                with store["lock"]:
                    store["idmap"][tmp_id] = real
                    for c in (store["data"] or {}).get("contacts", []):
                        if c.get("id") == tmp_id:
                            c["id"] = real
        except Exception as e:
            store["write_errors"].append(f"{op} : {e}")
        finally:
            with store["lock"]:
                store["pending"] -= 1
            q.task_done()
        if q.empty():
            try:
                _fetch_into(store)       # line up with the sheet once everything is sent
            except Exception:
                pass


def _ensure_threads(store):
    import threading
    for name, target in (("reseau-poller", _poller), ("reseau-writer", _writer)):
        t = store["threads"].get(name)
        if t is None or not t.is_alive():
            t = threading.Thread(target=target, args=(store,), name=name, daemon=True)
            t.start()
            store["threads"][name] = t


def get_data(force=False):
    """The sheet's data, without waiting for Google on the first display: the last copy kept on
    this PC is shown at once and the sheet is read in the background (watch_sheet redraws)."""
    store = _store()
    if not force and store["data"] is None:
        if not store.get("started"):
            import threading
            store["started"], store["loading"] = True, True
            cached = _read_cache()
            if cached:
                with store["lock"]:
                    store["data"], store["sig"] = cached, data_sig(cached)
            threading.Thread(target=_first_fetch, args=(store,), name="reseau-premiere-lecture",
                             daemon=True).start()
        if store["data"] is None:
            if store.get("loading"):
                return {"contacts": [], "companies": [], "sheet_url": "", "error": None, "loading": True}
            force = True              # the first reading failed: try again now (shows the error)
    if force or store["data"] is None:
        try:
            _fetch_into(store)
            if store["data"] is None:
                raise RuntimeError("lecture impossible")
        except Exception as e:
            if store["data"] is None:
                return {"contacts": [], "companies": [], "sheet_url": "", "error": str(e)}
            store["error"] = str(e)
    _ensure_threads(store)
    return {**store["data"], "error": None}


def _apply(data, op, args, tmp_id):
    """Same change as the sheet will get, on the local copy."""
    contacts, companies = data["contacts"], data["companies"]
    norm = lambda x: (x or "").strip().lower()
    if op == "add_contact":
        contacts.append({"id": tmp_id, "statut": "À contacter", **args[0]})
    elif op == "update_contact":
        for c in contacts:
            if str(c.get("id")) == str(args[0]):
                c.update(args[1])
    elif op == "delete_contact":
        data["contacts"] = [c for c in contacts if str(c.get("id")) != str(args[0])]
    elif op == "add_companies":
        known = {norm(c.get("entreprise")) for c in companies}
        for item in args[0]:
            if norm(item.get("entreprise")) not in known:
                companies.append(dict(item))
                known.add(norm(item.get("entreprise")))
    elif op == "update_company":
        for c in companies:
            if norm(c.get("entreprise")) == norm(args[0]):
                c.update(args[1])
    elif op == "delete_company":
        data["companies"] = [c for c in companies if norm(c.get("entreprise")) != norm(args[0])]


def _rerun():
    """Redraw only the Réseau tab (the rest of the app does not need it)."""
    try:
        st.rerun(scope="fragment")
    except Exception:
        st.rerun()


def _write(op, *args, done="Enregistré dans ton Google Sheets."):
    """Apply the change now and send it to the sheet in the background."""
    store = _store()
    _ensure_threads(store)
    args = tuple(reseau.clean_fields(a) if isinstance(a, dict) else a for a in args)
    with store["lock"]:
        tmp_id = None
        if op == "add_contact":
            store["tmp"] += 1
            tmp_id = f"tmp{store['tmp']}"
        if store["data"] is not None:
            _apply(store["data"], op, args, tmp_id)
            store["sig"] = data_sig(store["data"])
        store["pending"] += 1
    store["queue"].put((op, args, tmp_id))
    st.session_state["reseau_sig"] = store["sig"]
    st.toast(done)
    return True


@st.fragment(run_every=5)
def watch_sheet():
    """Redraw the tab when the background reader brought changes made in the sheet."""
    store = _store()
    seen = st.session_state.get("reseau_sig")
    if seen == "loading" and not store.get("loading"):   # first reading over (read, or failed)
        st.rerun(scope="app")
    if store["sig"] and seen and store["sig"] != seen:
        st.rerun(scope="app")


# ------------------------------------------------------------------ script update
def script_update():
    st.warning("Ton script Google Sheets « Réseau » doit être mis à jour.")
    with st.expander("🔧 Mettre à jour le script (2 minutes)", expanded=True):
        st.markdown("1. Dans ton Sheets : **Extensions > Apps Script**, efface tout et colle ce code, puis 💾 Enregistrer.")
        st.code(reseau.script_text(reseau.token()), language="javascript", height=160)
        st.markdown(
            "2. **Déployer > Gérer les déploiements** > ✏️ (crayon) > Version : **Nouvelle version** > **Déployer**.\n\n"
            "L'URL ne change pas : rien d'autre à faire. Clique ensuite ici :")
        if st.button("✅ C'est fait", type="primary"):
            get_data(force=True)
            _rerun()
        st.markdown("**Tu as créé un *nouveau* déploiement au lieu de modifier l'ancien ?** "
                    "Il a une autre URL : colle-la ici.")
        url = st.text_input("Nouvelle URL de l'application Web", key="reseau_new_url",
                            placeholder="https://script.google.com/macros/s/.../exec")
        if st.button("Utiliser cette URL", disabled=not url.strip()):
            if not url.strip().startswith("https://script.google.com/"):
                st.error("Ce n'est pas une URL d'application Web Apps Script.")
            else:
                reseau.save_env_value("RESEAU_WEBAPP_URL", url.strip())
                get_data(force=True)
                _rerun()
        st.caption("Le script actuellement en ligne répond encore « version 1 » : c'est l'ancienne version qui tourne.")


# ------------------------------------------------------------------ first-time setup
def setup():
    st.markdown("### 🤝 Relier ton Google Sheets « Réseau »")
    secret = reseau.token()
    if not secret:
        secret = st.session_state.setdefault("reseau_new_secret", reseau.new_secret())
    st.markdown(
        "1. Ouvre ton Google Sheets de réseau, puis **Extensions > Apps Script**.\n"
        "2. Efface tout le code et colle celui-ci (bouton copier en haut à droite du cadre). "
        "Ton code secret est déjà dedans.")
    st.code(reseau.script_text(secret), language="javascript", height=180)
    st.markdown(
        "3. 💾 Enregistre, puis **Déployer > Nouveau déploiement** > roue ⚙️ > **Application Web** :\n"
        "   - Exécuter en tant que : **Moi**\n"
        "   - Qui a accès : **Tout le monde**\n"
        "4. **Déployer**, autorise l'accès à ton compte, puis copie l'**URL de l'application Web** ici :")
    url = st.text_input("URL de l'application Web", placeholder="https://script.google.com/macros/s/.../exec")
    if st.button("Relier", type="primary", disabled=not url.strip()):
        url = url.strip()
        if not url.startswith("https://script.google.com/"):
            st.error("Ce n'est pas une URL d'application Web Apps Script (elle commence par https://script.google.com/).")
            return
        reseau.save_env_value("RESEAU_WEBAPP_URL", url)
        if not os.environ.get("SHEETS_TOKEN") or secret != os.environ.get("SHEETS_TOKEN"):
            reseau.save_env_value("RESEAU_TOKEN", secret)
        get_data(force=True)
        data = get_data()
        if data["error"]:
            st.error(f"Relié, mais la lecture échoue : {data['error']}")
        else:
            st.success("C'est relié : les onglets « Entreprises » et « Contacts » ont été créés dans ton Sheets.")
            _rerun()
    st.caption("L'URL et le code secret sont gardés dans le fichier .env de ce PC, jamais sur GitHub.")


# ------------------------------------------------------------------ companies
def companies_view(data, offers, open_external):
    companies, contacts = data["companies"], data["contacts"]
    per_company = reseau.contacts_by_company(contacts)

    if not companies:
        starter = reseau.default_companies()
        if starter:
            st.info("Ta liste d'entreprises est vide. Commence avec une liste de départ (tu pourras en retirer "
                    "ou en ajouter), ou ajoute les tiennes.")
            if st.button(f"➕ Ajouter la liste de départ ({len(starter)} entreprises, réglée dans "
                         "cdi_search.yaml)", type="primary"):
                if _write("add_companies", starter, done="Liste ajoutée à ton Sheets."):
                    _rerun()
        else:
            st.info("Ta liste d'entreprises est vide. Ajoute les entreprises qui t'intéressent ci-dessous, "
                    "ou pioche dans les suggestions tirées de tes offres.")

    c1, c2 = st.columns(2)
    with c1.expander("➕ Ajouter une entreprise"):
        with st.form("reseau_add_company", clear_on_submit=True):
            name = st.text_input("Entreprise")
            sector = st.text_input("Secteur", placeholder="Aéronautique, énergie...")
            search = st.text_input("Mots-clés de recherche LinkedIn", value=reseau.DEFAULT_SEARCH,
                                   help="Le type de personnes que tu cherches dans cette entreprise : "
                                        "un métier, une équipe, une techno (ex. chef de projet, data, RH...)")
            if st.form_submit_button("Ajouter", type="primary") and name.strip():
                if _write("add_companies", [{"entreprise": name, "secteur": sector, "recherche": search}]):
                    _rerun()
    suggestions = reseau.suggest_companies(offers, companies)
    with c2.expander(f"💡 Suggestions tirées de tes offres ({len(suggestions)})"):
        if not suggestions:
            st.caption("Aucune : les entreprises de tes offres notées 7/10 ou plus sont déjà dans ta liste.")
        for s in suggestions:
            a, b = st.columns([4, 1])
            a.markdown(f"**{s['entreprise']}** · {s['offres']} offre(s), meilleure note ⭐ {s['best']}/10")
            if b.button("➕", key=f"sugg_{s['entreprise']}", help="Ajouter à ta liste"):
                if _write("add_companies", [{"entreprise": s["entreprise"], "recherche": reseau.DEFAULT_SEARCH}]):
                    _rerun()

    if not companies:
        return
    q = st.text_input("Filtrer", placeholder="🔍 Entreprise, secteur...", label_visibility="collapsed",
                      key="reseau_company_q").strip().lower()
    order = sorted(companies, key=lambda c: (c.get("priorite") != "Haute", c["entreprise"].lower()))
    for comp in order:
        name = comp["entreprise"]
        if q and q not in f"{name} {comp.get('secteur', '')}".lower():
            continue
        people = per_company.get(name.strip().lower(), [])
        with st.container(border=True):
            info, b1, b2, b3, b4 = st.columns([4, 2, 2, 2, 1])
            star = "⭐ " if comp.get("priorite") == "Haute" else ""
            info.markdown(f"**{star}{name}**  \n" + " · ".join(
                x for x in [comp.get("secteur"), f"{len(people)} contact(s)" if people else "aucun contact"] if x))
            b1.button("🔎 Trouver des contacts", key=f"li_{name}", width="stretch", on_click=open_external,
                      args=(reseau.linkedin_people_url(name, comp.get("recherche")),),
                      help=f"Recherche LinkedIn « {comp.get('recherche') or reseau.DEFAULT_SEARCH} {name} », "
                           "dans ton navigateur")
            b2.button("💼 Carrières", key=f"car_{name}", width="stretch", on_click=open_external,
                      args=(reseau.careers_url(name),))
            b3.button("➕ Contact", key=f"addc_{name}", width="stretch", on_click=_open_dialog,
                      args=("add_contact", name))
            b4.button("⋯", key=f"editc_{name}", help="Modifier / retirer", on_click=_open_dialog,
                      args=("company", name))


# ------------------------------------------------------------------ contacts
def contact_form(key, data, company=None):
    names = sorted({c["entreprise"] for c in data["companies"]}, key=str.lower)
    with st.form(key, clear_on_submit=True):
        st.markdown("**Nouveau contact**")
        nom = st.text_input("Nom et prénom")
        poste = st.text_input("Poste", placeholder="Responsable d'équipe, chef de projet...")
        if company:
            entreprise = company
        else:
            choice = st.selectbox("Entreprise", names + ["Autre..."]) if names else "Autre..."
            other = st.text_input("Autre entreprise") if choice == "Autre..." or not names else ""
            entreprise = other if choice == "Autre..." else choice
        linkedin = st.text_input("Lien du profil LinkedIn", placeholder="https://www.linkedin.com/in/...")
        email = st.text_input("E-mail (si tu l'as)", help="Seulement une adresse obtenue normalement : affichée "
                                                          "publiquement, donnée par quelqu'un, adresse recrutement...")
        notes = st.text_area("Notes", placeholder="Comment tu l'as trouvé, point commun...", height=68)
        if st.form_submit_button("Ajouter", type="primary"):
            if not nom.strip() or not (entreprise or "").strip():
                st.error("Il faut au moins un nom et une entreprise.")
            elif _write("add_contact", {"nom": nom, "poste": poste, "entreprise": entreprise,
                                             "linkedin": linkedin, "email": email, "notes": notes},
                        done="Contact ajouté."):
                _close_dialog()
                st.rerun(scope="app")   # also closes the dialog it may be in


def contacts_view(data, handler, profile, signature, open_external):
    contacts, companies = data["contacts"], data["companies"]
    comp_info = {c["entreprise"].strip().lower(): c for c in companies}
    with st.expander("➕ Ajouter un contact", expanded=not contacts):
        contact_form("reseau_add_contact", data)
    if not contacts:
        st.caption("Astuce : dans 🏢 Entreprises, « 🔎 Trouver des contacts » ouvre une recherche LinkedIn "
                   "toute prête ; ajoute ensuite les personnes intéressantes ici.")
        return

    f1, f2 = st.columns([3, 2])
    q = f1.text_input("Rechercher", placeholder="🔍 Nom, poste, entreprise...", label_visibility="collapsed",
                      key="reseau_contact_q").strip().lower()
    show = f2.segmented_control("Afficher", ["En cours", "Tous"], default="En cours", key="reseau_show",
                                label_visibility="collapsed")
    due = [c for c in contacts if reseau.follow_up_due(c)]
    rest = [c for c in contacts if c not in due]
    for c in due + sorted(rest, key=lambda c: (reseau.STATUTS.index(c.get("statut")) if c.get("statut")
                                               in reseau.STATUTS else 0, c.get("entreprise", "").lower())):
        if show == "En cours" and c.get("statut") in ("Pas de réponse",):
            continue
        if q and q not in f"{c.get('nom')} {c.get('poste')} {c.get('entreprise')}".lower():
            continue
        contact_card(c, comp_info.get((c.get("entreprise") or "").strip().lower()), c in due,
                     handler, profile, signature, open_external)


def contact_card(c, company, due, handler, profile, signature, open_external):
    cid = c["id"]
    statut = c.get("statut") or "À contacter"
    label = f"{ICON.get(statut, '🔵')} **{c.get('nom')}** — {c.get('poste') or 'poste ?'} · {c.get('entreprise')}"
    if due:
        label += " · 🔁 **à relancer**"
    elif c.get("contacte_le"):
        label += f" · contacté le {c['contacte_le']}"
    with st.expander(label):
        links = st.columns(3)
        if c.get("linkedin"):
            links[0].button("🔗 Son profil LinkedIn", key=f"prof_{cid}", on_click=open_external, args=(c["linkedin"],))
        else:
            links[0].caption("Pas de lien LinkedIn")
        links[1].caption(f"✉️ {c['email']}" if c.get("email") else "Pas d'e-mail")
        links[2].caption(f"Statut : **{statut}**")

        # ---- message
        msg = st.session_state.get(f"msg_{cid}") or reseau.unpack_message(c.get("message"))
        if handler is not None:
            if st.button("✍️ Réécrire le message" if msg else "✍️ Écrire le message", key=f"gen_{cid}",
                         type="secondary" if msg else "primary"):
                with st.spinner("Rédaction..."):
                    try:
                        msg = reseau.generate_message(c, company, handler, profile, signature)
                        st.session_state[f"msg_{cid}"] = msg
                        _write("update_contact", cid, {"message": reseau.pack_message(msg)},
                               done="Message gardé dans ton Sheets.")
                    except Exception as e:
                        st.error(str(e))
        else:
            st.caption("Clé Gemini ou profil manquant : impossible d'écrire le message.")
        if msg:
            st.markdown(f"**Note d'invitation LinkedIn** ({len(msg['note'])}/{reseau.NOTE_MAX} caractères) : "
                        "« Se connecter » > « Ajouter une note », puis colle.")
            st.code(msg["note"], language=None, wrap_lines=True)
            st.markdown("**Mail**")
            st.code(f"{msg['objet']}", language=None, wrap_lines=True)
            st.code(msg["mail"], language=None, wrap_lines=True)
            st.button("📧 Ouvrir dans Gmail" + ("" if c.get("email") else " (sans destinataire)"), key=f"gm_{cid}",
                      on_click=open_external, args=(reseau.gmail_url(c.get("email"), msg["objet"], msg["mail"]),))
            st.caption("Relis et adapte avant d'envoyer. C'est toi qui envoies : rien ne part tout seul.")

        # ---- status
        st.markdown("**Où tu en es**")
        actions = {
            "À contacter": [("📨 Message envoyé", "Contacté")],
            "Contacté": [("🔁 J'ai relancé", "Relancé"), ("💬 A répondu", "A répondu"),
                         ("⚪ Pas de réponse", "Pas de réponse")],
            "Relancé": [("💬 A répondu", "A répondu"), ("⚪ Pas de réponse", "Pas de réponse")],
            "A répondu": [("🗓️ Entretien obtenu", "Entretien")],
            "Entretien": [],
            "Pas de réponse": [("💬 A répondu finalement", "A répondu")],
        }.get(statut, [])
        cols = st.columns(len(actions) + 1)
        for col, (text, new) in zip(cols, actions):
            if col.button(text, key=f"st_{cid}_{new}", width="stretch",
                          type="primary" if new in ("Contacté", "A répondu") else "secondary"):
                if _write("update_contact", cid, reseau.status_change(new)):
                    _rerun()
        if statut != "À contacter" and cols[-1].button("↩️ Annuler", key=f"undo_{cid}", width="stretch"):
            if _write("update_contact", cid, {"statut": "À contacter", "contacte_le": "", "relance_le": ""}):
                _rerun()
        if c.get("relance_le") and statut == "Contacté":
            st.caption(f"Relance prévue le {c['relance_le']} (sans réponse d'ici là).")

        st.button("✏️ Modifier / notes", key=f"editk_{cid}", on_click=_open_dialog, args=("contact", cid))


def _open_dialog(kind, key):
    st.session_state["reseau_dialog"] = (kind, key)
    st.session_state["reseau_open_dialog"] = True


def _close_dialog():
    st.session_state.pop("reseau_dialog", None)


@st.dialog("Nouveau contact", on_dismiss=_close_dialog)
def dialog_add_contact(data, company):
    contact_form(f"dlg_addc_{company}", data, company=company)


@st.dialog("Entreprise", on_dismiss=_close_dialog)
def dialog_company(comp):
    name = comp["entreprise"]
    st.markdown(f"**{name}**")
    with st.form(f"edit_comp_{name}"):
        sector = st.text_input("Secteur", comp.get("secteur", ""))
        search = st.text_input("Mots-clés LinkedIn", comp.get("recherche") or reseau.DEFAULT_SEARCH)
        prio = st.checkbox("⭐ Prioritaire", comp.get("priorite") == "Haute")
        if st.form_submit_button("Enregistrer", type="primary"):
            _write("update_company", name, {"secteur": sector, "recherche": search,
                                            "priorite": "Haute" if prio else ""})
            _close_dialog()
            st.rerun(scope="app")
    if st.button("🗑️ Retirer de la liste", key=f"del_comp_{name}"):
        _write("delete_company", name, done="Entreprise retirée.")
        _close_dialog()
        st.rerun(scope="app")


@st.dialog("Contact", on_dismiss=_close_dialog)
def dialog_contact(c):
    cid = c["id"]
    with st.form(f"edit_{cid}"):
        fields = {
            "nom": st.text_input("Nom", c.get("nom", "")),
            "poste": st.text_input("Poste", c.get("poste", "")),
            "entreprise": st.text_input("Entreprise", c.get("entreprise", "")),
            "linkedin": st.text_input("LinkedIn", c.get("linkedin", "")),
            "email": st.text_input("E-mail", c.get("email", "")),
            "notes": st.text_area("Notes", c.get("notes", "")),
        }
        if st.form_submit_button("Enregistrer", type="primary"):
            _write("update_contact", cid, fields)
            _close_dialog()
            st.rerun(scope="app")
    if st.button("🗑️ Supprimer ce contact", key=f"delc_{cid}"):
        _write("delete_contact", cid, done="Contact supprimé.")
        _close_dialog()
        st.rerun(scope="app")


def draw_dialog(data):
    kind, key = st.session_state.get("reseau_dialog") or (None, None)
    if kind == "add_contact":
        dialog_add_contact(data, key)
    elif kind == "company":
        comp = next((c for c in data["companies"] if c["entreprise"] == key), None)
        if comp:
            dialog_company(comp)
    elif kind == "contact":
        c = next((c for c in data["contacts"] if str(c["id"]) == str(key)), None)
        if c:
            dialog_contact(c)


# ------------------------------------------------------------------ tab
@st.fragment
def render_fragment(handler, profile, offers, signature, open_external):
    render(handler, profile, offers, signature, open_external)
    if st.session_state.pop("reseau_open_dialog", False):
        st.rerun(scope="app")   # dialogs are drawn by the full page


def render(handler, profile, offers, signature, open_external):
    if not reseau.configured():
        setup()
        return
    data = get_data()
    if data.get("loading"):
        st.session_state["reseau_sig"] = "loading"   # watch_sheet redraws the tab once it is read
        st.info("⏳ Lecture de ton Google Sheets « Réseau »…")
        return
    if data["error"]:
        st.error(f"Google Sheets « Réseau » illisible : {data['error']}")
        if st.button("Réessayer"):
            get_data(force=True)
            _rerun()
        with st.expander("Refaire la liaison"):
            setup()
        return

    if data.get("version", 1) < reseau.SCRIPT_VERSION:
        script_update()
    st.session_state["reseau_sig"] = data_sig(data)

    s = reseau.summary(data["contacts"])
    m = st.columns(5)
    m[0].metric("🏢 Entreprises", len(data["companies"]))
    m[1].metric("👥 Contacts", s["total"])
    m[2].metric("📨 Contactés", s["reached"])
    m[3].metric("💬 Réponses", s["answered"], delta=f"{s['rate']} %" if s["rate"] is not None else None,
                delta_color="off", help="Ont répondu ou t'ont proposé un entretien (taux sur les contactés)")
    m[4].metric("🔁 À relancer", s["due"], help=f"Contactés il y a {reseau.FOLLOW_UP_DAYS} jours ou plus, sans réponse")

    top = st.columns([4, 1, 1])
    default = "👥 Contacts" if data["contacts"] else "🏢 Entreprises"
    view = top[0].segmented_control("Vue", ["🏢 Entreprises", "👥 Contacts"], default=default,
                                    key="reseau_view", label_visibility="collapsed") or default
    if top[1].button("🔄 Actualiser", width="stretch", help="Relit tout de suite ton Google Sheets"):
        get_data(force=True)
        _rerun()
    if data.get("sheet_url"):
        top[2].button("📗 Ouvrir le Sheets", on_click=open_external, args=(data["sheet_url"],), width="stretch")
    pending = _store()["pending"]
    st.caption((f"⏳ {pending} modification(s) en cours d'envoi au Sheets · " if pending else "")
               + f"🔄 Synchronisé avec ton Google Sheets : tes changements y sont écrits en arrière-plan, et ceux "
               f"faits dans le Sheets apparaissent ici en moins de {SYNC_SECONDS} secondes.")
    if view == "🏢 Entreprises":
        companies_view(data, offers, open_external)
    else:
        contacts_view(data, handler, profile, signature, open_external)
    store = _store()
    while store["write_errors"]:
        st.error(f"Une modification n'a pas pu être enregistrée dans le Sheets ({store['write_errors'].pop(0)}). "
                 "Clique sur 🔄 Actualiser pour voir l'état réel.")


def draw_dialogs():
    """Called by the dashboard outside the tab's fragment (a dialog cannot open inside a fragment)."""
    if reseau.configured() and st.session_state.get("reseau_sig"):
        watch_sheet()                 # outside the tab's fragment: nested timers confuse Streamlit
    if st.session_state.get("reseau_dialog") and reseau.configured():
        data = get_data()
        if not data["error"] and not data.get("loading"):
            draw_dialog(data)
