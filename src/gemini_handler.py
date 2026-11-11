import time
import logging
 
import requests
 
log = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MAX_RETRIES = 5
GEMINI_WAIT = 4
GEMINI_MINUTE_WAIT = 61
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}

class AllModelsExhausted(Exception):
    pass


class Gemini_Model:

    def __init__(self, name):
        self.name = name
        self.rpd_exhausted = False


class GeminiHandler: 
    def __init__(self, api_key, models):
        self.api_key = api_key
        self.models = [
            Gemini_Model(m["name"]) for m in models
        ]
 
    def _pick_available(self):
        for model in self.models:
            if not model.rpd_exhausted:
                return model
        return None

    def generate(self, prompt):
        while True:

            model = self._pick_available()

            if model is None:
                raise AllModelsExhausted()

            for attempt in range(GEMINI_MAX_RETRIES + 1):
                try:
                    answer = self._call(model, prompt)
                    return answer
                except requests.exceptions.HTTPError as e:
                    status = e.response.status_code if e.response is not None else None
                    if status not in TRANSIENT_STATUSES:
                        raise

                    wait = GEMINI_WAIT
                    if attempt < GEMINI_MAX_RETRIES - 1:
                        log.warning(
                            f"RELEVANCE WARNING - Gemini rate limit hit, waiting {GEMINI_WAIT}s (retry {attempt + 1}/{GEMINI_MAX_RETRIES})...")
                    elif attempt == GEMINI_MAX_RETRIES -1:
                        wait = GEMINI_MINUTE_WAIT
                        log.warning(
                            f"RELEVANCE WARNING - Waiting {wait}s before trying one last time with model {model.name}")
                        
                    elif attempt == GEMINI_MAX_RETRIES:
                        log.warning(f"RELEVANCE WARNING - RPD limit reached for {model.name}")
                        model.rpd_exhausted = True
                        wait = 0.5

                    time.sleep(wait)

                    continue
 
    def _call(self, model, prompt):
        url = GEMINI_URL.format(model=model.name)
        r = requests.post(
            url,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=30,
        )
        r.raise_for_status()
        return answer_text(r.json())


def answer_text(data):
    """Whole answer: Gemini can split it over several parts (and add thought parts)."""
    cand = (data.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    reason = cand.get("finishReason")
    if reason and reason not in ("STOP", "MAX_TOKENS"):
        log.warning(f"Gemini stopped early ({reason}), answer may be incomplete.")
    return text