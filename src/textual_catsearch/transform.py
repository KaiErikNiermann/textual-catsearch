"""Editing a query as a tree: pin a category, read which one is pinned.

Category tabs — "all / unread / read", "open / closed" — are best built as sugar over the query
language rather than as separate view state: there is one source of truth for what is on
screen, and pressing a tab teaches the syntax by showing it in the bar. These two functions
are that sugar. They edit the parsed tree and write it back out, rather than re-lexing the
string, so there is no second opinion about quoting, negation or what a clause looks like.
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import replace

from textual_catsearch.query import Query
from textual_catsearch.render import render
from textual_catsearch.tree import And, Expr, Term

__all__ = ["pinned", "with_term", "without"]


def _top_level(expr: Expr) -> tuple[Expr, ...]:
    """The clauses and groups a query is a conjunction of."""
    return expr.parts if isinstance(expr, And) else (expr,)


def _category(among: Collection[str] | None) -> Callable[[str], bool]:
    """Is a value one of the categories — any value at all when ``among`` is not given?"""
    folded = None if among is None else {v.casefold() for v in among}
    return lambda v: folded is None or v.casefold() in folded


def _here(term: Term, field: str) -> bool:
    """A positive clause asking about ``field`` of this row, not of one a path reaches."""
    return term.field == field and not term.negated and not term.via


def pinned[Row](query: Query[Row], field: str, among: Collection[str] | None = None) -> str | None:
    """The value the query pins ``field`` to, or None.

    Only a clause in the query's conjunctive core counts. A value named inside a disjunction —
    "unread or starred" — pins nothing, and lighting a tab for it would say the view is
    narrower than it is. ``among`` restricts the answer to a set of values (the tabs), so an
    ``is:starred`` beside ``is:unread`` does not get mistaken for a tab.
    """
    is_category = _category(among)
    return next(
        (
            v
            for part in _top_level(query.expr)
            if isinstance(part, Term) and _here(part, field)
            for v in part.values
            if is_category(v)
        ),
        None,
    )


def with_term[Row](
    query: Query[Row],
    term: Term,
    *,
    among: Collection[str] | None = None,
) -> str:
    """The query rewritten so ``term`` pins its field, every other clause left intact.

    The clause that already pinned the field is replaced and ``term`` goes first. With
    ``among``, only the category values are taken out of that clause and the rest ride along
    with ``term`` — a key written twice is one clause (``is:blocked is:unread`` *is*
    ``is:blocked,unread``), so replacing it wholesale would drop ``blocked``. Returns source
    text, ready for the bar.
    """
    is_category = _category(among)
    others: list[str] = []
    kept: list[Expr] = []
    for part in _top_level(query.expr):
        if (
            isinstance(part, Term)
            and _here(part, term.field)
            and any(map(is_category, part.values))
        ):
            others.extend(v for v in part.values if not is_category(v))
        else:
            kept.append(part)
    pin = replace(term, values=tuple(dict.fromkeys((*term.values, *others))))
    return render(And((pin, *kept)), query.schema)


def without[Row](query: Query[Row], field: str, *, among: Collection[str] | None = None) -> str:
    """The query with no pin on ``field`` — the "all" tab — every other clause left intact.

    The inverse of :func:`with_term`: with ``among``, only the category values leave their
    clause, so clearing the ``unread`` tab from ``is:unread,starred`` keeps ``is:starred``.
    Returns source text, ready for the bar.
    """
    is_category = _category(among)
    kept: list[Expr] = []
    for part in _top_level(query.expr):
        if isinstance(part, Term) and _here(part, field):
            rest = tuple(v for v in part.values if not is_category(v))
            if rest or part.absent:
                kept.append(replace(part, values=rest))
            continue
        kept.append(part)
    return render(And(tuple(kept)), query.schema)
