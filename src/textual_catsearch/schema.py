"""The field vocabulary a query language is built from — declared once, read by everything.

A search box built on this library knows nothing about your data until you describe it. You
describe it as a :class:`Schema`: a list of fields, each saying what it is called, how its
values are read off a row, and how they compare. Parsing, matching, rendering and completion
all read that one declaration, so a field cannot be matchable but uncompletable, or
completable but silently match every row — the two ways a hand-maintained vocabulary drifts.

Each kind of field is its own class rather than one class with a ``domain`` switch and
accessors that only some domains may set. Matching dispatches on the class, exhaustively, so a
new kind cannot arrive without a way to match it::

    schema = Schema(
        [
            TextField("title", lambda b: b.title, aliases=("name",), complete=False),
            TextField("author", lambda b: b.authors),
            EnumField("format", lambda b: b.format, choices=("hardcover", "ebook")),
            NumberField("year", lambda b: b.year),
            FlagField("is", {"read": lambda b: b.read, "owned": lambda b: b.owned}),
        ],
        bare="title",
    )

Pure: no I/O, no terminal. The accessors are the only thing that knows what a row looks like.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Final

from textual_catsearch.text import fold

__all__ = [
    "Completions",
    "CustomField",
    "EnumField",
    "Field",
    "FlagField",
    "NumberField",
    "Numbers",
    "Relation",
    "Schema",
    "Strings",
    "TextField",
    "Unit",
    "VocabEntry",
    "Vocabulary",
    "detail_of",
    "numbers_of",
    "strings_of",
    "unquoted",
]

type Strings = str | Iterable[str] | None
"""What a string accessor may hand back: one value, several, or nothing."""

type Numbers = float | Iterable[float] | None
"""What a numeric accessor may hand back: one value, several, or nothing."""

type Unit = Callable[[str], float | tuple[float, float] | None]
"""A number field's reader for values with units: a number, a half-open span, or None."""


def strings_of(value: Strings) -> tuple[str, ...]:
    """An accessor's answer as a tuple of non-empty strings.

    A lone ``str`` is one value, not an iterable of characters — ``lambda b: b.title`` is the
    commonest accessor anyone writes, and iterating it would match every title containing an
    ``e`` against ``title:e``.
    """
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value else ()
    return tuple(v for v in value if v)


def numbers_of(value: Numbers) -> tuple[float, ...]:
    """An accessor's answer as a tuple of numbers."""
    if value is None:
        return ()
    if isinstance(value, int | float):
        return (value,)
    return tuple(value)


# --- completion vocabulary ------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class VocabEntry:
    """One completable value, with how many rows use it (drives ranking)."""

    value: str
    uses: int = 0


type Completions = tuple[tuple[VocabEntry, str], ...]
"""``(value, detail)`` pairs a field completes to."""


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """Completable values per field, keyed by canonical field name.

    Usually built by :meth:`Schema.vocabulary` from the rows being searched, so the values on
    offer are the values that can actually match. Built by hand where a field's values come
    from somewhere else — a :class:`CustomField`, or a list too expensive to derive per row.
    """

    entries: Mapping[str, tuple[VocabEntry, ...]] = dc_field(
        default_factory=dict[str, tuple[VocabEntry, ...]]
    )

    def of(self, field: str) -> tuple[VocabEntry, ...]:
        return self.entries.get(field, ())

    def merged(self, other: Vocabulary) -> Vocabulary:
        """Both vocabularies; where both name a field, ``other``'s entries follow this one's."""
        keys = dict.fromkeys((*self.entries, *other.entries))
        return Vocabulary({k: _distinct((*self.of(k), *other.of(k))) for k in keys})


def _distinct(entries: Iterable[VocabEntry]) -> tuple[VocabEntry, ...]:
    """One entry per folded spelling — the first one wins."""
    seen: dict[str, VocabEntry] = {}
    for entry in entries:
        seen.setdefault(fold(entry.value), entry)
    return tuple(seen.values())


def _tally(per_row: Iterable[tuple[str, ...]]) -> tuple[VocabEntry, ...]:
    """One entry per folded value, counted once per row that carries it, most used first."""
    uses: Counter[str] = Counter()
    spelling: dict[str, str] = {}
    for values in per_row:
        folded = {fold(v): v for v in values}
        uses.update(folded.keys())
        for key, value in folded.items():
            spelling.setdefault(key, value)
    ranked = sorted(uses.items(), key=lambda kv: (-kv[1], kv[0]))
    return tuple(VocabEntry(spelling[key], n) for key, n in ranked)


