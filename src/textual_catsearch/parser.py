"""Parsing: a query string into a tree, against a schema. Total — it reports, never refuses.

::

    reacher kind:tv cast:"Alan Ritchson" year:2026
    "the odyssey" -tag:comedy is:upcoming
    (kind:tv OR kind:movie) -(tag:horror year:<2000)

A bare (or quoted) word is a term on the schema's bare field; everything else is
``field:value``. Terms are AND-ed, comma-separated values within one term are OR-ed, a leading
``-`` negates, ``OR`` alternates, brackets group, and ``field:none`` asks for rows with nothing
under that field.
"""

from __future__ import annotations

import enum
import re
import string
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from typing import Final

from textual_catsearch.lexer import QUOTE, WORD, Guarded, Token, lex
from textual_catsearch.query import MAX_GROUPS, NOTHING, OR_WORDS, Diagnostic, Fault, Query
from textual_catsearch.schema import Field, NumberField, Schema, unquoted
from textual_catsearch.tree import And, Expr, NumRange, Or, Term, neg

__all__ = ["parse", "reserved", "stepped"]


# --- parsing ------------------------------------------------------------------------------
def _parse_range(value: str, unit: Callable[[str], float | None] | None = None) -> NumRange | None:
    """``2026`` / ``2020..2026`` / ``>=2026`` / ``<2030`` -> a window, or None if unparseable.

    With ``unit`` (a number field's ``parse``), each number is read by it, so ``>5m`` or
    ``1G..2G`` work, and strict comparisons stay strict (real quantities have no "next one").
    """
    v = value.strip()
    read = _reader(unit)
    try:
        if (compared := _comparison(v, read, integral=unit is None)) is not None:
            return compared
        if ".." in v:
            lo, _, hi = v.partition("..")
            return NumRange(
                lo=read(lo) if lo.strip() else None,
                hi=read(hi) if hi.strip() else None,
            )
        n = read(v)
    except ValueError:
        return None
    return NumRange(lo=n, hi=n)


def _comparison(v: str, read: Callable[[str], float], *, integral: bool) -> NumRange | None:
    """``>=n``, ``<=n``, ``>n``, ``<n`` as a window; None if ``v`` is not a comparison."""
    for op, strict in ((">=", False), ("<=", False), (">", True), ("<", True)):
        if v.startswith(op):
            n = read(v[len(op) :])
            upper = op.startswith("<")
            if strict and integral:  # integers: > n is >= n + 1, the historical form
                return NumRange(hi=n - 1) if upper else NumRange(lo=n + 1)
            return NumRange(hi=n, hi_strict=strict) if upper else NumRange(lo=n, lo_strict=strict)
    return None


def _reader(unit: Callable[[str], float | None] | None) -> Callable[[str], float]:
    """``int``, or the field's unit parser with its None (unreadable) turned into ValueError."""
    if unit is None:
        return lambda text: int(text)

    def read(text: str) -> float:
        if (n := unit(text.strip())) is None:
            raise ValueError(text)
        return n

    return read


# A whole *value* wrapped in apostrophes, and nothing else: `author:'Ursula Le Guin'`.
# Anchored on a token boundary and requiring the closing quote to end the token, so it can
# only ever fire on the shell-shaped form it exists for.
_SINGLE_QUOTED_VALUE = re.compile(r"(?<!\S)([A-Za-z][\w.-]*):'([^'\"]*)'(?=\s|$)")


def _normalize_quotes(source: str) -> str:
    """Rewrite ``field:'value'`` to ``field:"value"`` before lexing.

    :func:`lex` deliberately gives ``'`` no special meaning — that is what keeps ``Don't Look
    Up`` from raising and ``cast:"Josh O'Connor"`` from being mangled — which leaves the
    shell-shaped ``author:'Le Guin'`` splitting across two tokens. Normalising the one
    unambiguous form beforehand fixes that without giving the lexer a second quote character:
    an apostrophe mid-word, or one opening a title like ``'71``, has no ``field:`` in front of
    it and is left exactly as typed.
    """
    return _SINGLE_QUOTED_VALUE.sub(r'\1:"\2"', source)


