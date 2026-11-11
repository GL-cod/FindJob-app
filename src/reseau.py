"""« 🤝 Réseau » : companies to target and people the user adds himself, kept in his own
Google Sheet (google_sheets/reseau.gs). Nothing here collects people's data automatically:
the app opens ready-made LinkedIn searches in the user's browser, he picks the people and
types them in; Gemini drafts messages that he reviews and sends himself.

.env: RESEAU_WEBAPP_URL (the script's web app URL) and RESEAU_TOKEN (defaults to SHEETS_TOKEN).
"""
import json
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

import requests

ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = ROOT / "google_sheets" / "reseau.gs"
ENV_PATH = ROOT / ".env"

STATUTS = ["À contacter", "Contacté", "Relancé", "A répondu", "Entretien", "Pas de réponse"]
STATUT_ICONS = {"À contacter": "🔵", "Contacté": "📨", "Relancé": "🔁", "A répondu": "💬",
                "Entretien": "🗓️", "Pas de réponse": "⚪"}
FOLLOW_UP_DAYS = 7
NOTE_MAX = 300          # LinkedIn connection note limit
# Starting list and LinkedIn keywords come from cdi_search.yaml (candidat.reseau), so each
# user has his own. Companies only (no people). The user edits them in the sheet.
def default_search():
    from .candidat import reseau_search
    return reseau_search()


def default_company_list():
    from .candidat import reseau_companies
    return reseau_companies()


def __getattr__(name):   # reseau.DEFAULT_SEARCH / reseau.DEFAULT_COMPANIES, always up to date
    if name == "DEFAULT_SEARCH":
        return default_search()
    if name == "DEFAULT_COMPANIES":
        return default_company_list()
    raise AttributeError(name)


# ------------------------------------------------------------------ configuration
def token():
    return os.environ.get("RESEAU_TOKEN") or os.environ.get("SHEETS_TOKEN") or ""


def configured():
    return bool(os.environ.get("RESEAU_WEBAPP_URL") and token())


def script_text(secret):
    """reseau.gs with the user's secret already filled in, ready to paste."""
    return SCRIPT_PATH.read_text(encoding="utf-8").replace("COLLE_ICI_TON_CODE_SECRET", secret)


def save_env_value(key, value, path=None):
    """Set KEY=value in .env (replaces the line, or appends it) and in the running process."""
    path = Path(path or ENV_PATH)
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    lines = [l for l in lines if not re.match(rf"\s*{re.escape(key)}\s*=", l)]
    lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value


def new_secret():
    import secrets
    return secrets.token_urlsafe(18)


# ------------------------------------------------------------------ sheet
SCRIPT_VERSION = 2   # version of google_sheets/reseau.gs the app expects


def fetch(timeout=25, tabs=False):
    """{contacts: [...], companies: [...], sheet_url, version}; with tabs=True also the raw content of
    the sheet's other tabs ({name, values}) for the import."""
    params = {"token": token()}
    if tabs:
        params["tabs"] = "1"
    r = requests.get(os.environ["RESEAU_WEBAPP_URL"], params=params, timeout=timeout)
    r.raise_for_status()
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError("le script ne répond pas en JSON : vérifie « Qui a accès : Tout le monde »")
    if not data.get("ok"):
        raise RuntimeError(f"Google Sheets a refusé la demande : {data.get('error')}")
    data.setdefault("contacts", [])
    data.setdefault("companies", [])
    data.setdefault("version", 1)
    return data


def post(action, timeout=30, **payload):
    r = requests.post(os.environ["RESEAU_WEBAPP_URL"], json={"token": token(), "action": action, **payload},
                      timeout=timeout)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Google Sheets a refusé la demande : {data.get('error')}")
    return data


def add_contact(fields):
    return post("add_contact", fields=clean_fields(fields))


def update_contact(contact_id, fields):
    return post("update_contact", id=contact_id, fields=clean_fields(fields))


def delete_contact(contact_id):
    return post("delete_contact", id=contact_id)


def add_contacts(items):
    return post("add_contacts", items=[clean_fields(i) for i in items], timeout=60)


def add_companies(items):
    return post("add_companies", items=[clean_fields(i) for i in items])


def update_company(name, fields):
    return post("update_company", name=name, fields=clean_fields(fields))


def delete_company(name):
    return post("delete_company", name=name)


def default_companies():
    return [{"entreprise": n, "secteur": s, "recherche": k, "priorite": ""} for n, s, k in default_company_list()]


def clean_fields(fields):
    return {k: (v.strip() if isinstance(v, str) else v) for k, v in fields.items() if v is not None}


