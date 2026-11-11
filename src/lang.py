"""Tiny French/English guess for an offer's text (no dependency)."""
import re

_FR = set("le la les des du de un une et est pour avec dans sur vous nous votre vos au aux en par qui que sera "
          "poste mission profil entreprise équipe expérience compétences missions".split())
_EN = set("the and of to a in for with you your we our is are will be on as an this team role experience "
          "skills job position responsibilities requirements".split())


def guess_lang(text):
    """'fr' or 'en' (French when unsure)."""
    words = re.findall(r"[a-zàâçéèêëîïôûùüÿœ]+", (text or "").lower())
    fr = sum(w in _FR for w in words)
    en = sum(w in _EN for w in words)
    return "en" if en > fr * 1.2 else "fr"


class _VieCv(dict):
    """CV advised for a VIE offer, by language (set in cdi_search.yaml, candidat.cv_vie)."""
    def __getitem__(self, lang):
        from .candidat import vie_cv
        return vie_cv(lang)


VIE_CV = _VieCv()
