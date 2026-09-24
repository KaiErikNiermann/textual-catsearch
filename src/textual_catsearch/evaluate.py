"""Evaluation: does a query hold for a row? Pure and in-memory — cheap enough per keystroke."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from textual_catsearch.schema import (
    CustomField,
    EnumField,
    Field,
    FlagField,
    NumberField,
    Schema,
    TextField,
    numbers_of,
    strings_of,
)
from textual_catsearch.text import fold
from textual_catsearch.tree import And, Expr, Not, NumRange, Or, Term

__all__ = ["holds"]


def holds[Row](expr: Expr, row: Row, schema: Schema[Row]) -> bool:
    """Does an expression hold for this row? Structural recursion over the tree."""
    match expr:
        case Term():
            return _match_term(expr, row, schema) != expr.negated
        case And(parts=parts):
            return all(holds(p, row, schema) for p in parts)
        case Or(parts=parts):
            return any(holds(p, row, schema) for p in parts)
        case Not(inner=inner):
            return not holds(inner, row, schema)


def _match_term[Row](term: Term, row: Row, schema: Schema[Row]) -> bool:
    """Does one clause hold for this row (before negation)?

    A clause names a field the schema no longer has only when a tree was built by hand against
    another schema; it answers no rather than matching everything.
    """
    spec = schema.fields.get(term.field)
    if spec is None:
        return False
    if term.via:
        return any(_asked_here(term, spec, r) for r in _walked(term.via, row, schema))
    return _asked_here(term, spec, row)


def _asked_here[Row](term: Term, spec: Field[Row], row: Row) -> bool:
    """The clause, asked of one row — the two questions it can be, OR-ed.

    ``tag:none,horror`` asks both: is there nothing here, and is one of these values here. A
    clause with no ``none`` in it only ever asks the second.
    """
    return (term.absent and _has_nothing(spec, row)) or _holds_value(term, spec, row)


def _walked[Row](via: Sequence[str], row: Row, schema: Schema[Row]) -> tuple[Row, ...]:
    """The rows a path arrives at — one hop per step.

    Deduplicated at every step, and by identity since a row need not be hashable. That is not
    tidiness: a graph that forks and rejoins would otherwise double the frontier per hop, so a
    long path over a small graph could cost more than the whole data set.
    """
    here: dict[int, Row] = {id(row): row}
    for step in via:
        relation = schema.relations.get(step)
        if relation is None:
            return ()
        here = {id(found): found for current in here.values() for found in relation.follow(current)}
        if not here:
            return ()
    return tuple(here.values())


def _holds_value[Row](term: Term, spec: Field[Row], row: Row) -> bool:
    """Does any of the clause's values match?

    Dispatch is on the field's *kind*, exhaustively. A field cannot reach here without having
    declared how it is compared, which is what stops an unrecognised field answering ``True``
    and quietly matching every row.

    A clause that asked only about absence arrives here with no values, and every case answers
    no to an empty list — which is what makes the OR above the whole of the rule rather than a
    branch with a special case behind it.
    """
    match spec:
        case TextField(get=get):
            return _substring(term.values, strings_of(get(row)))
        case EnumField(get=get, normalize=normalize):
            wanted = term.values if normalize is None else tuple(map(normalize, term.values))
            return _equal(wanted, strings_of(get(row)))
        case NumberField(get=get):
            return _match_num(term.ranges, numbers_of(get(row)))
        case FlagField(flags=flags):
            return _flagged(term.values, flags, row)
        case CustomField(test=test):
            return any(test(row, v) for v in term.values)


def _substring(needles: Sequence[str], haystacks: Sequence[str]) -> bool:
    hays = [fold(h) for h in haystacks]
    return any(fold(n) in h for n in needles for h in hays)


def _equal(needles: Sequence[str], haystacks: Sequence[str]) -> bool:
    hays = {fold(h) for h in haystacks}
    return any(fold(n) in hays for n in needles)


def _flagged[Row](
    asked: Sequence[str], flags: Mapping[str, Callable[[Row], bool]], row: Row
) -> bool:
    """Is any asked-for flag both named in the table and true of the row?"""
    wanted = {fold(v) for v in asked}
    return any(test(row) for name, test in flags.items() if fold(name) in wanted)


def _match_num(ranges: Sequence[NumRange], values: Sequence[int]) -> bool:
    return any(r.contains(n) for r in ranges for n in values)


def _has_nothing[Row](spec: Field[Row], row: Row) -> bool:
    """Does this row carry nothing at all under this field?

    The question `-tag:horror` cannot ask. Negating a value asks "not this one", and a row with
    no tags answers yes to that as surely as a row tagged comedy does — which is right, and
    leaves "has none" unaskable. Now both are sayable, and the difference between them is the
    difference between a filter and a gap in the data.

    Not defined for a flag field, whose value set is a set of questions rather than data.
    """
    match spec:
        case TextField(get=get) | EnumField(get=get):
            return not strings_of(get(row))
        case NumberField(get=get):
            return not numbers_of(get(row))
        case FlagField():
            return False
        case CustomField(empty=empty):
            return empty is not None and empty(row)
