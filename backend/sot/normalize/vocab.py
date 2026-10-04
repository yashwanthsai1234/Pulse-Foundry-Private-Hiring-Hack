"""Controlled-vocabulary normalization (IMPLEMENTATION §10.3).

Lower-case, strip punctuation, collapse spaces (`clean`, shared with the mapper and the contracts); exact alias
match, else rapidfuzz `ratio` >= 90. token_set_ratio scored 100 for any token subset ("Nurse" -> RN,
"Riverdale/Bayside" -> Bayside), `ratio` (normalized Indel) does not; one-character values never fuzzy-match.

Sources:
- https://rapidfuzz.github.io/RapidFuzz/Usage/fuzz.html (token_set_ratio is 100 for a subset; ratio = normalized Indel)
- https://rapidfuzz.github.io/RapidFuzz/Usage/process.html (extractOne)
"""
from __future__ import annotations

import re
from collections.abc import Callable

from rapidfuzz import fuzz, process

from sot.core.pack import Vocab

FUZZY_MIN = 90


def clean(text: str) -> str:
    """Lower-case words (Unicode letters and digits kept), everything else is one space."""
    return re.sub(r"[\W_]+", " ", text.lower()).strip()


def vocab_matcher(vocab: Vocab) -> Callable[[str], tuple[str | None, bool]]:
    """Build the alias index once; the returned function is normalize_vocab bound to `vocab`."""
    index = {clean(a): code for code, aliases in vocab.codes.items() for a in aliases}

    def match(value: str) -> tuple[str | None, bool]:
        key = clean(value)
        if key in index:
            return index[key], False
        if len(key) < 2:
            return None, False
        hit = process.extractOne(key, list(index), scorer=fuzz.ratio, score_cutoff=FUZZY_MIN)
        return (index[hit[0]], True) if hit else (None, False)

    return match


def normalize_vocab(value: str, vocab: Vocab) -> tuple[str | None, bool]:
    """(code, fuzzy). fuzzy=True means the match was approximate (caller adds vocab_fuzzy:<field>)."""
    return vocab_matcher(vocab)(value)
