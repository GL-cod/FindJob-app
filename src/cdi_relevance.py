"""Gemini prompts for the CDI watcher: relevance verdict + cover-letter draft."""
import json
import logging
import re

from . import candidat
from .gemini_handler import AllModelsExhausted

log = logging.getLogger(__name__)

MAX_DESC_CHARS = 6000


def cv_text(key):
    """« CV « Ingénieur Projet » » for messages (the first CV if the key is unknown)."""
    return f"CV « {candidat.cv_label(key) or candidat.cv_label(candidat.default_cv())} »"


def offer_text(offer):
    parts = [
        f"Intitulé : {offer.get('title', '')}",
        f"Entreprise : {offer.get('company', '')}",
        f"Lieu : {offer.get('location', '')}",
        f"Contrat : {offer.get('contract', '') or 'non précisé'}",
        f"Source : {offer.get('source', '')}",
        "Description :",
        (offer.get("description") or "(pas de description)")[:MAX_DESC_CHARS],
    ]
    return "\n".join(parts)


def relevance_prompt(offer, profile, max_years=3, excluded_domains=(), feedback_block=""):
    metiers = candidat.metiers()
    cvs = candidat.cvs()
    cv_choices = "|".join(f'"{k}"' for k in cvs)
    if len(cvs) > 1:
        cv_block = ("Choisis aussi le CV à envoyer :\n"
                    + "".join(f"- \"{k}\" ({v['nom']}) : {v['quand'] or 'à toi de juger'}\n" for k, v in cvs.items()) + "\n")
    else:
        cv_block = f"Pour le champ cv, réponds toujours \"{next(iter(cvs))}\".\n\n"
    domains = ""
    if excluded_domains:
        domains = ("Réponds aussi NON si le poste relève d'un de ces domaines, que le candidat ne veut pas :\n"
                   + "\n".join(f"- {d}" for d in excluded_domains) + "\n")
    return (
        "Tu aides un jeune diplômé à trier des offres d'emploi en France.\n"
        "Décide si l'offre correspond à son profil et s'il a des chances réalistes "
        f"d'être retenu (poste junior / débutant / 0-{max_years} ans d'expérience).\n"
        "Relève d'abord l'expérience MINIMALE exigée par l'offre, en années : "
        "\"3 à 5 ans\" -> 3, \"5 ans minimum\" -> 5, \"confirmé\" ou \"senior\" sans chiffre -> 5, "
        "\"débutant accepté\" ou rien de précisé -> 0.\n"
        f"Réponds NON si : expérience minimale exigée supérieure à {max_years} ans, "
        "stage ou alternance, "
        + (f"métier sans lien avec {metiers}, " if metiers else "métier sans lien avec le profil, ")
        + "ou compétence obligatoire qu'il n'a pas du tout.\n"
        + domains + feedback_block + cv_block +
        "Donne enfin une note d'adéquation sur 10 : 9-10 = correspond très bien et chances réelles, "
        "7-8 = bonne piste, 5-6 = possible mais pas idéal, 0-4 = à écarter (alors relevant = false).\n"
        "Réponds UNIQUEMENT avec un objet JSON sur une ligne, sans texte autour :\n"
        '{"relevant": true|false, "score": <0-10>, "years_required": <entier>, "cv": ' + cv_choices + ', '
        '"reason": "<une phrase courte en français qui justifie la note>"}\n\n'
        "=== PROFIL DU CANDIDAT ===\n" + profile + "\n\n"
        "=== OFFRE ===\n" + offer_text(offer)
    )


def letter_prompt(offer, profile, cv_key):
    angle = candidat.cv_angle(cv_key)
    return (
        "Rédige en français un brouillon de lettre de motivation pour cette offre.\n"
        "Contraintes :\n"
        "- 180 à 230 mots, ton professionnel mais naturel, pas de formules creuses.\n"
        + (f"- Angle : {angle}.\n" if angle else "") +
        "- Appuie-toi UNIQUEMENT sur les faits du profil. N'invente aucune expérience, "
        "compétence, chiffre ou certification.\n"
        "- Fais le lien concret entre 2 ou 3 éléments du profil et les besoins de l'offre.\n"
        "- Pas d'en-tête (adresse, date, objet), commence par « Madame, Monsieur, » "
        f"et termine par une formule de politesse courte {candidat.signature_rule()}.\n"
        "- Texte brut, sans markdown.\n\n"
        "=== PROFIL ===\n" + profile + "\n\n"
        "=== OFFRE ===\n" + offer_text(offer)
    )