def parse[Row](source: str, schema: Schema[Row], *, empty_as_text: bool = False) -> Query[Row]:
    """Parse a query string. Never raises — malformed input degrades, it does not explode.

    ``empty_as_text`` changes exactly one judgement: what an empty value means. Filtering,
    ``kind:`` half-typed constrains nothing and is dropped. Where the string instead *names*
    something — a new entry being typed into an add box — dropping it would eat a word out of
    the name, so a thing actually called "Person: Someone" would come out as "Someone". With
    the flag set it degrades to literal text instead, the same answer an unknown field gets.
    """
    normalized = _normalize_quotes(source)
    items, stray = _items(lex(normalized))
    reader = _Reader(items, schema, empty_as_text=empty_as_text)
    expr = reader.group(closing=False)
    faults = [_narrowed(d, normalized) for d in (*stray, *reader.faults)]
    if normalized.count(QUOTE) % 2:
        faults.append(
            Diagnostic(Fault.UNCLOSED_QUOTE, QUOTE, normalized.rindex(QUOTE), len(normalized))
        )
    return Query(schema, expr, tuple(faults))


def _narrowed(d: Diagnostic, source: str) -> Diagnostic:
    """The diagnostic's span cut from its whole token down to the fragment it names.

    Faults are found per token, but ``nope`` is what is wrong in ``nope:1``, and the ``(`` in
    ``(year:soon`` is not part of ``year:soon``: a span is for pointing at the text, so it
    should hold exactly that. A surplus ``)`` is the last one in its token; reserved characters
    run from the first of them to the last. Where the fragment is not a run of the token (a
    value the lexer unquoted), the token stays the span.
    """
    if not d.text:  # `:x` has an empty key: the token is the only thing to point at
        return d
    if d.fault is Fault.RESERVED:  # a set of characters: from the first of them to the last
        value = source.find(":", d.start, d.end) + 1 or d.start  # in the value, not its key
        hits = [i for i in range(value, d.end) if source[i] in d.text]
        return replace(d, start=hits[0], end=hits[-1] + 1) if hits else d
    at = (
        source.rfind(d.text, d.start, d.end)
        if d.fault is Fault.STRAY_CLOSE
        else source.find(d.text, d.start, d.end)
    )
    return d if at < 0 else replace(d, start=at, end=at + len(d.text))


# --- the token stream ------------------------------------------------------------------------
class Sym(enum.StrEnum):
    """What one item in the stream is, once brackets and the operator are separated out."""

    CLAUSE = "clause"
    OPEN = "open"
    CLOSE = "close"
    OR = "or"


@dataclass(frozen=True, slots=True)
class Item:
    sym: Sym
    token: Token
    body: Guarded = Guarded()  # the clause, brackets peeled off
    # Set on the `(` of a negated group. A clause carries its own sign in `body` instead,
    # because `_read` has to split it off after the field name either way.
    negated: bool = False


def _opens(body: Guarded) -> tuple[tuple[bool, ...], Guarded, int]:
    """Every group a token opens — each flagged if a ``-`` opened it — the rest, and its closers.

    Two things are being told apart at once. A *group's* negation from a *clause's*:
    ``-(kind:tv year:2026)`` negates the group, while ``-kind:tv`` negates the clause and is
    read off the body by :func:`_read`. They look identical until you check whether a bracket
    opens behind the sign — and peeling brackets first finds nothing to peel, because the token
    starts with the dash.

    And one token from several groups. ``(-(a`` opens two, the inner one negated, so this
    walks rather than peeling once: a fuzzer found ``(-(()))`` — which `render` emits for a
    tree `parse` can build — coming back as a title search, because everything after the outer
    bracket was handed on as a single clause.
    """
    _, rest, closes = body.peel("", ")")
    flags: list[bool] = []
    while True:
        negated, signed = rest.sign()
        lead, inner, _ = (signed if negated else rest).peel("(", "")
        if not lead:
            # Nothing more opens here, so a sign that got this far belongs to the clause and
            # is left on `rest` for `_read` to find.
            return tuple(flags), rest, closes
        # Only the outermost of a run carries the sign: `-((a` is a negated group around one.
        flags.extend([negated, *[False] * (lead - 1)])
        rest = inner


