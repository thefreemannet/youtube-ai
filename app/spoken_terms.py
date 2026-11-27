"""Spell abbreviations the voice would misread.

XTTS reads VAV as one word. With this speaker that comes out like "baby".
Captions keep the written abbreviation. Only the text sent to the voice changes.
"""
import re

_VAV = re.compile(r"\bVAV(?:'s|s)?\b", re.IGNORECASE)

# These spellings stay in the captions. Spoken alone, this voice leaves Spanish
# and mixes in another language. The voice hears a Spanish pronunciation instead.
_SPANISH_SAY = (
    (re.compile(r"\bWi-?Fi\b", re.IGNORECASE), "güifi"),
    (re.compile(r"\bWPA3\b"), "doble uve pe a tres"),
    (re.compile(r"\bWPA2\b"), "doble uve pe a dos"),
    (re.compile(r"\bMFA\b"), "eme efe a"),
    (re.compile(r"\bBluetooth\b", re.IGNORECASE), "blutuz"),
    (re.compile(r"\bphishing\b", re.IGNORECASE), "fishin"),
    (re.compile(r"\bfirmware\b", re.IGNORECASE), "firmwer"),
    (re.compile(r"\brouters\b", re.IGNORECASE), "rúters"),
    (re.compile(r"\bUSB\b"), "u ese be"),
)


def spoken_narration(text, language="en"):
    spanish = str(language or "").strip().lower() == "es"

    def replace(match):
        plural = match.group(0).lower().endswith("s")
        if spanish:
            return "uves a uve" if plural else "uve a uve"
        return "vee ay vees" if plural else "vee ay vee"

    spoken = _VAV.sub(replace, text)
    if not spanish:
        return spoken
    for pattern, said in _SPANISH_SAY:
        spoken = pattern.sub(said, spoken)
    return spoken
