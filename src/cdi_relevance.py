"""Gemini prompts for the CDI watcher: relevance verdict + cover-letter draft."""
import json
import logging
import re

from . import candidat, temps_travail
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


def _rules(max_years, excluded_domains, feedback_block, work_time):
    """Sorting rules shared by the one-offer and the batch prompts: (rules text, cv choices)."""
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
        + (f"ou métier sans lien avec {metiers}.\n" if metiers else "ou métier sans lien avec le profil.\n")
        + temps_travail.prompt_rule(work_time) + domains + feedback_block + cv_block +
        "Donne enfin une note d'adéquation sur 10 : 9-10 = correspond très bien et chances réelles, "
        "7-8 = bonne piste, 5-6 = possible mais pas idéal, 0-4 = faible correspondance.\n"
    ), cv_choices


def relevance_prompt(offer, profile, max_years=3, excluded_domains=(), feedback_block="", work_time=None):
    rules, cv_choices = _rules(max_years, excluded_domains, feedback_block, work_time)
    return (
        rules +
        "Réponds UNIQUEMENT avec un objet JSON sur une ligne, sans texte autour :\n"
        '{"relevant": true|false, "score": <0-10>, "years_required": <entier>, "cv": ' + cv_choices + ', '
        '"reason": "<une phrase courte en français qui justifie la note>"}\n\n'
        "=== PROFIL DU CANDIDAT ===\n" + profile + "\n\n"
        "=== OFFRE ===\n" + offer_text(offer)
    )


BATCH_DESC_CHARS = 3000     # per offer in a batch (the whole prompt stays reasonable)
JUDGE_TEMPERATURE = 0       # same offer, same verdict (Gemini's default 1.0 gives varying verdicts)


def ask(handler, prompt):
    """A sorting question to Gemini, with a steady answer (temperature 0) when the handler allows it."""
    try:
        return handler.generate(prompt, temperature=JUDGE_TEMPERATURE)
    except TypeError:            # handlers without the parameter (tests, older code)
        return handler.generate(prompt)


def batch_relevance_prompt(offers, profile, max_years=3, excluded_domains=(), feedback_block="", work_time=None):
    """One prompt for several offers ([(label, offer)]): Gemini judges each one on its own."""
    rules, cv_choices = _rules(max_years, excluded_domains, feedback_block, work_time)
    blocks = []
    for label, offer in offers:
        text = offer_text({**offer, "description": (offer.get("description") or "")[:BATCH_DESC_CHARS]})
        blocks.append(f"=== OFFRE {label} ===\n{text}")
    return (
        f"Il y a {len(offers)} offres à juger. Juge chacune SÉPARÉMENT, comme si elle était seule, avec les "
        "mêmes règles : ne mélange jamais les informations de deux offres.\n" + rules +
        "Réponds UNIQUEMENT avec un tableau JSON, un objet par offre, dans l'ordre, sans texte autour. "
        "Recopie exactement l'identifiant et l'intitulé de chaque offre :\n"
        '[{"offre": "<identifiant, ex. ' + offers[0][0] + '>", "intitule": "<intitulé de l\'offre, recopié>", '
        '"relevant": true|false, "score": <0-10>, "years_required": <entier>, "cv": ' + cv_choices + ', '
        '"reason": "<une phrase courte en français qui justifie la note>"}, ...]\n\n'
        "=== PROFIL DU CANDIDAT ===\n" + profile + "\n\n" + "\n\n".join(blocks)
    )


def parse_batch(answer):
    """{label: (relevant, cv, reason, years, score)} from a batch answer (missing offers left out)."""
    text = (answer or "").strip()
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return {}
    try:
        items = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    out = {}
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("offre"):
            continue
        one = json.dumps(item, ensure_ascii=False)
        out[str(item["offre"]).strip()] = (*parse_verdict(one), parse_score(one), str(item.get("intitule") or ""))
    return out


def same_title(echo, title):
    """Did Gemini answer about this offer? (its copy of the title starts like the real one)"""
    a, b = _plain(echo), _plain(title)
    a, b = re.sub(r"[^a-z0-9]+", "", a), re.sub(r"[^a-z0-9]+", "", b)
    n = min(len(a), len(b), 20)
    return n > 0 and a[:n] == b[:n]


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
        "- Texte brut, sans markdown.\n"
        + "".join(f"- {rule}\n" for rule in candidat.letter_rules()) +
        "\n=== PROFIL ===\n" + profile + "\n\n"
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


def _plain(text):
    import unicodedata
    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()


def in_priority_places(location, places):
    """Is the offer's place one of `places` (cdi_search.yaml, `priorite_lieux`)?

    A number is a département: « Paris - 75 », « Neuilly (92200) », « 92 - Hauts-de-Seine ».
    A name matches anywhere, accents and case ignored: « Massy, Essonne », « Paris, Île-de-France »."""
    loc = _plain(location)
    if not loc:
        return False
    for p in places or []:
        p = str(p).strip()
        if not p:
            continue
        if p.isdigit():
            dep = p.zfill(2)
            if re.search(rf"(?<!\d){dep}(?:\d{{3}})?(?!\d)", loc):
                return True
        elif re.search(rf"(?<![a-z]){re.escape(_plain(p))}(?![a-z])", loc):
            return True
    return False


