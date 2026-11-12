"""CV adapted to an offer, built from the candidate's own PowerPoint CV models.

One model per CV of cdi_search.yaml (and per VIE CV), kept on the PC only in
data/cv_modeles/<key>.pptx (data/* is git-ignored: a CV holds personal data).

Gemini only rewrites some pieces of text of the model (job title, profile, skills,
descriptions of experiences). Layout, photo, fonts, names, dates, companies and contact
details are never touched, and every new text must stay about as long as the old one so
the page keeps its layout.
"""
import io
import json
import re
import unicodedata
from pathlib import Path

from pptx import Presentation

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "data" / "cv_modeles"
VIE_KEYS = ("vie_fr", "vie_en")
MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

_PHONE = re.compile(r"(\+?\d[\d .]{7,}\d)")
_DATE_ONLY = re.compile(r"[\s\d–\-/.,]*(?:(?:janv|févr|fevr|mars|avr|mai|juin|juil|août|aout|sept|oct|nov|déc|dec|"
                        r"jan|feb|mar|apr|may|jun|jul|aug|sep|dec)[a-zéû.]*)?[\s\d–\-/.,]*(?:aujourd'hui|présent|"
                        r"present|now)?[\s\d–\-/.,]*", re.IGNORECASE)


# ------------------------------------------------------------------ models on disk
def model_keys():
    from . import candidat
    return list(candidat.cvs()) + list(VIE_KEYS)


def model_path(key, models_dir=None):
    path = Path(models_dir or MODELS_DIR) / f"{key}.pptx"
    return path if path.exists() else None


def available_models(models_dir=None):
    return [k for k in model_keys() if model_path(k, models_dir)]


