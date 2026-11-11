"""Statistics on the user's applications (rows of the Google Sheet)."""
import re
import unicodedata
from collections import Counter, defaultdict
from urllib.parse import urlparse

from .sheets import parse_date

# First matching family wins (order matters: "chef de projet XR" is XR, "consultant PMO" is PMO)
FAMILIES = [
    ("XR / pédagogie", r"\b(vr|ar|xr|unity|3d)\b|realite|immersi|pedagog|e-?learning|\bformation"),
    ("Gestion de projet / PMO", r"\b(pmo|chef(fe)? de projets?|ingenieu?r(e)? (de |en )?(gestion de )?projets?|project|"
                                r"projets?|coordinat|amoa|charge(e)? de (projets?|missions?)|business analyst)\b"),
    ("Développement", r"\b(developpeu?r|developer|dev|logiciel|software|full ?stack|c#|c\+\+|python|java|web|"
                      r"concepteur|programm|code)"),
    ("Support / technicien", r"\b(support|technicien|helpdesk|assistance|poste de travail|exploitation|"
                             r"proximite|mco|applicatif|n1|n2|n3)\b"),
    ("Conseil", r"\b(consultant|conseil)"),
    ("Commercial / affaires", r"\b(affaires|commercial|business developer|avant[- ]vente|vente)\b"),
    ("Test / validation", r"\b(test|validation|verification|v&v|qualite)\b"),
    ("IT généraliste", r"\b(informatique|technologie de l.information|generaliste|applications?|solutions? (digitales|ia)|"
                       r"deploiement|systemes?|incident|si|ia|low code)\b"),
]
_FAMILIES = [(name, re.compile(rx)) for name, rx in FAMILIES]


def _plain(text):
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()


def family(poste):
    p = _plain(poste)
    if "spontanee" in p:
        return "Candidature spontanée"
    for name, rx in _FAMILIES:
        if rx.search(p):
            return name
    return "Autre"


def source_of(url):
    u = (url or "").strip().lower()
    if not u:
        return "Sans lien"
    host = urlparse(u if "://" in u else "https://" + u).netloc
    for needle, name in (("linkedin", "LinkedIn"), ("indeed", "Indeed"), ("hellowork", "HelloWork"),
                         ("apec", "APEC"), ("francetravail", "France Travail"), ("pole-emploi", "France Travail"), ("welcometothejungle", "Welcome to the Jungle"),
                         ("businessfrance", "VIE (Business France)"), ("jobteaser", "JobTeaser"),
                         ("myworkdayjobs", "Site de l'entreprise"), ("careers", "Site de l'entreprise"),
                         ("recrutement", "Site de l'entreprise"), ("carrieres", "Site de l'entreprise")):
        if needle in host:
            return name
    return "Autre site"


def outcome(retour):
    r = _plain(retour).strip()
    if r == "positif":
        return "positif"
    if r == "negatif":
        return "negatif"
    return "attente"


def breakdown(rows, by):
    """Per group: candidatures, positifs, négatifs, sans réponse, taux de réponse, taux positif."""
    acc = defaultdict(Counter)
    for r in rows:
        g = by(r)
        acc[g]["total"] += 1
        acc[g][outcome(r.get("retour"))] += 1
    table = []
    for g, c in acc.items():
        answered = c["positif"] + c["negatif"]
        table.append({
            "Catégorie": g,
            "Candidatures": c["total"],
            "Positifs": c["positif"],
            "Négatifs": c["negatif"],
            "Sans réponse": c["attente"],
            "Taux de réponse": round(100 * answered / c["total"]) if c["total"] else 0,
            "Taux positif": round(100 * c["positif"] / c["total"], 1) if c["total"] else 0.0,
        })
    table.sort(key=lambda t: t["Candidatures"], reverse=True)
    return table


def by_month(rows):
    months = defaultdict(Counter)
    for r in rows:
        d = parse_date(r.get("date"))
        if not d:
            continue
        m = d.strftime("%Y-%m")
        months[m]["Candidatures"] += 1
        months[m]["Positifs"] += outcome(r.get("retour")) == "positif"
    return [{"Mois": m, "Candidatures": c["Candidatures"], "Positifs": c["Positifs"]} for m, c in sorted(months.items())]


def insights(rows, min_count=5):
    """A few plain-French findings, strongest first."""
    out = []
    total = len(rows)
    if not total:
        return out
    pos = sum(outcome(r.get("retour")) == "positif" for r in rows)
    neg = sum(outcome(r.get("retour")) == "negatif" for r in rows)
    out.append(f"Sur {total} candidatures : {pos} retour(s) positif(s) ({100 * pos / total:.1f} %), "
               f"{neg} négatif(s), {total - pos - neg} sans réponse ({100 * (total - pos - neg) / total:.0f} %).")
    fam = [t for t in breakdown(rows, lambda r: family(r.get("poste"))) if t["Candidatures"] >= min_count]
    if fam:
        best = max(fam, key=lambda t: (t["Taux positif"], t["Candidatures"]))
        if best["Positifs"]:
            out.append(f"Les postes « {best['Catégorie']} » te répondent le mieux : {best['Positifs']} positif(s) "
                       f"sur {best['Candidatures']} ({best['Taux positif']} %).")
        zero = [t["Catégorie"] for t in fam if t["Positifs"] == 0]
        if zero:
            out.append("Aucun retour positif pour l'instant en : " + ", ".join(zero) + ".")
    src = [t for t in breakdown(rows, lambda r: source_of(r.get("url") or r.get("lien"))) if t["Candidatures"] >= min_count]
    if src:
        best = max(src, key=lambda t: (t["Taux de réponse"], t["Candidatures"]))
        out.append(f"Source qui répond le plus : {best['Catégorie']} ({best['Taux de réponse']} % de réponses, "
                   f"positives ou négatives).")
    return out