def _items(tokens: Sequence[Token]) -> tuple[tuple[Item, ...], tuple[Diagnostic, ...]]:
    """Separate brackets and ``OR`` out of the whitespace tokens.

    Brackets are peeled here rather than lexed, and a closing one is only peeled while a group
    is actually open. That is what keeps ``title:(2021)`` a literal value while ``(kind:tv
    year:2026)`` is a group — the same characters, told apart by whether anything is waiting
    to be closed rather than by where they sit in the token.
    """
    out: list[Item] = []
    stray: list[Diagnostic] = []
    depth = 0
    for token in tokens:
        flags, body, closes = _opens(token.body)
        if depth + len(flags) > MAX_GROUPS:
            # Read the innermost surplus brackets as part of the value rather than refusing.
            # The outer ones are kept because they are the ones with something in them.
            keep = max(0, MAX_GROUPS - depth)
            body = Guarded((("(" * (len(flags) - keep), False), *body.runs))
            flags = flags[:keep]
            stray.append(Diagnostic(Fault.TOO_NESTED, "(", token.start, token.end))
        out.extend(Item(Sym.OPEN, token, negated=negated) for negated in flags)
        depth += len(flags)
        taken = min(closes, depth)
        if closes > taken:
            # More `)` than there are groups open. It stays part of the value — a title may
            # well end in a bracket — but it is worth saying, because far more often it is a
            # bracket the user meant to match one they never opened.
            stray.append(Diagnostic(Fault.STRAY_CLOSE, ")", token.start, token.end))
            body = body.then(")" * (closes - taken))
        if any(body.is_free(word) for word in OR_WORDS):
            out.append(Item(Sym.OR, token, body))
        elif body:
            out.append(Item(Sym.CLAUSE, token, body))
        out.extend(Item(Sym.CLOSE, token) for _ in range(taken))
        depth -= taken
    return tuple(out), tuple(stray)


# --- reading the stream ----------------------------------------------------------------------
class _Reader[Row]:
    """Recursive descent over :func:`_items`. Reports; never refuses.

    ``group -> or+``, ``or -> unary ("OR" unary)*``, ``unary -> "-"? (group | clause)``. Every
    recovery is a diagnostic and a sensible tree, because the string being parsed is whatever
    the user is halfway through typing.
    """

    def __init__(self, items: Sequence[Item], schema: Schema[Row], *, empty_as_text: bool) -> None:
        self.items = items
        self.schema = schema
        self.empty_as_text = empty_as_text
        self.pos = 0
        self.faults: list[Diagnostic] = []

    def _at(self, item: Item, fault: Fault, text: str) -> None:
        self.faults.append(Diagnostic(fault, text, item.token.start, item.token.end))

    def group(self, *, closing: bool, opened: Item | None = None) -> Expr:
        """A juxtaposition of alternatives, up to ``)`` or the end of the stream."""
        parts: list[Expr] = []
        while self.pos < len(self.items):
            item = self.items[self.pos]
            if item.sym is Sym.CLOSE:
                self.pos += 1
                if closing:
                    return And(_merged(parts, self.schema))
                # Unreachable while `_items` only emits a close for a group it saw open — but
                # `unary` does not consume a close, so skipping it here is what guarantees this
                # loop makes progress rather than spinning.
                continue
            if (part := self.alternatives()) is not None:
                parts.append(part)
        if closing:
            at = (opened.token.start, opened.token.end) if opened is not None else (0, 0)
            self.faults.append(Diagnostic(Fault.UNCLOSED_GROUP, "(", *at))
        return And(_merged(parts, self.schema))

    def alternatives(self) -> Expr | None:
        """One or more clauses joined by ``OR``."""
        first = self.unary()
        parts = [] if first is None else [first]
        while self.pos < len(self.items) and self.items[self.pos].sym is Sym.OR:
            marker = self.items[self.pos]
            self.pos += 1
            if (nxt := self.unary()) is not None:
                parts.append(nxt)
            else:
                self._at(marker, Fault.DANGLING_OR, marker.body.text)
        if not parts:
            return None
        return parts[0] if len(parts) == 1 else Or(tuple(parts))

    def unary(self) -> Expr | None:
        """A clause or a bracketed group, either optionally negated."""
        if self.pos >= len(self.items):
            return None
        item = self.items[self.pos]
        if item.sym is Sym.OR:
            # A leading `OR` has nothing to its left; say so and read it as the word it is.
            self._at(item, Fault.DANGLING_OR, item.body.text)
            self.pos += 1
            return None
        if item.sym is Sym.CLOSE:
            return None
        self.pos += 1
        if item.sym is Sym.OPEN:
            inner = self.group(closing=True, opened=item)
            return neg(inner) if item.negated else inner
        read = _read(item, self.schema, empty_as_text=self.empty_as_text)
        self.faults.extend(read.faults)
        return read.term