_EXP_LINE = re.compile(r"exp[ée]rien|experience|years?\b|\bans?\b.*\b(minimum|min\.?)\b", re.IGNORECASE)
_YEAR_PATTERNS = [
    re.compile(r"(\d{1,2})\s*(?:à|a|-|/|–)\s*\d{1,2}\s*(?:ans|an|years?)", re.IGNORECASE),
    re.compile(r"(?:minimum|au moins|min\.?)\s*(?:de\s*|d['’]\s*)?(\d{1,2})\s*(?:ans|an|years?)", re.IGNORECASE),
    re.compile(r"(\d{1,2})\s*\+\s*(?:ans|an|years?)|(\d{1,2})\s*(?:ans|an|years?)\s*\+", re.IGNORECASE),
    re.compile(r"(\d{1,2})\s*(?:ans|an)\s*(?:minimum|min\.?|et plus|ou plus|au moins)", re.IGNORECASE),
    re.compile(r"(\d{1,2})\s*(?:ans|an)\s*(?:d['’]\s*|de\s*)?exp[ée]rience", re.IGNORECASE),
    re.compile(r"exp[ée]rience\s*(?:\w+\s*){0,6}?(?:de|d['’])\s*(\d{1,2})\s*(?:ans|an)\b", re.IGNORECASE),
    re.compile(r"(\d{1,2})\s*\+?\s*years?\s*(?:of\s*)?(?:\w+\s*){0,3}experience", re.IGNORECASE),
    re.compile(r"exp[ée]rience[^:\n]{0,25}:\s*(?:\w+\s+){0,2}?(\d{1,2})\s*(?:ans|an|years?)\b", re.IGNORECASE),
]


def required_years(text):
    """Minimum years of experience stated in an offer, or None if not found.

    Only lines that talk about experience are read, so "Bac+5", "contrat de 2 ans"
    or "entreprise créée il y a 30 ans" are ignored. The first requirement found wins.
    """
    for line in re.split(r"[\n.;•]", text or ""):
        if not _EXP_LINE.search(line):
            continue
        for pattern in _YEAR_PATTERNS:
            m = pattern.search(line)
            if not m:
                continue
            value = next(int(g) for g in m.groups() if g)
            if 1 <= value <= 15:
                return value
    return None


def parse_score(answer):
    """Score out of 10 from Gemini's JSON answer, or None."""
    m = re.search(r'"score"\s*:\s*"?(\d+(?:[.,]\d+)?)', answer or "")
    if not m:
        return None
    return max(0, min(10, round(float(m.group(1).replace(",", ".")))))


def parse_verdict(answer):
    """Parse Gemini's JSON verdict, tolerating code fences or a bare YES/NO."""
    text = (answer or "").strip()
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            relevant = data.get("relevant")
            if isinstance(relevant, str):
                relevant = relevant.strip().lower() in ("true", "yes", "oui")
            cv = candidat.normalize_cv(data.get("cv", ""))
            try:
                years = int(float(data.get("years_required") or 0))
            except (TypeError, ValueError):
                years = 0
            return bool(relevant), cv, str(data.get("reason", "")).strip(), years
        except json.JSONDecodeError:
            pass
    upper = text.upper()
    return upper.startswith(("YES", "OUI", "TRUE")), candidat.default_cv(), "", 0


def check_offers(offers, profile, handler, max_checks, save_func=None, draft_letters=True, max_years=3,
                 excluded_domains=(), feedback_block=""):
    """Judge unchecked offers in place. Returns {id: offer} of newly relevant ones."""
    relevant = {}
    checked = 0
    for offer_id, offer in offers.items():
        if offer.get("relevancy_check") != "unchecked":
            continue
        if checked >= max_checks:
            log.info(f"Reached max_checks_per_run ({max_checks}); the rest waits for the next run.")
            break

        stated = required_years(offer.get("description", ""))
        if stated is not None and stated > max_years:
            offer["relevancy_check"] = "not_relevant"
            offer["reason"] = f"{stated} ans d'expérience exigés"
            log.info(f"Skipped {offer_id} without Gemini: {stated} years of experience required.")
            continue

        try:
            answer = handler.generate(relevance_prompt(offer, profile, max_years, excluded_domains, feedback_block))
            is_rel, cv, reason, years = parse_verdict(answer)
            score = parse_score(answer)
        except AllModelsExhausted:
            log.error("RELEVANCE ERROR - all Gemini models exhausted; stopping checks for this run.")
            break
        except Exception as e:
            log.error(f"RELEVANCE ERROR - offer {offer_id}: {e}")
            continue

        checked += 1
        if years > max_years:
            is_rel = False
            reason = f"{years} ans d'expérience exigés"
        if score is not None and score < 5:
            is_rel = False
        offer["score"] = score
        offer["relevancy_check"] = "relevant" if is_rel else "not_relevant"
        offer["reason"] = reason
        offer["cv"] = cv
        log.info(f"Checked {offer_id} [{offer['source']}] {offer['title'][:60]!r}: {offer['relevancy_check']}")

        if is_rel:
            if draft_letters:
                try:
                    offer["letter"] = handler.generate(letter_prompt(offer, profile, cv)).strip()
                except AllModelsExhausted:
                    log.warning("Gemini quota exhausted before the cover letter; sending the offer without it.")
                    offer["letter"] = ""
                except Exception as e:
                    log.warning(f"Cover letter failed for {offer_id}: {e}")
                    offer["letter"] = ""
            relevant[offer_id] = offer

        if save_func is not None and checked % 10 == 0:
            save_func(offers)

    if save_func is not None:
        save_func(offers)
    return relevant
