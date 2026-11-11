"""Cover letter as a Word (.docx) file, built in memory for a download button."""
import io
import json
import re
import unicodedata
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
CONTACT_PATH = ROOT / "data" / "coordonnees.json"   # local only (data/* is git-ignored)
CONTACT_FIELDS = {"nom": "Nom", "telephone": "Téléphone", "email": "E-mail", "ville": "Ville (pour la date)",
                  "linkedin": "LinkedIn"}

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
INK = RGBColor(0x1E, 0x22, 0x30)
MUTED = RGBColor(0x55, 0x5B, 0x6E)


def load_contact(path=None):
    try:
        data = json.loads(Path(path or CONTACT_PATH).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    if not data.get("nom"):
        from .candidat import settings
        data["nom"] = settings().get("nom") or ""
    return data


def save_contact(contact, path=None):
    path = Path(path or CONTACT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(contact, ensure_ascii=False, indent=2), encoding="utf-8")


def file_name(offer):
    def slug(text, n):
        text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
        text = re.sub(r"\(?\b[HFhf]\s*/\s*[HFhf](\s*/\s*\w)?\b\)?", " ", text)
        return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:n]
    parts = ["Lettre", slug(offer.get("company"), 30), slug(offer.get("title"), 45)]
    return "_".join(p for p in parts if p) + ".docx"


def _para(doc, text="", size=11, bold=False, color=INK, align=None, after=0, before=0):
    p = doc.add_paragraph()
    if text:
        run = p.add_run(text)
        run.bold, run.font.size, run.font.color.rgb = bold, Pt(size), color
    fmt = p.paragraph_format
    fmt.space_after, fmt.space_before = Pt(after), Pt(before)
    if align is not None:
        p.alignment = align
    return p


_GENDER = re.compile(r"\s*[\(\[]?\b[HFMW]\s*/\s*[HFMW](\s*/\s*[XDN]+)?\b[\)\]]?\s*", re.IGNORECASE)


def clean_title(title):
    """« Développeur C# H/F » -> « Développeur C# » (for the subject line)."""
    return re.sub(r"\s{2,}", " ", _GENDER.sub(" ", title or "")).strip(" -–")


def build(offer, letter, contact=None, english=False, today=None):
    """Return the .docx as bytes."""
    contact = contact or load_contact()
    today = today or date.today()
    doc = Document()
    sec = doc.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)          # A4
    sec.left_margin = sec.right_margin = Cm(2.5)
    sec.top_margin, sec.bottom_margin = Cm(2.2), Cm(2.2)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Calibri", Pt(11)

    # Sender (top left)
    _para(doc, contact.get("nom", ""), size=13, bold=True)
    for key in ("telephone", "email", "linkedin"):
        if contact.get(key):
            _para(doc, contact[key], size=10, color=MUTED)

    # Recipient (right)
    _para(doc, before=14)
    _para(doc, offer.get("company") or "", bold=True, align=WD_ALIGN_PARAGRAPH.RIGHT)
    if offer.get("location"):
        _para(doc, offer["location"], size=10, color=MUTED, align=WD_ALIGN_PARAGRAPH.RIGHT)

    # Date and subject
    if english:
        when = f"{MONTHS[today.month - 1]} {today.day}, {today.year}"
        dated = f"{contact['ville']}, {when}" if contact.get("ville") else when
        subject_label, subject = "Subject: ", f"Application for the position of {clean_title(offer.get('title'))}"
    else:
        when = f"{today.day} {MOIS[today.month - 1]} {today.year}"
        dated = f"{contact['ville']}, le {when}" if contact.get("ville") else f"Le {when}"
        subject_label, subject = "Objet : ", f"Candidature au poste de {clean_title(offer.get('title'))}"
    _para(doc, dated, align=WD_ALIGN_PARAGRAPH.RIGHT, before=14, after=18)
    p = _para(doc, after=14)
    r = p.add_run(subject_label)
    r.bold = True
    p.add_run(subject)

    # Body: one paragraph per block of text; the signature line stays on its own
    blocks = [b.strip() for b in re.split(r"\n\s*\n", (letter or "").strip()) if b.strip()]
    if len(blocks) == 1:  # letter written with single line breaks
        blocks = [b.strip() for b in letter.strip().splitlines() if b.strip()]
    for i, block in enumerate(blocks):
        text = " ".join(line.strip() for line in block.splitlines())
        is_signature = i == len(blocks) - 1 and len(text) < 40 and text.lower() == (contact.get("nom") or "").lower()
        _para(doc, text, align=WD_ALIGN_PARAGRAPH.LEFT if (i == 0 or is_signature) else WD_ALIGN_PARAGRAPH.JUSTIFY,
              after=10, before=8 if is_signature else 0, bold=is_signature)

    buf = io.BytesIO()
    doc.core_properties.author = contact.get("nom", "")
    doc.core_properties.title = subject
    doc.save(buf)
    return buf.getvalue()