def _merged[Row](parts: Sequence[Expr], schema: Schema[Row]) -> tuple[Expr, ...]:
    """Fold repeated keys into one term, so a key written twice offers alternatives.

    ``kind:tv kind:movie`` used to AND, and a row has one kind — so it asked for a row that
    was two things at once and matched nothing, silently. GitHub's rule instead: **OR within a
    key, AND across keys**, which people already know and which makes ``,``, ``|`` and ``OR``
    three spellings of one thing rather than three semantics.

    Two exclusions, both because the alternative would be worse:

    * **Bare text.** ``reacher jack`` is two words that must both appear, which is what typing
      two words into a search bar means everywhere. Since the bare field is a field like any
      other, an explicit ``name:a name:b`` conjoins for the same reason.
    * **Negated terms.** ``-tag:a -tag:b`` means neither, and folding it to ``-tag:a,b`` would
      turn it into "not both".

    Folding here rather than at match time is what keeps :func:`render` writing the comma form
    back out, so the query the bar echoes is the query that ran.
    """
    at: dict[tuple[str, tuple[str, ...]], tuple[int, Term]] = {}
    out: list[Expr] = []
    for part in parts:
        if not isinstance(part, Term) or part.negated or part.field == schema.bare:
            out.append(part)
        elif (seen := at.get((part.field, part.via))) is None:
            at[(part.field, part.via)] = (len(out), part)
            out.append(part)
        else:
            index, first = seen
            at[(part.field, part.via)] = (index, grown := _widened(first, part, schema))
            out[index] = grown
    return tuple(out)


def _widened[Row](first: Term, extra: Term, schema: Schema[Row]) -> Term:
    """``first`` with ``extra``'s values as further alternatives, in the order they were typed.

    Read back through :func:`_typed_term` rather than assembled by hand, so the merged term is
    exactly the term that value list would have produced had it been written as one comma
    list. ``ranges`` is why that matters — it belongs to number fields only, and deriving it
    here would give a text field a numeric window whenever a value happened to read as one.
    """
    values = tuple(dict.fromkeys((*first.values, *extra.values)))
    absent = first.absent or extra.absent
    spec = schema.fields[first.field]  # `_merged` only sees fields `_read` recognised
    return _typed_term(spec, values, negated=first.negated, absent=absent, via=first.via)


@dataclass(frozen=True, slots=True)
class _Read:
    """What one clause came to: the term to keep, and anything worth reporting about it."""

    term: Term | None = None
    faults: tuple[Diagnostic, ...] = ()


def _noticed(token: Token, fault: Fault, text: str) -> tuple[Diagnostic, ...]:
    return (Diagnostic(fault, text, token.start, token.end),)


def _read[Row](item: Item, schema: Schema[Row], *, empty_as_text: bool) -> _Read:
    """One clause item, read as a term."""
    token = item.token
    negated, body = item.body.sign()
    head, sep, value = body.partition(":")

    via, spec = stepped(head, schema) if sep else ((), None)
    if spec is None:
        # No colon is a bare word. A colon in front of something unrecognised is a colonated
        # *title* ("Andor: Season 2") far more often than it is a typo'd field, so it degrades
        # to literal text rather than vanishing.
        found = () if not sep else _noticed(token, Fault.UNKNOWN_FIELD, head)
        return _Read(Term(schema.bare, (body.text,), negated=negated), found)
    return _named(token, spec, value, body.text, schema, empty_as_text, negated=negated, via=via)


def _named[Row](
    token: Token,
    spec: Field[Row],
    value: Guarded,
    body: str,
    schema: Schema[Row],
    empty_as_text: bool,
    *,
    negated: bool,
    via: tuple[str, ...],
) -> _Read:
    """A clause whose field was recognised — what its values came to, and what was lost."""
    pieces = tuple(piece for piece in (p.strip() for p in value.split(",")) if piece.text)
    if not pieces:
        # `kind:` mid-typing constrains nothing — unless the string names something, where
        # dropping it would eat a word out of the name. See :func:`parse`.
        kept = Term(schema.bare, (body,), negated=negated) if empty_as_text else None
        return _Read(kept, _noticed(token, Fault.EMPTY_VALUE, body))
    absent = any(_says_nothing(piece) for piece in pieces)
    kept_values = tuple(piece.text for piece in pieces if not _says_nothing(piece))
    term = _typed_term(spec, kept_values, negated=negated, absent=absent, via=via)
    return _Read(term, _noticed_about(token, spec, pieces, term, body))