def save_model(key, data, models_dir=None):
    """Check that `data` is a PowerPoint file with text, then keep it as the model for `key`."""
    try:
        segs = segments(data)
    except Exception as e:
        raise ValueError("ce fichier n'est pas un PowerPoint (.pptx) lisible") from e
    if not any(s["editable"] for s in segs):
        raise ValueError("aucun texte modifiable trouvé dans ce PowerPoint")
    folder = Path(models_dir or MODELS_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{key}.pptx").write_bytes(data)


def delete_model(key, models_dir=None):
    path = model_path(key, models_dir)
    if path:
        path.unlink()


def model_for_offer(offer, models_dir=None):
    """The model to use by default: the CV advised for the offer, else the first one available."""
    available = available_models(models_dir)
    if not available:
        return None
    return offer.get("cv") if offer.get("cv") in available else available[0]


# ------------------------------------------------------------------ text pieces
def _open(src):
    if isinstance(src, (bytes, bytearray)):
        return Presentation(io.BytesIO(src))
    return Presentation(str(src))


def _shapes(shapes):
    for sh in shapes:
        if sh.shape_type == 6 and hasattr(sh, "shapes"):          # group
            yield from _shapes(sh.shapes)
        else:
            yield sh


def _paragraphs(prs):
    """Every paragraph of the file, always in the same order."""
    for slide in prs.slides:
        for sh in _shapes(slide.shapes):
            frames = []
            if getattr(sh, "has_text_frame", False) and sh.has_text_frame:
                frames.append(sh.text_frame)
            if getattr(sh, "has_table", False) and sh.has_table:
                frames += [cell.text_frame for row in sh.table.rows for cell in row.cells]
            for tf in frames:
                yield from tf.paragraphs


def _is_upper(text):
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def _protected(text):
    t = text.strip()
    low = t.lower()
    return (len(t) < 4
            or "@" in t or "linkedin" in low or "http" in low or "www." in low
            or bool(_PHONE.search(t))
            or bool(_DATE_ONLY.fullmatch(t))
            or " — " in t                       # « Entreprise — Poste », « Diplôme — École »
            or t.endswith(":")                  # bold labels « Développement : »
            or t in ("•", "-", "–"))


_PUNCT = re.compile(r"[\s.,;:!?…)’'»]*")


def _units(prs):
    """Paragraphs cut into units: a protected run alone, or a run of editable text (with the
    punctuation that follows it) that Gemini may rewrite as a whole. Yields (id, runs, kind, editable)."""
    uppers = 0
    for pi, para in enumerate(_paragraphs(prs)):
        runs = list(para.runs)
        i = 0
        while i < len(runs):
            text = runs[i].text
            if _protected(text):
                yield f"p{pi}.{i}", [runs[i]], "texte", False
                i += 1
                continue
            if _is_upper(text):
                uppers += 1
                kind = "nom" if uppers == 1 else "titre" if uppers == 2 else "rubrique"
                yield f"p{pi}.{i}", [runs[i]], kind, kind == "titre"
                i += 1
                continue
            j = i + 1
            while j < len(runs) and not _is_upper(runs[j].text) and (
                    not _protected(runs[j].text) or _PUNCT.fullmatch(runs[j].text)):
                j += 1
            yield f"p{pi}.{i}", runs[i:j], "texte", True
            i = j


def _bold(run):
    return bool(run.font.bold)


def _joined(runs):
    """Text of a unit; bold runs are written **like this** when the unit mixes bold and plain."""
    mixed = len({_bold(r) for r in runs if r.text.strip()}) > 1
    return "".join(f"**{r.text.strip()}**".join(_spaces(r.text)) if mixed and _bold(r) and r.text.strip()
                   else r.text for r in runs)


def _spaces(text):
    return text[:len(text) - len(text.lstrip())], text[len(text.rstrip()):]


def segments(src):
    """[{id, text, editable, kind}]. kind: 'nom', 'titre' (job title under the name),
    'rubrique' (section heading) or 'texte'."""
    return [{"id": uid, "text": _joined(runs), "editable": editable, "kind": kind}
            for uid, runs, kind, editable in _units(_open(src))]


def max_len(text):
    return int(len(text.replace("**", "").strip()) * 1.12) + 8


# ------------------------------------------------------------------ Gemini
def cv_prompt(offer_text, profile, segs):
    editable = {s["id"]: s["text"].strip() for s in segs if s["editable"]}
    limits = {sid: max_len(t) for sid, t in editable.items()}
    titre = next((s["id"] for s in segs if s["kind"] == "titre"), None)
    full_cv = "\n".join(s["text"] for s in segs if s["text"].strip())
    return (
        "Tu adaptes un CV existant à une offre d'emploi, sans changer sa mise en page.\n"
        "On te donne des morceaux de texte du CV, chacun avec un identifiant. Réécris seulement ceux "
        "qui gagnent à être adaptés à l'offre.\n"
        "Règles strictes :\n"
        "- Garde la langue du CV.\n"
        "- N'invente RIEN : aucune expérience, compétence, outil, langage, chiffre, certification ou "
        "responsabilité qui ne figure pas déjà dans le CV ou le profil. Tu peux reformuler, réordonner une "
        "liste (le plus utile pour l'offre en premier), reprendre le vocabulaire de l'offre quand il décrit "
        "la même chose, et mettre en avant ce qui correspond à l'offre.\n"
        + (f"- {titre} est l'intitulé sous le nom : mets l'intitulé du poste visé, court (40 caractères max), "
           "sans « H/F ».\n" if titre else "") +
        "- Les passages entre ** ** sont en gras (ton école, le poste recherché). Garde le même nombre de "
        "passages en gras au même endroit (le poste recherché peut changer) et n'en ajoute aucun.\n"
        "- Respecte la longueur maximale de chaque morceau (en caractères), sinon la page déborde.\n"
        "- Ne touche pas aux morceaux que tu ne listes pas.\n"
        "- Réponds UNIQUEMENT avec un objet JSON, sans markdown :\n"
        '{"modifications": {"<id>": "<nouveau texte>"}, "resume": "<2 phrases : ce que tu as mis en avant '
        'et ce qui manque au CV pour cette offre>"}\n\n'
        "=== MORCEAUX MODIFIABLES (id → texte) ===\n" + json.dumps(editable, ensure_ascii=False, indent=0) + "\n\n"
        "=== LONGUEUR MAXIMALE (id → caractères) ===\n" + json.dumps(limits) + "\n\n"
        "=== CV COMPLET (pour le contexte) ===\n" + full_cv + "\n\n"
        "=== PROFIL ===\n" + (profile or "") + "\n\n"
        "=== OFFRE ===\n" + offer_text
    )


def parse_answer(text):
    m = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not m:
        raise ValueError("réponse de Gemini illisible")
    data = json.loads(m.group(0))
    if not isinstance(data, dict) or not isinstance(data.get("modifications"), dict):
        raise ValueError("réponse de Gemini sans modifications")
    return data


def clean_changes(segs, changes):
    """Keep only allowed, sensible changes; restore the spaces around each piece."""
    by_id = {s["id"]: s for s in segs}
    out = {}
    for sid, new in (changes or {}).items():
        seg = by_id.get(sid)
        if not seg or not seg["editable"] or not isinstance(new, str):
            continue
        old = seg["text"]
        new = " ".join(new.split())
        if not new or new == old.strip():
            continue
        if seg["kind"] == "titre":
            new = re.sub(r"\s*\(?\b[HFhf]\s*/\s*[HFhf]\b\)?", "", new).strip()
            if _is_upper(old.strip()):
                new = new.upper()
            if len(new) > 40:
                continue
        elif len(new) > max_len(old):
            continue                       # too long: the page would overflow
        new = _limit_bold(new, old.count("**") // 2)
        lead = old[:len(old) - len(old.lstrip())]
        trail = old[len(old.rstrip()):]
        out[sid] = lead + new + trail
    return out


def _limit_bold(text, allowed):
    """Keep at most `allowed` bold passages (the first ones): Gemini must not add bold."""
    out, kept = [], 0
    for part, bold in _pieces(text):
        if bold and kept < allowed:
            out.append(f"**{part}**")
            kept += 1
        else:
            out.append(part)
    return "".join(out)


def generate(offer_text, handler, profile, model_bytes, tries=2):
    """Ask Gemini for the changes. Returns {"modifications": {...}, "resume": "..."}."""
    segs = segments(model_bytes)
    prompt = cv_prompt(offer_text, profile, segs)
    last_error = None
    for _ in range(tries):
        try:
            data = parse_answer(handler.generate(prompt))
        except (ValueError, json.JSONDecodeError) as e:
            last_error = e
            continue
        changes = clean_changes(segs, data["modifications"])
        if changes:
            return {"modifications": changes, "resume": str(data.get("resume") or "").strip()}
        last_error = ValueError("Gemini n'a proposé aucune modification utilisable")
    raise RuntimeError(f"Impossible d'adapter le CV : {last_error}")


# ------------------------------------------------------------------ build and show
def _pieces(text):
    """« a **b** c » -> [("a ", False), ("b", True), (" c", False)]"""
    out = []
    for k, part in enumerate(re.split(r"\*\*", text)):
        if part:
            out.append((part, k % 2 == 1))
    return out


def _replace(runs, new):
    import copy
    pieces = _pieces(new) if "**" in new else [(new, None)]
    plain = next((r for r in runs if not _bold(r) and r.text.strip()), runs[0])
    bold = next((r for r in runs if _bold(r) and r.text.strip()), None)
    anchor = runs[0]._r
    for text, is_bold in pieces:
        model = bold if (is_bold and bold is not None) else plain if is_bold is not None else runs[0]
        r = copy.deepcopy(model._r)
        t = r.find("{http://schemas.openxmlformats.org/drawingml/2006/main}t")
        t.text = text
        anchor.addprevious(r)
    for run in runs:
        run._r.getparent().remove(run._r)


def build(model_bytes, changes):
    """The model with the changes applied, as .pptx bytes (formatting of each piece kept)."""
    prs = _open(model_bytes)
    changes = changes or {}
    for uid, runs, _kind, editable in list(_units(prs)):
        if editable and uid in changes:
            _replace(runs, changes[uid])
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def diff(model_bytes, changes):
    """[(before, after)] for display."""
    old = {s["id"]: s["text"].replace("**", "").strip() for s in segments(model_bytes)}
    return [(old[sid], new.replace("**", "").strip()) for sid, new in (changes or {}).items() if sid in old]


def file_name(offer, nom=""):
    def slug(text, n):
        text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
        text = re.sub(r"\(?\b[HFhf]\s*/\s*[HFhf](\s*/\s*\w)?\b\)?", " ", text)
        return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:n]
    parts = ["CV", slug(nom, 30), slug(offer.get("company"), 30)]
    return "_".join(p for p in parts if p) + ".pptx"