# ------------------------------------------------------------------ status changes
def fr_date(d):
    return d.strftime("%d/%m/%Y")


def parse_fr_date(text):
    try:
        return datetime.strptime((text or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def status_change(statut, today=None):
    """Fields to write when the user changes a contact's status."""
    today = today or date.today()
    fields = {"statut": statut}
    if statut in ("Contacté", "Relancé"):
        fields["contacte_le"] = fr_date(today)
        fields["relance_le"] = fr_date(today + timedelta(days=FOLLOW_UP_DAYS)) if statut == "Contacté" else ""
    if statut in ("A répondu", "Entretien", "Pas de réponse"):
        fields["relance_le"] = ""
    return fields


def follow_up_due(contact, today=None):
    d = parse_fr_date(contact.get("relance_le"))
    return contact.get("statut") == "Contacté" and d is not None and d <= (today or date.today())


def summary(contacts, today=None):
    s = {k: 0 for k in STATUTS}
    for c in contacts:
        s[c.get("statut") or "À contacter"] = s.get(c.get("statut") or "À contacter", 0) + 1
    reached = sum(s[k] for k in ("Contacté", "Relancé", "A répondu", "Entretien", "Pas de réponse"))
    answered = s["A répondu"] + s["Entretien"]
    return {"total": len(contacts), "reached": reached, "answered": answered,
            "rate": round(100 * answered / reached) if reached else None,
            "due": sum(follow_up_due(c, today) for c in contacts), "by_status": s}


def contacts_by_company(contacts):
    out = {}
    for c in contacts:
        out.setdefault((c.get("entreprise") or "").strip().lower(), []).append(c)
    return out


def suggest_companies(offers, companies, min_score=7, limit=10):
    """Companies of the user's best-scored offers that are not in his list yet."""
    known = {(c.get("entreprise") or "").strip().lower() for c in companies}
    counts = {}
    for o in offers:
        name = (o.get("company") or "").strip()
        if not name or name.lower() in known or (o.get("score") or 0) < min_score:
            continue
        if re.search(r"confidenti|anonyme|cabinet de recrutement", name, re.IGNORECASE):
            continue
        c = counts.setdefault(name.lower(), {"entreprise": name, "offres": 0, "best": 0})
        c["offres"] += 1
        c["best"] = max(c["best"], o.get("score") or 0)
    return sorted(counts.values(), key=lambda c: (-c["best"], -c["offres"], c["entreprise"]))[:limit]


# ------------------------------------------------------------------ links
def linkedin_people_url(company, keywords=None):
    """LinkedIn people search the user opens himself in his browser."""
    words = f"{keywords or default_search()} {company}".strip()
    return "https://www.linkedin.com/search/results/people/?" + urlencode({"keywords": words, "origin": "GLOBAL_SEARCH_HEADER"})


def careers_url(company):
    return "https://www.google.com/search?" + urlencode({"q": f"{company} carrières recrutement offres"})


def gmail_url(to, subject, body):
    return "https://mail.google.com/mail/?" + urlencode({"view": "cm", "fs": "1", "to": to or "",
                                                         "su": subject or "", "body": body or ""},
                                                        quote_via=quote)


def mailto_url(to, subject, body):
    return f"mailto:{quote(to or '')}?" + urlencode({"subject": subject or "", "body": body or ""}, quote_via=quote)


# ------------------------------------------------------------------ messages (Gemini)
def message_prompt(contact, company, profile, signature=""):
    from .candidat import nom as _nom, reseau_example
    company = company or {}
    example, nom = reseau_example(), _nom()
    return (
        "Tu aides un jeune ingénieur à écrire à un professionnel qu'il ne connaît pas, pour se faire "
        "connaître et obtenir un échange, dans le cadre de sa recherche d'emploi.\n"
        "Réponds UNIQUEMENT avec un objet JSON : "
        '{"note": "...", "objet": "...", "mail": "..."}\n\n'
        "Règles :\n"
        f"- note : message d'invitation LinkedIn, {NOTE_MAX - 20} caractères MAXIMUM espaces compris, "
        "vouvoiement, commence par « Bonjour <Prénom>, », sans signature.\n"
        "- objet : objet de mail court et précis (moins de 70 caractères).\n"
        "- mail : 110 à 170 mots, vouvoiement, commence par « Bonjour <Prénom> <Nom>, » (ou « Bonjour, » "
        "si le nom est inconnu), termine par « Bien cordialement, » puis la signature fournie.\n"
        "- Ton direct et humble, pas de flatterie ni de formules creuses. Demande un court échange "
        "(15 minutes) ou un conseil sur les postes de son équipe, pas directement un emploi.\n"
        "- Fais UN lien concret entre son poste ou son entreprise et une expérience réelle du profil"
        + (f" (par exemple {example})" if example else "") + ".\n"
        "- N'invente RIEN : ni fait sur la personne ou l'entreprise, ni compétence du candidat. "
        "Si le poste de la personne est vague, reste général sur son domaine.\n"
        "- Texte brut, sans markdown.\n\n"
        f"=== DESTINATAIRE ===\nNom : {contact.get('nom') or 'inconnu'}\nPoste : {contact.get('poste') or 'inconnu'}\n"
        f"Entreprise : {contact.get('entreprise') or 'inconnue'}\nSecteur : {company.get('secteur') or 'inconnu'}\n"
        f"Notes du candidat sur ce contact : {contact.get('notes') or '(aucune)'}\n\n"
        f"=== SIGNATURE ===\n{signature or nom or '(aucune : termine par « Bien cordialement, »)'}\n\n"
        f"=== PROFIL DU CANDIDAT ===\n{profile}"
    )


def parse_message(text):
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        raise ValueError("réponse de Gemini illisible")
    data = json.loads(m.group(0))
    out = {k: (data.get(k) or "").strip() for k in ("note", "objet", "mail")}
    if not out["note"] or not out["mail"]:
        raise ValueError("message incomplet")
    return out


def shorten_note(note, limit=NOTE_MAX):
    """Last resort if Gemini went over LinkedIn's limit: cut at the last full sentence."""
    if len(note) <= limit:
        return note
    cut = note[:limit]
    end = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    return cut[:end + 1] if end > limit // 2 else cut[:limit - 1].rstrip() + "…"


def signature_text(contact_info):
    from .candidat import nom
    lines = [contact_info.get("nom") or nom()]
    lines += [contact_info[k] for k in ("telephone", "email", "linkedin") if contact_info.get(k)]
    return "\n".join(lines)


def generate_message(contact, company, handler, profile, signature=""):
    prompt = message_prompt(contact, company, profile, signature)
    last = None
    for _ in range(3):
        try:
            msg = parse_message(handler.generate(prompt))
        except (ValueError, json.JSONDecodeError) as e:
            last = e
            continue
        if len(msg["note"]) <= NOTE_MAX:
            return msg
        last = msg
    if isinstance(last, dict):
        last["note"] = shorten_note(last["note"])
        return last
    raise RuntimeError(f"Gemini n'a pas rendu de message exploitable ({last}). Réessaie dans un instant.")


def pack_message(msg):
    """Stored in the sheet's « Message » column."""
    return f"[LinkedIn]\n{msg['note']}\n\n[Objet]\n{msg['objet']}\n\n[Mail]\n{msg['mail']}"


def unpack_message(text):
    m = re.match(r"\[LinkedIn\]\n(.*?)\n\n\[Objet\]\n(.*?)\n\n\[Mail\]\n(.*)", text or "", re.DOTALL)
    if not m:
        return None
    return {"note": m.group(1).strip(), "objet": m.group(2).strip(), "mail": m.group(3).strip()}


# ------------------------------------------------------------------ import of the user's existing tabs
import unicodedata

IMPORT_FIELDS = {   # field -> words that identify its column header
    "nom": ["nom complet", "nom", "name", "contact", "personne", "interlocuteur", "full name"],
    "prenom": ["prénom", "prenom", "first name", "firstname"],
    "poste": ["poste", "fonction", "titre", "title", "job", "rôle", "role", "position"],
    "entreprise": ["entreprise", "société", "societe", "company", "boîte", "boite", "organisation", "employeur", "structure"],
    "secteur": ["secteur", "domaine", "industrie", "industry"],
    "linkedin": ["linkedin", "profil", "profile", "url", "lien"],
    "email": ["email", "e-mail", "mail", "courriel", "adresse"],
    "statut": ["statut", "status", "état", "etat", "suivi", "retour", "réponse", "reponse"],
    "contacte_le": ["date", "contacté le", "contacte le", "envoyé le"],
    "notes": ["notes", "note", "commentaire", "commentaires", "remarque", "remarques", "info"],
}
FIELD_LABELS = {"nom": "Nom (ou nom complet)", "prenom": "Prénom", "poste": "Poste", "entreprise": "Entreprise",
                "secteur": "Secteur", "linkedin": "Lien LinkedIn", "email": "E-mail", "statut": "Statut / suivi",
                "contacte_le": "Date de contact", "notes": "Notes"}


def _norm(text):
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9@./ -]+", " ", text).strip()


def header_row(values):
    """Index of the header line: the first of the first 5 lines with at least 2 filled cells."""
    for i, row in enumerate(values[:5]):
        if sum(1 for v in row if str(v).strip()) >= 2:
            return i
    return 0


def guess_mapping(values):
    """{field: column index or None}, from header words, then from the cells' content."""
    if not values:
        return {f: None for f in IMPORT_FIELDS}
    h = header_row(values)
    headers = [_norm(v) for v in values[h]]
    body = values[h + 1:h + 51]
    mapping, used = {}, set()
    for field, words in IMPORT_FIELDS.items():
        best = None
        for w in words:                          # exact header first, then header containing the word
            w = _norm(w)
            for i, head in enumerate(headers):
                if i not in used and head == w:
                    best = i
                    break
            if best is None:
                for i, head in enumerate(headers):
                    if i not in used and head and re.search(rf"\b{re.escape(w)}\b", head):
                        best = i
                        break
            if best is not None:
                break
        mapping[field] = best
        if best is not None:
            used.add(best)

    def share(i, pattern):
        cells = [str(r[i]) for r in body if i < len(r) and str(r[i]).strip()]
        return sum(bool(re.search(pattern, c, re.IGNORECASE)) for c in cells) / len(cells) if cells else 0
    width = max((len(r) for r in values), default=0)
    for field, pattern in (("linkedin", r"linkedin\.com"), ("email", r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$")):
        col = mapping.get(field)
        if col is not None and share(col, pattern) >= 0.5:
            continue
        found = next((i for i in range(width) if i not in used and share(i, pattern) >= 0.5), None)
        if found is not None:
            if col is not None:
                used.discard(col)
            mapping[field] = found
            used.add(found)
        elif col is not None and share(col, pattern) == 0 and any(
                str(r[col]).strip() for r in body if col < len(r)):
            mapping[field] = None            # e.g. an "URL" column that holds something else
            used.discard(col)
    return mapping


def map_status(text):
    t = _norm(text)
    if not t:
        return "À contacter", ""
    for statut in STATUTS:
        if _norm(statut) == t:
            return statut, ""
    rules = [("entretien|rdv|rendez", "Entretien"), ("repondu|reponse|positif|rappel", "A répondu"),
             ("relance", "Relancé"), ("pas de reponse|sans reponse|negatif|refus|aucune", "Pas de réponse"),
             ("contacte|envoye|ecrit|message|mail|invitation|attente", "Contacté")]
    for pattern, statut in rules:
        if re.search(pattern, t):
            return statut, f"Statut d'origine : {text}"
    return "À contacter", f"Statut d'origine : {text}"


def build_import(values, mapping, known_contacts=(), known_companies=()):
    """Rows of one tab -> (contacts, companies) to add. Lines without a person become companies only."""
    h = header_row(values)
    seen = {(_norm(c.get("nom")), _norm(c.get("entreprise"))) for c in known_contacts}
    seen_comp = {_norm(c.get("entreprise")) for c in known_companies}
    contacts, companies = [], {}

    def cell(row, field):
        i = mapping.get(field)
        return str(row[i]).strip() if i is not None and i < len(row) else ""
    for row in values[h + 1:]:
        nom = " ".join(x for x in (cell(row, "prenom"), cell(row, "nom")) if x).strip()
        entreprise = cell(row, "entreprise")
        if entreprise and _norm(entreprise) not in seen_comp and _norm(entreprise) not in companies:
            companies[_norm(entreprise)] = {"entreprise": entreprise, "secteur": cell(row, "secteur"),
                                            "recherche": default_search()}
        if not nom:
            continue
        key = (_norm(nom), _norm(entreprise))
        if key in seen:
            continue
        seen.add(key)
        statut, extra = map_status(cell(row, "statut"))
        notes = " · ".join(x for x in (cell(row, "notes"), extra) if x)
        date_txt = cell(row, "contacte_le")
        c = {"nom": nom, "poste": cell(row, "poste"), "entreprise": entreprise, "linkedin": cell(row, "linkedin"),
             "email": cell(row, "email"), "statut": statut, "notes": notes}
        d = parse_fr_date(date_txt)
        if d and statut != "À contacter":
            c["contacte_le"] = fr_date(d)
            if statut == "Contacté":
                c["relance_le"] = fr_date(d + timedelta(days=FOLLOW_UP_DAYS))
        contacts.append(c)
    return contacts, list(companies.values())
