"""How two strings are compared: one spelling per name, however it was typed."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Final

__all__ = ["fold", "word_prefixed"]

# Invisible by design: joiners, direction overrides, soft hyphens, the zero-width space, and
# the C0 controls. A name carrying one of these looks identical to one that does not, so
# letting it decide a match would mean a row the user can see and cannot find.
_INVISIBLE: Final[frozenset[str]] = frozenset({"Cf", "Cc", "Zl", "Zp"})


@lru_cache(maxsize=16384)
def fold(text: str) -> str:
    """The form two names are compared in — one spelling per name, however it was typed.

    Names reach a search box by being pasted, and the same name arrives spelled several ways.
    macOS hands out decomposed text where most web sources hand out composed, so ``Café`` and
    ``Café`` are different strings; a Japanese IME hands back a fullwidth spelling of a Latin
    word; German sources disagree about ``Straße`` and ``STRASSE``; a copied web title carries
    a zero-width space through the middle of it. Compared as typed, every one of those is a row
    the user can see on screen and cannot find by typing its name.

    So: drop what is invisible, decompose, drop the combining marks, recompose, and casefold.
    Losing the marks also makes ``cafe`` find ``Café``, which is what someone typing quickly on
    a keyboard without the accent wants — and it is what makes ``İstanbul`` findable, since
    casefolding alone turns the Turkish dotted capital into an ``i`` with a mark still on it.

    Deliberately *not* folded: scripts. A Cyrillic capital A and a Latin one look identical and
    stay different, because collapsing them would silently answer a question about one
    alphabet with a row from another.

    Cached because a snapshot's names repeat heavily, and the same haystack is folded on every
    keystroke.
    """
    visible = "".join(c for c in text if unicodedata.category(c) not in _INVISIBLE)
    loose = unicodedata.normalize("NFKD", visible)
    bare = "".join(c for c in loose if not unicodedata.combining(c))
    return unicodedata.normalize("NFC", bare).casefold()


# Unicode-aware on purpose: `[^0-9a-z]` treated every Cyrillic, Greek and CJK name as one
# unbroken word, so `cast:пе` could only ever complete a name that *began* that way.
_WORDS = re.compile(r"[\W_]+")


def word_prefixed(value: str, needle: str) -> bool:
    """Does ``value`` begin with ``needle``, at the start of the value or of one of its words?

    ``needle`` is expected folded already. Prefix rather than substring, so that typing narrows
    monotonically: ``is:a`` offers *aging* and *available* but not *dated*, which the typed
    ``a`` has already ruled out as far as the reader is concerned. Word starts still count,
    because a name is looked up by whichever part of it comes to mind — ``cast:rit`` must find
    *Alan Ritchson*.
    """
    low = fold(value)
    return low.startswith(needle) or any(w.startswith(needle) for w in _WORDS.split(low) if w)