# --- fields ---------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class TextField[Row]:
    """Case- and accent-insensitive *substring* match against the strings ``get`` returns.

    ``complete`` offers the values seen on rows as completions. Turn it off for a field whose
    values are too open to be worth listing — a free-text title, a description.
    """

    name: str
    get: Callable[[Row], Strings]
    aliases: tuple[str, ...] = ()
    detail: str = ""  # what completion calls this field's values; defaults to the name
    choices: tuple[str, ...] = ()  # offered as completions whether or not a row uses them
    complete: bool = True


@dataclass(frozen=True, slots=True)
class EnumField[Row]:
    """Case- and accent-insensitive *equality* against the strings ``get`` returns.

    ``normalize`` is applied to the *query's* values before comparing, which is where synonyms
    live: a ``kind`` field whose rows say ``movie`` can accept ``film`` with a normaliser that
    maps one to the other.
    """

    name: str
    get: Callable[[Row], Strings]
    aliases: tuple[str, ...] = ()
    detail: str = ""
    choices: tuple[str, ...] = ()
    complete: bool = True
    normalize: Callable[[str], str] | None = None


@dataclass(frozen=True, slots=True)
class NumberField[Row]:
    """Range containment against the numbers ``get`` returns.

    Values are ``2026``, ``2020..2026``, ``..2026``, ``>=2026``, ``<2030``. A value that does
    not read as a number keeps its clause and matches nothing — see :func:`parser._typed_term`.

    ``parse`` reads values with units — ``took:>5m``, ``mem:1G..4G`` — into the numbers ``get``
    returns (seconds, bytes); it returns None for text that is not a quantity. Without it,
    values are integers. It may return a span, ``(lo, hi)``, for a value that stands for a
    stretch rather than a point: a time written to the minute is the whole minute, so
    ``time:14:30`` matches 14:30:59 and ``time:..14:30`` includes it (see ``parser._parse_range``).
    """

    name: str
    get: Callable[[Row], Numbers]
    aliases: tuple[str, ...] = ()
    detail: str = ""
    parse: Unit | None = None
    unquoted: str = ""
    """Punctuation ``parse`` reads, beyond the range operators: ``:`` for a time of day, ``+``
    for an offset. Values may carry it without quotes."""


@dataclass(frozen=True, slots=True)
class FlagField[Row]:
    """Named predicates: ``is:read`` holds when ``flags["read"](row)`` does.

    One table, so the completable names and the matchable names cannot drift apart. There is no
    ``is:none`` — a flag field has no values to be absent — so it matches nothing.
    """

    name: str
    flags: Mapping[str, Callable[[Row], bool]]
    aliases: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True, slots=True)
class CustomField[Row]:
    """The escape hatch: ``test(row, value)`` decides, one query value at a time.

    ``empty`` answers ``field:none`` — whether the row has nothing under this field — and
    without it ``field:none`` matches nothing. ``unquoted`` is punctuation the field's values
    may carry without quotes, for a field that reads an operator of its own (``netflix@us``).
    Values to complete come from ``choices`` or from a hand-built :class:`Vocabulary`.
    """

    name: str
    test: Callable[[Row, str], bool]
    aliases: tuple[str, ...] = ()
    detail: str = ""
    choices: tuple[str, ...] = ()
    empty: Callable[[Row], bool] | None = None
    unquoted: str = ""


type Field[Row] = (
    TextField[Row] | EnumField[Row] | NumberField[Row] | FlagField[Row] | CustomField[Row]
)


@dataclass(frozen=True, slots=True)
class Relation[Row]:
    """An edge a query may follow before asking: ``parent.year:<2020``.

    ``follow`` hands back the rows one hop away. A relation is only ever a step in a path,
    never the end of one — ``parent:x`` names no question — and a path steps one hop per
    segment, so ``parent.parent.name:x`` asks about the grandparent.
    """

    name: str
    follow: Callable[[Row], Iterable[Row]]
    aliases: tuple[str, ...] = ()
    detail: str = ""


# The operator spellings a field understands, and therefore the characters its values may
# carry unquoted. `year:>=2026`, `year:2020..2026`. Nothing else reads an operator, so nothing
# else earns one.
_NUMERIC_OPERATORS: Final[str] = "<>=."


def unquoted[Row](field: Field[Row]) -> str:
    """Punctuation this field's values may carry *without* quotes, beyond ``[A-Za-z0-9_-]``.

    Earned, not granted: a field gets a character because it declares an operator that spells
    one. A number field reads ranges, so it gets ``<>=.``, and whatever its parser declares it
    reads. Every other character has to be
    quoted, which is what keeps the punctuation free for the grammar to claim later — see
    :data:`lexer.WORD`.
    """
    match field:
        case NumberField(unquoted=extra):
            return _NUMERIC_OPERATORS + extra
        case CustomField(unquoted=extra):
            return extra
        case _:
            return ""


def detail_of[Row](field: Field[Row] | Relation[Row]) -> str:
    """What completion calls a field's values."""
    return field.detail or field.name


