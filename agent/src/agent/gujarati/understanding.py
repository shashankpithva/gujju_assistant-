"""Word-level helpers for reading Gujarati the way speech-to-text writes it.

Speech-to-text writes code-mixed speech with English words in English ("પાણી daily આવે છે"), and
sometimes in Gujarati script ("ડેઇલી"). Everything that reads a caller's words splits them with
`words`, never with `\\b` or `\\w` (see gujarati/__init__.py for why).
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[^\s,.!?।;:\"'()\-–—…]+")


def words(text: str) -> list[str]:
    """Split on spaces and punctuation, keeping vowel signs and the virama inside their word."""
    return _WORD.findall(text.lower().replace("’", "'"))


def has_gujarati(text: str) -> bool:
    return any("઀" <= ch <= "૿" for ch in text)
