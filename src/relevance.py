from .gemini_handler import AllModelsExhausted
from . import feedback
import json
import logging
import re
import time

import requests

log = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MAX_RETRIES = 5
GEMINI_WAIT = 4
SAVE_EVERY = 10

def offer_text(offer):
    parts = [
        offer.get("missionTitle"),
        offer.get("missionDescription"),
        offer.get("missionProfile"),
        offer.get("organizationName"),
    ]
    return "\n".join(p for p in parts if p)


def is_relevant(offer, handler, config_dict):
    """Returns (relevant, score out of 10 or None, short reason)."""
    profile = config_dict["USER_PROFILE"]
    text = offer_text(offer)

    prompt = (
        "You decide if a job offer matches a candidate's profile.\n"
        "Give a match score out of 10: 9-10 = excellent fit with real chances, 7-8 = good lead, "
        "5-6 = possible but not ideal, 0-4 = not a match (then relevant = false).\n"
        "Answer ONLY with a one-line JSON object, no text around it:\n"
        '{"relevant": true|false, "score": <0-10>, "reason": "<one short sentence in French explaining the score>"}\n\n'
        "Candidate profile:\n" + profile + "\n\n"
        + feedback.prompt_block(lang="en") +
        "Job offer:\n" + text + "\n\n"
        "Does this offer match the profile?"
    )

    answer = (handler.generate(prompt) or "").strip()
    m = re.search(r"\{.*\}", answer, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            relevant = data.get("relevant")
            if isinstance(relevant, str):
                relevant = relevant.strip().lower() in ("true", "yes", "oui")
            try:
                score = max(0, min(10, round(float(data.get("score")))))
            except (TypeError, ValueError):
                score = None
            if score is not None and score < 5:
                relevant = False
            return bool(relevant), score, str(data.get("reason") or "").strip()
        except json.JSONDecodeError:
            pass
    return answer.upper().startswith("YES"), None, ""


def filter_relevant(offers, config_dict, handler, save_func=None):
    relevant = {}
    items = list(offers.items())
    total = len(items)
    checked_since_save = 0

    for i, (offer_id, offer) in enumerate(items):
        if offer.get("relevancy_check") != "unchecked":
            continue

        try:
            match, score, reason = is_relevant(offer, handler, config_dict)
        except AllModelsExhausted:
            log.error("RELEVANCE ERROR - all Gemini models exhausted; stopping run.")
            break
        except Exception as e:
            log.error(f"RELEVANCE ERROR - offer {offer_id}: {e}")
            continue

        offer["score"] = score
        offer["reason"] = reason
        if match:
            offer["relevancy_check"] = "relevant"
            relevant[offer_id] = offer
        else:
            offer["relevancy_check"] = "not_relevant"

        log.info(f"Checked offer {i + 1}/{total} ({offer_id}): {offer['relevancy_check']}")

        checked_since_save += 1
        if save_func is not None and checked_since_save >= SAVE_EVERY:
            save_func(offers)
            checked_since_save = 0

    if save_func is not None:
        save_func(offers)

    return relevant