"""A parsed query, what the parser noticed about it, and running it against rows."""

from __future__ import annotations

import enum
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from textual_catsearch.evaluate import holds
from textual_catsearch.schema import Schema
from textual_catsearch.tree import And, Expr, Term

__all__ = [
    "MAX_GROUPS",
    "NOTHING",
    "OR_WORDS",
    "WORDING",
    "Diagnostic",
    "Fault",
    "Query",
    "notice_of",
]

# How many things a status line says at once before it says "and more" (see `Query.notice`).
_MAX_NOTICES: Final[int] = 2

# How deep groups may nest. `parse` recurses a level per group, so without a ceiling a bar
# full of brackets is a `RecursionError` — and totality is the one thing the language actually
# promises. Far past any query anyone writes: past it the brackets are read as text.
MAX_GROUPS: Final[int] = 32

OR_WORDS: Final[frozenset[str]] = frozenset({"OR", "|"})

# `tag:none` asks which rows carry no tags at all — a question the language could not put,
# because an empty value set and a value nobody asked about looked the same from outside.
# Unquoted and case-insensitively, like a field name and unlike `OR`: a value is typed in
# lower case far more often than an operator is, so `tag:NONE` meaning a literal would be a
# trap rather than a rule. `tag:"none"` is the tag.
NOTHING: Final[str] = "none"


class Fault(enum.StrEnum):
    """What a parse noticed but did not refuse. The language never rejects; it reports."""

    UNKNOWN_FIELD = "unknown-field"  # read as text instead — `Andor: Season 2` is a title
    EMPTY_VALUE = "empty-value"  # `kind:` mid-typing constrains nothing
    NOT_A_NUMBER = "not-a-number"  # `year:soon` — a number question with no number in it
    RESERVED = "reserved"  # `cast:O.Connor` — punctuation the grammar keeps; quote it
    UNCLOSED_QUOTE = "unclosed-quote"  # normal while typing, worth saying once at the end
    UNCLOSED_GROUP = "unclosed-group"  # `(kind:tv` — closed at the end rather than refused
    STRAY_CLOSE = "stray-close"  # a `)` with nothing open; ignored
    TOO_NESTED = "too-nested"  # more groups than anyone means; the rest read as text
    DANGLING_OR = "dangling-or"  # `kind:tv OR` — nothing to be an alternative to


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """Something the parser noticed, and where in the source it was.

    A total parser cannot report by raising, and dropping a clause silently is how ``year:soon``
    came to widen a query instead of narrowing it. So the clause still degrades, and the reason
    it degraded is carried alongside the tree rather than thrown away.
    """

    fault: Fault
    text: str  # the offending fragment, as typed
    start: int  # inclusive offset into the source
    end: int  # exclusive

    def render(self) -> str:
        return WORDING[self.fault].format(text=self.text)


def notice_of(diagnostics: Iterable[Diagnostic]) -> str:
    """The status-line summary of some diagnostics: distinct wordings, the first two, a count."""
    found = tuple(dict.fromkeys(d.render() for d in diagnostics))
    if not found:
        return ""
    shown = " · ".join(found[:_MAX_NOTICES])
    return shown if len(found) <= _MAX_NOTICES else f"{shown} · +{len(found) - _MAX_NOTICES}"


# One wording per fault, as a table rather than a `match`. The cost is that a fault added
# without an entry raises `KeyError` where it is displayed instead of failing to type-check,
# so the test suite sweeps the enum.
WORDING: dict[Fault, str] = {
    Fault.UNKNOWN_FIELD: "{text}: not a field — searched as text",
    Fault.EMPTY_VALUE: "{text}: nothing to match on",
    Fault.NOT_A_NUMBER: "{text}: not a number",
    Fault.RESERVED: "{text} in a value has to be quoted",
    Fault.UNCLOSED_QUOTE: "unclosed quote",
    Fault.UNCLOSED_GROUP: "unclosed ( — closed for you at the end",
    Fault.STRAY_CLOSE: "stray ) — ignored",
    Fault.DANGLING_OR: "{text} with nothing after it",
    Fault.TOO_NESTED: f"more than {MAX_GROUPS} nested groups — the rest read as text",
}


@dataclass(frozen=True, slots=True)
class Query[Row]:
    """A parsed query, and the schema it was parsed against — enough to run it."""

    schema: Schema[Row] = field(compare=False, repr=False)
    expr: Expr = And(())
    diagnostics: tuple[Diagnostic, ...] = ()

    def matches(self, row: Row) -> bool:
        """Does this query hold for this row? An empty query matches everything."""
        return holds(self.expr, row, self.schema)

    def filter(self, rows: Iterable[Row]) -> list[Row]:
        """The rows this query keeps, in the order they came. Cheap enough per keystroke."""
        return [r for r in rows if holds(self.expr, r, self.schema)]

    @property
    def terms(self) -> tuple[Term, ...]:
        """The clauses in the query's **conjunctive core** — its top-level ``And``.

        Anything that reads a query for an *intent* rather than as a predicate reads this. A
        clause under a disjunction states no intent — "``kind:tv`` or ``kind:movie``" pins no
        kind — so it is deliberately not here.
        """
        return (
            ()
            if not isinstance(self.expr, And)
            else tuple(p for p in self.expr.parts if isinstance(p, Term))
        )

    def first(self, field: str) -> Term | None:
        """The first positive clause in the core asking about this field *here*.

        ``field`` is a canonical name; a clause reached through a relation asks about another
        row, so it never counts.
        """
        return next(
            (t for t in self.terms if t.field == field and not t.negated and not t.via), None
        )

    @property
    def unknown_fields(self) -> tuple[str, ...]:
        """The field names the parser did not recognise, in the order they were typed."""
        return tuple(
            dict.fromkeys(d.text for d in self.diagnostics if d.fault is Fault.UNKNOWN_FIELD)
        )

    @property
    def notice(self) -> str:
        """One line saying what the parser noticed, or empty when it noticed nothing.

        Capped because its destination is a status line. Two is enough to tell you the query is
        not doing what you think, and the rest are usually the same slip repeated.
        """
        return notice_of(self.diagnostics)

    @property
    def is_empty(self) -> bool:
        return self.expr == And(())

    @property
    def text(self) -> str:
        """The bare words, joined — the free-text part of the query."""
        bare = self.schema.bare
        return " ".join(v for t in self.terms if t.field == bare and not t.via for v in t.values)