# --- the schema -----------------------------------------------------------------------------
# A field name is typed as the head of `name:value` and as a step of `a.b:value`, and it is
# lowercased on the way in. So: lowercase, no `.` (the path separator), no `:`, and no leading
# `-` (which would read as negation).
_NAME: Final[re.Pattern[str]] = re.compile(r"[a-z0-9_][a-z0-9_-]*")


class Schema[Row]:
    """Every field and relation a query may name, and which field bare words search.

    Construction fails loudly on any name claimed twice. Two fields sharing a name would
    silently shadow one another; an *alias* shadowing a real field is worse, because alias
    resolution runs first and the real field would become unreachable with nothing to show for
    it.
    """

    __slots__ = ("_aliases", "_fields", "_relations", "bare")

    def __init__(
        self,
        fields: Iterable[Field[Row]],
        *,
        bare: str,
        relations: Iterable[Relation[Row]] = (),
    ) -> None:
        self._fields: dict[str, Field[Row]] = {}
        self._relations: dict[str, Relation[Row]] = {}
        self._aliases: dict[str, str] = {}
        declared: list[Field[Row] | Relation[Row]] = [*fields, *relations]
        for spec in declared:
            self._claim(spec)
        for spec in declared:
            for alias in spec.aliases:
                self._alias(alias, spec.name)
        found = self.fields.get(bare)
        if not isinstance(found, TextField):
            raise ValueError(f"bare field {bare!r} must name a TextField of this schema")
        self.bare: str = bare

    def _claim(self, spec: Field[Row] | Relation[Row]) -> None:
        if not _NAME.fullmatch(spec.name):
            raise ValueError(f"field name {spec.name!r} must match {_NAME.pattern}")
        if spec.name in self.fields or spec.name in self.relations:
            raise ValueError(f"field name claimed twice: {spec.name!r}")
        if isinstance(spec, Relation):
            self._relations[spec.name] = spec
        else:
            self._fields[spec.name] = spec

    def _alias(self, alias: str, name: str) -> None:
        if not _NAME.fullmatch(alias):
            raise ValueError(f"alias {alias!r} must match {_NAME.pattern}")
        if alias in self.fields or alias in self.relations:
            raise ValueError(f"alias {alias!r} shadows the field of the same name")
        if alias in self._aliases:
            raise ValueError(f"alias claimed twice: {alias!r}")
        self._aliases[alias] = name

    # --- lookup ------------------------------------------------------------------------------
    @property
    def fields(self) -> Mapping[str, Field[Row]]:
        """Every field, by canonical name, in declaration order."""
        return self._fields

    @property
    def relations(self) -> Mapping[str, Relation[Row]]:
        """Every relation, by canonical name, in declaration order."""
        return self._relations

    @property
    def names(self) -> frozenset[str]:
        """Every canonical field and relation name."""
        return frozenset((*self.fields, *self.relations))

    def canonical(self, name: str) -> str:
        """The name an alias stands for. Idempotent on a real name, lowercases everything."""
        lowered = name.strip().lower()
        return self._aliases.get(lowered, lowered)

    def field(self, name: str) -> Field[Row] | None:
        """The field a name or alias refers to, or None if nothing goes by that name."""
        return self.fields.get(self.canonical(name))

    def relation(self, name: str) -> Relation[Row] | None:
        """The relation a name or alias refers to, or None."""
        return self.relations.get(self.canonical(name))

    # --- completion ------------------------------------------------------------------------
    def vocabulary(self, rows: Iterable[Row]) -> Vocabulary:
        """Every completable value on these rows, per field, most used first.

        Counted per row rather than per occurrence, so a value a row repeats is not ranked
        above one twice as many rows carry. Spellings that fold together are one entry, under
        whichever spelling was seen first.
        """
        counted = [
            f for f in self.fields.values() if isinstance(f, TextField | EnumField) and f.complete
        ]
        seen = tuple(rows)
        return Vocabulary({f.name: _tally(strings_of(f.get(row)) for row in seen) for f in counted})

    def completions(self, name: str, vocab: Vocabulary) -> Completions:
        """What a field completes to, given a vocabulary: its values, then its fixed choices."""
        spec = self.field(name)
        if spec is None:
            return ()
        detail = detail_of(spec)
        match spec:
            case FlagField(flags=flags):
                pool = tuple(VocabEntry(v) for v in flags)
            case NumberField():
                pool = vocab.of(spec.name)
            case (
                TextField(choices=choices)
                | EnumField(choices=choices)
                | CustomField(choices=choices)
            ):
                pool = _distinct((*vocab.of(spec.name), *(VocabEntry(v) for v in choices)))
        return tuple((entry, detail) for entry in pool)
