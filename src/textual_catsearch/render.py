"""Rendering: a tree written back out in the language it was parsed from."""

from __future__ import annotations

from typing import Final

from textual_catsearch.lexer import QUOTE
from textual_catsearch.parser import parse, reserved
from textual_catsearch.query import NOTHING, OR_WORDS
from textual_catsearch.schema import Schema, unquoted
from textual_catsearch.tree import And, Expr, Not, Or, Term

__all__ = ["quote", "render"]

_SEPARATORS: Final[frozenset[str]] = frozenset(",:()")


def quote(value: str, extra: str = "") -> str:
    """Wrap a *field value* in quotes unless it is spelled in the language's own alphabet.

    Public because anything composing a query out of data — a title, a person's name — needs
    the one answer to "does this need quoting", not its own guess at it.

    The alphabet is :data:`lexer.WORD` plus whatever operators the field declares
    (:func:`schema.unquoted`), and everything else is quoted. Deliberately more than today's
    grammar needs: an unquoted value that may hold any punctuation is one the grammar can never
    claim a character back from, because every string already saved means something. So the
    punctuation is claimed now, while the only cost of claiming it is a pair of quotes.
    """
    return _wrapped(value) if not value or _plainly(value, extra) is None else value


def _plainly(value: str, extra: str) -> str | None:
    """``value`` if it can be written bare, else ``None`` — the reserved characters say why."""
    if (
        value in OR_WORDS
        or value.casefold() == NOTHING  # else `tag:"none"` would come back as a question
        or value[:1] in ("-", "!")
        or reserved(value, extra)
    ):
        # A leading `-` or `!` negates when the value starts a token, so a thing called `-30-`
        # has to be quoted to be searched *for* rather than searched against.
        return None
    return value


def _loose(value: str) -> str:
    """A *bare* word, quoted only where writing it bare would not read back as one word.

    Free text is level zero of the language and stays there. A bare word has no field in front
    of it, so there is no slot for punctuation to mean anything in — `Mr. Robot`, `Wall-E` and
    `#Alive` are names, and making them ask for quotes would be a tax on the commonest thing
    anyone types. The stricter alphabet is for values, where a character *does* have a slot.
    """
    unsafe = (
        value in OR_WORDS
        or value[:1] in ("-", "!")
        or any(c.isspace() or c in _SEPARATORS or c == QUOTE for c in value)
    )
    return _wrapped(value) if unsafe else value


def _wrapped(value: str) -> str:
    """In quotes, with any quote of its own doubled — the one escape the language has."""
    return f"{QUOTE}{value.replace(QUOTE, QUOTE * 2)}{QUOTE}"


def render[Row](expr: Expr, schema: Schema[Row]) -> str:
    """An expression, written back out in the language it was parsed from.

    The inverse of :func:`parse`, and the reason a query can be *transformed* rather than
    string-edited: pinning a category tab, or carrying part of one query into another, is a
    change to the tree followed by one call here. Pasting strings together instead is how a
    value containing a comma fails to survive the trip.

    ``parse(render(e)) == e`` for every expression :func:`parse` can produce — asserted as a
    property test rather than by example, because that is the claim the whole seam rests on.
    """
    return _Renderer(schema).render(expr, _LOOSEST)


# How tightly each node binds, so a child is bracketed exactly when leaving it bare would read
# as something else. `OR` binds tighter than juxtaposition (see :class:`Or`), so an alternation
# inside a conjunction needs no brackets — but a conjunction inside one does.
_LOOSEST, _CONJUNCTION, _ALTERNATION, _ATOM = 0, 1, 2, 3


class _Renderer[Row]:
    def __init__(self, schema: Schema[Row]) -> None:
        self.schema = schema

    def render(self, expr: Expr, floor: int) -> str:
        text, binds = self._written(expr)
        if not text:
            # An empty group is only worth writing where dropping it would change the shape —
            # `a OR ()` must not come back as a bare `a` with a dangling operator.
            return "()" if floor > _LOOSEST else ""
        return f"({text})" if binds < floor else text

    def _written(self, expr: Expr) -> tuple[str, int]:
        """An expression as text, and how tightly the result binds."""
        match expr:
            case Term():
                return self._term(expr), _ATOM
            case Not(inner=inner):
                return f"-({self.render(inner, _LOOSEST)})", _ATOM
            case Or(parts=parts):
                return " OR ".join(self.render(p, _ATOM) for p in parts), _ALTERNATION
            case And(parts=parts):
                written = (self.render(p, _ALTERNATION) for p in parts)
                return " ".join(r for r in written if r), _CONJUNCTION

    def _term(self, term: Term) -> str:
        sign = "-" if term.negated else ""
        spec = self.schema.fields.get(term.field)
        extra = "" if spec is None else unquoted(spec)
        # `none` leads, so `tag:horror,none` and `tag:none,horror` write back as one spelling —
        # the flag is a property of the clause and does not sit anywhere among the values.
        body = ",".join(
            (*((NOTHING,) if term.absent else ()), *(quote(v, extra) for v in term.values))
        )
        # A path always writes its key out, the bare field included: the bare form has no room
        # for one, and `parent.name:x` written bare would come back asking about this row.
        if term.via or term.field != self.schema.bare:
            return f"{sign}{'.'.join((*term.via, term.field))}:{body}"
        bare = f"{sign}{','.join(_loose(v) for v in term.values)}"
        return bare if self._reads_back(bare, term) else f"{sign}{term.field}:{body}"

    def _reads_back(self, bare: str, term: Term) -> bool:
        """Would this clause, written without its field name, come back as the same clause?

        Usually yes — that is what makes a query readable. But the bare form is the one place
        in the language where the text is unguarded, so a value that happens to look like
        syntax reads as syntax: ``name:a,b`` written bare comes back as one value rather than
        two, and ``name:kind:tv`` comes back as a kind filter. Rather than enumerate the ways
        that can happen and miss one, the renderer reads its own output back and keeps the
        field name when the answer differs.
        """
        return parse(bare, self.schema).expr == And((term,))