def stepped[Row](head: str, schema: Schema[Row]) -> tuple[tuple[str, ...], Field[Row] | None]:
    """A key read as a path: the relations to follow, and the field to ask at the end.

    ``parent.year`` is one hop and then a question about years. Every segment but the last has
    to be a relation the schema declares — `.` is not a general accessor, and a path through
    something that is not an edge is not a path.

    All or nothing, and that is the "never hard-fail" rule rather than strictness: a key with a
    dot in it that does not resolve is far more likely to be a title someone typed than a path
    with a typo, so it degrades to text the way any unknown field does.
    """
    *walked, tail = head.split(".")
    hops = tuple(r.name for piece in walked if (r := schema.relation(piece)) is not None)
    spec = schema.field(tail)
    if spec is None or len(hops) != len(walked):
        return (), None
    return hops, spec


def _says_nothing(piece: Guarded) -> bool:
    """Is this the bare word :data:`NOTHING`, and therefore a question rather than a value?"""
    return piece.bare and piece.text.casefold() == NOTHING


def _noticed_about[Row](
    token: Token, spec: Field[Row], pieces: Sequence[Guarded], term: Term, body: str
) -> tuple[Diagnostic, ...]:
    """What was worth saying about a clause the parser could otherwise read.

    Both of these leave the clause standing — one reads the value as though it had been
    quoted, the other leaves it with nothing to match — so they are reported rather than
    raised, and more than one can be true of the same clause.
    """
    found: list[Diagnostic] = []
    if held := claimed(reserved("".join(piece.free_text() for piece in pieces), unquoted(spec))):
        found.append(Diagnostic(Fault.RESERVED, held, token.start, token.end))
    numbers = [piece for piece in pieces if not _says_nothing(piece)]
    if isinstance(spec, NumberField) and len(term.ranges) < len(numbers):
        found.append(Diagnostic(Fault.NOT_A_NUMBER, body, token.start, token.end))
    return tuple(found)


GRAMMAR_PUNCTUATION: Final[frozenset[str]] = frozenset(string.punctuation)


def claimed(characters: str) -> str:
    """Of the characters a value would be quoted for, the ones worth a warning unquoted.

    Only ASCII punctuation can be claimed: the grammar is written in it, and nothing else is
    ever going to be an operator. Letters, digits and marks of any script, emoji, and
    punctuation from outside ASCII (an em dash, a fullwidth colon) are text, so `cwd:проект`
    and `label:Ünïcode` are ordinary values, not warnings; `render` still quotes them, which
    costs nothing.
    """
    return "".join(c for c in characters if c in GRAMMAR_PUNCTUATION)


def reserved(text: str, extra: str) -> str:
    """The characters in ``text`` an unquoted value may not carry — deduped, as they appear.

    The value keeps its meaning: the clause is read as though the value had been quoted, and
    :func:`render` writes it back with the quotes, so anything that goes through the tree
    migrates itself. What this buys is that the character is *claimed* — announced as the
    grammar's before the grammar uses it, rather than silently meaning "a literal" right up to
    the release where it starts meaning something else.
    """
    allowed = WORD | set(extra)
    return "".join(dict.fromkeys(c for c in text if c not in allowed))


def _typed_term[Row](
    spec: Field[Row],
    values: tuple[str, ...],
    *,
    negated: bool,
    absent: bool = False,
    via: tuple[str, ...] = (),
) -> Term:
    """One recognised ``field:value`` clause.

    A number field whose value does not read as a number keeps its term, with no range to
    match against — so ``year:soon`` matches nothing and says why. Dropping it instead would
    mean a question about numbers with a non-number in it quietly widened the query: `kind:tv
    year:soon` would search every kind. The property suite asserts that adding a clause never
    adds a row for exactly this reason.
    """
    ranges: tuple[NumRange, ...] = ()
    if isinstance(spec, NumberField):
        ranges = tuple(_ranges(values, spec.parse))
    return Term(spec.name, values, ranges, negated, absent, via)


def _ranges(
    values: Iterable[str], unit: Callable[[str], float | None] | None = None
) -> Iterable[NumRange]:
    return (r for v in values if (r := _parse_range(v, unit)) is not None)
