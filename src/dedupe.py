"""Same job posted on several boards (HelloWork, APEC, LinkedIn): keep only the first one seen."""
import re
import unicodedata

_GENDER = re.compile(r"\(?\b(?:h\s*/\s*f(?:\s*/\s*(?:x|d|nb))?|f\s*/\s*h(?:\s*/\s*(?:x|d|nb))?|m\s*/\s*f|f\s*/\s*m|w\s*/\s*m|m\s*/\s*w)\b\)?")
_NOISE = re.compile(r"\b(?:cdi|cdd|stage|alternance|h|f|x|e)\b")
_LEGAL = re.compile(r"\b(?:sas|sasu|sa|sarl|group|groupe|france|consulting|international)\b")


def _plain(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return text


def norm_title(title):
    t = _GENDER.sub(" ", _plain(title))
    t = re.sub(r"[^a-z0-9+#]+", " ", t)
    t = _NOISE.sub(" ", t)
    return " ".join(t.split())


def norm_company(company):
    c = re.sub(r"[^a-z0-9]+", " ", _plain(company))
    c = _LEGAL.sub(" ", c)
    return " ".join(c.split())


# Temp agencies show their own name instead of the client's: the same title from the same
# agency in two cities is two different jobs, so the place is part of the key for them.
AGENCY_SOURCES = {"Adecco", "CRIT"}


def norm_place(location):
    """City part of a location: « Massy, Essonne » / « Neuilly-sur-Seine (92200) » -> massy / neuilly sur seine."""
    first = re.split(r"[,(]", location or "")[0]
    return " ".join(re.sub(r"[^a-z0-9]+", " ", _plain(first)).split())


def key(offer):
    title, company = norm_title(offer.get("title")), norm_company(offer.get("company"))
    if not title or not company:
        return None
    if offer.get("source") in AGENCY_SOURCES:
        return f"{company}|{title}|{norm_place(offer.get('location'))}"
    return f"{company}|{title}"


def unflag_wrong_duplicates(offers):
    """Agency offers flagged as duplicates by the older key (without the place): judge them again.

    Returns the number of offers set back to « unchecked »."""
    fixed = 0
    for o in offers.values():
        if o.get("relevancy_check") != "duplicate" or o.get("source") not in AGENCY_SOURCES:
            continue
        first = offers.get(o.get("duplicate_of"))
        if first is not None and key(first) == key(o):
            continue
        o["relevancy_check"] = "unchecked"
        o.pop("duplicate_of", None)
        fixed += 1
    return fixed


def mark_duplicates(new_offers, known_offers):
    """Flag new offers already known (from any source) or repeated within the batch.

    A duplicate gets relevancy_check = "duplicate" and duplicate_of = <id of the first one>,
    so it is never judged, notified or shown twice. Returns the number flagged.
    """
    seen = {}
    for oid, o in known_offers.items():
        k = key(o)
        if k and o.get("relevancy_check") != "duplicate":
            seen.setdefault(k, oid)
    flagged = 0
    for oid, o in new_offers.items():
        k = key(o)
        if not k:
            continue
        if k in seen and seen[k] != oid:
            o["relevancy_check"] = "duplicate"
            o["duplicate_of"] = seen[k]
            flagged += 1
        else:
            seen[k] = oid
    return flagged
