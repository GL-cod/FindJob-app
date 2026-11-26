"""Check that judging by batches gives the same verdicts as judging one offer at a time.

Takes N offers already judged (Île-de-France first, the sites in turn), downloads their
description, judges them again one by one and by batches, and prints how often the two agree.
Nothing is saved. Run by the « Contrôle du tri par lots » workflow (GitHub Actions, manual).
"""
import copy
import os
import sys

from . import cdi_main, feedback, temps_travail
from .cdi_relevance import (
    batch_relevance_prompt, in_priority_places, parse_batch, parse_score, parse_verdict, relevance_prompt,
)
from .gemini_handler import GeminiHandler


def main(n=30, batch_size=10):
    settings = cdi_main.load_settings()
    env = cdi_main.load_env()
    places = settings.get("priorite_lieux") or []
    store = cdi_main.load_offers(cdi_main.STORE_PATH)
    judged = [o for o in store.values() if o.get("relevancy_check") in ("relevant", "not_relevant")
              and o.get("reason") not in ("Offre retirée du site",) and "ans d'expérience" not in (o.get("reason") or "")]
    # half retained, half rejected (else the sample is almost only rejections), Île-de-France first
    judged.sort(key=lambda o: (in_priority_places(o.get("location"), places), o.get("posted") or ""), reverse=True)
    kept = [o for o in judged if o["relevancy_check"] == "relevant"]
    rejected = [o for o in judged if o["relevancy_check"] != "relevant"]
    judged = [o for pair in zip(kept, rejected) for o in pair] + kept[len(rejected):] + rejected[len(kept):]
    sample = []
    describe = cdi_main.describer(cdi_main.new_session())
    for o in judged:
        o = copy.deepcopy(o)
        if not o.get("description") and describe(o) is not True:
            continue
        sample.append(o)
        if len(sample) >= n:
            break

    handler = GeminiHandler(env["GEMINI_API_KEY"], [{"name": m} for m in settings["gemini_models"]])
    rules = (settings.get("max_experience_years", 3), settings.get("excluded_domains") or [],
             feedback.prompt_block(lang="fr"), temps_travail.value(settings))
    alone = []
    for o in sample:
        a = handler.generate(relevance_prompt(o, env["USER_PROFILE"], *rules))
        alone.append((*parse_verdict(a), parse_score(a)))
    grouped = {}
    for start in range(0, len(sample), batch_size):
        chunk = [(f"O{i + 1}", o) for i, o in enumerate(sample[start:start + batch_size])]
        verdicts = parse_batch(handler.generate(batch_relevance_prompt(chunk, env["USER_PROFILE"], *rules)))
        for i, (label, _) in enumerate(chunk):
            grouped[start + i] = verdicts.get(label)

    same = missing = 0
    gaps = []
    print(f"{'offre':55} | seule      | par lot")
    for i, o in enumerate(sample):
        a, b = alone[i], grouped.get(i)
        if b is None:
            missing += 1
            print(f"{o['title'][:55]:55} | {'oui' if a[0] else 'non'} {a[4]}/10 | (absente)")
            continue
        same += a[0] == b[0]
        if a[4] is not None and b[4] is not None:
            gaps.append(abs(a[4] - b[4]))
        mark = "" if a[0] == b[0] else "   <-- différent"
        print(f"{o['title'][:55]:55} | {'oui' if a[0] else 'non'} {a[4]}/10 | {'oui' if b[0] else 'non'} {b[4]}/10{mark}")
    total = len(sample) - missing
    gap = f"{sum(gaps) / len(gaps):.1f}" if gaps else "-"
    print(f"\nMême verdict (retenue ou non) : {same}/{total} ; absentes de la réponse groupée : {missing} ; "
          f"écart moyen de note : {gap} point(s)")
    return same, total


if __name__ == "__main__":
    main(int(os.environ.get("CONTROLE_N", sys.argv[1] if len(sys.argv) > 1 else 30)))