def judging_order(offers, places=()):
    """Ids of the offers to judge: priority places first; inside each group, the sites take turns
    (newest first on each), so a site with hundreds of new offers (HelloWork) does not take all
    the judgments of a run while Adecco or CRIT wait."""
    def newest(o):
        return o.get("posted") or o.get("first_seen") or ""

    groups = {True: {}, False: {}}
    for oid, o in offers.items():
        if o.get("relevancy_check") == "unchecked":
            prio = in_priority_places(o.get("location"), places)
            groups[prio].setdefault(o.get("source") or "", []).append((oid, o))
    order = []
    for prio in (True, False):
        queues = [sorted(q, key=lambda item: newest(item[1]), reverse=True) for q in groups[prio].values()]
        queues.sort(key=lambda q: newest(q[0][1]), reverse=True)
        for rank in range(max((len(q) for q in queues), default=0)):
            order.extend(q[rank][0] for q in queues if rank < len(q))
    return order


def check_offers(offers, profile, handler, max_checks, save_func=None, draft_letters=True, max_years=3,
                 excluded_domains=(), feedback_block="", work_time=None, priority_places=(), batch_size=5,
                 describe=None):
    """Judge unchecked offers in place, priority places first and the sites in turn.

    Offers go to Gemini by batches of `batch_size` (one request for several offers: many more
    offers judged per run); an offer missing from a batch answer is judged alone. `describe(offer)`
    downloads a missing description just before judging (True = done, False = offer removed from
    the site, None = not possible now: the offer waits). Returns {id: offer} of newly relevant ones."""
    relevant = {}
    checked = 0
    rule_args = (max_years, excluded_domains, feedback_block, work_time)
    batch = []
    stop = False

    def record(offer_id, verdict):
        nonlocal checked
        is_rel, cv, reason, years, score = verdict
        offer = offers[offer_id]
        checked += 1
        if years > max_years:
            is_rel = False
            reason = f"{years} ans d'expérience exigés"
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

    def judge_alone(offer_id):
        try:
            answer = ask(handler, relevance_prompt(offers[offer_id], profile, *rule_args))
        except AllModelsExhausted:
            raise
        except Exception as e:
            log.error(f"RELEVANCE ERROR - offer {offer_id}: {e}")
            return
        record(offer_id, (*parse_verdict(answer), parse_score(answer)))

    def flush():
        nonlocal stop
        ids = list(batch)
        batch.clear()
        if not ids or stop:
            return
        try:
            if len(ids) == 1:
                judge_alone(ids[0])
                return
            labelled = [(f"O{i + 1}", oid) for i, oid in enumerate(ids)]
            try:
                answer = ask(handler, batch_relevance_prompt([(lab, offers[oid]) for lab, oid in labelled],
                                                             profile, *rule_args))
                verdicts = parse_batch(answer)
            except AllModelsExhausted:
                raise
            except Exception as e:
                log.error(f"RELEVANCE ERROR - batch of {len(ids)} offer(s): {e}; judged one by one.")
                verdicts = {}
            # an answer whose title is not the offer's own (offers mixed up): judged again alone
            verdicts = {lab: v for lab, v in verdicts.items()
                        if lab in dict(labelled) and same_title(v[5], offers[dict(labelled)[lab]].get("title"))}
            missing = [oid for lab, oid in labelled if lab not in verdicts]
            for lab, oid in labelled:
                if lab in verdicts:
                    record(oid, verdicts[lab][:5])
            if missing and verdicts:
                log.warning(f"{len(missing)} offer(s) missing from a batch answer: judged one by one.")
            for oid in missing:
                judge_alone(oid)
        except AllModelsExhausted:
            log.error("RELEVANCE ERROR - all Gemini models exhausted; stopping checks for this run.")
            stop = True

    for offer_id in judging_order(offers, priority_places):
        if stop:
            break
        if checked + len(batch) >= max_checks:
            flush()
            if checked >= max_checks or stop:
                log.info(f"Reached max_checks_per_run ({max_checks}); the rest waits for the next run.")
                break
        offer = offers[offer_id]

        if describe is not None and not offer.get("description"):
            found = describe(offer)
            if found is None:
                continue                      # not possible now: waits for the next run
            if found is False:
                offer["relevancy_check"] = "not_relevant"
                offer["reason"] = "Offre retirée du site"
                continue

        stated = required_years(offer.get("description", ""))
        if stated is not None and stated > max_years:
            offer["relevancy_check"] = "not_relevant"
            offer["reason"] = f"{stated} ans d'expérience exigés"
            log.info(f"Skipped {offer_id} without Gemini: {stated} years of experience required.")
            continue

        wrong_time = temps_travail.mismatch(offer, work_time)
        if wrong_time:
            offer["relevancy_check"] = "not_relevant"
            offer["reason"] = wrong_time
            log.info(f"Skipped {offer_id} without Gemini: {wrong_time}.")
            continue

        batch.append(offer_id)
        if len(batch) >= max(1, batch_size):
            flush()
    flush()

    if save_func is not None:
        save_func(offers)
    return relevant
