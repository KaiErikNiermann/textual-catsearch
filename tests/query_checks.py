"""The claims the query language makes about *any* string, in one place.

Imported by the property tests and usable from a fuzzer, so the two can never check subtly
different things. Raises rather than asserts, and says what it saw: a fuzzer's whole output is
the message on the crash it found.
"""

from __future__ import annotations

from catalog import SCHEMA
from textual_catsearch import Vocabulary, parse, render, suggest

__all__ = ["check"]


def check(source: str) -> None:
    """Everything that must hold for an arbitrary string. Raises on the first that does not."""
    parsed = parse(source, SCHEMA)
    parse(source, SCHEMA, empty_as_text=True)  # the naming reading must be total too

    # Writing a query back out and reading it again is the identity. It is what lets a query
    # be transformed rather than string-edited.
    once = render(parsed.expr, SCHEMA)
    reparsed = parse(once, SCHEMA)
    if reparsed.expr != parsed.expr:
        raise AssertionError(
            f"render is not the inverse of parse:\n  in   {source!r}\n"
            f"  out  {once!r}\n  back {render(reparsed.expr, SCHEMA)!r}"
        )
    if (twice := render(reparsed.expr, SCHEMA)) != once:
        raise AssertionError(
            f"rendering is not a fixed point:\n  {source!r}\n  -> {once!r}\n  -> {twice!r}"
        )

    # The bar completes on every keystroke, at whatever offset the caret happens to be.
    for cursor in (0, len(source) // 2, len(source)):
        suggest(source, cursor, SCHEMA, Vocabulary())
