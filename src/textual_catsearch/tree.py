"""The parsed shape of a query: clauses, conjunction, alternation and negation."""

from __future__ import annotations

from dataclasses import dataclass, replace

__all__ = ["And", "Expr", "Not", "NumRange", "Or", "Term", "neg"]


@dataclass(frozen=True, slots=True)
class NumRange:
    """An inclusive numeric window; an open end is ``None`` (``year:>=2026``)."""

    lo: int | None = None
    hi: int | None = None

    def contains(self, n: int) -> bool:
        return (self.lo is None or n >= self.lo) and (self.hi is None or n <= self.hi)


@dataclass(frozen=True, slots=True)
class Term:
    """One clause. ``values`` are OR-ed; ``negated`` inverts the whole term."""

    field: str
    values: tuple[str, ...] = ()
    ranges: tuple[NumRange, ...] = ()
    negated: bool = False
    # `field:none` — the row has nothing under this field. Its own flag rather than a value,
    # because a value is a string and this is not one: `tag:"none"` has to keep meaning a tag
    # called none, and a magic string in `values` would take that spelling away.
    #
    # OR-ed with the rest, so `tag:none,horror` is "untagged, or tagged horror".
    absent: bool = False
    # Relations to follow before asking: `parent.year:<2020` is `via=("parent",)` and
    # `field="year"`. On the term rather than a fifth node in the tree, because it is still one
    # clause — a question, asked somewhere else. Empty for every clause that asks about here.
    via: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class And:
    """Every part holds. The shape of a whole query — an empty one matches everything."""

    parts: tuple[Expr, ...] = ()


@dataclass(frozen=True, slots=True)
class Or:
    """Any part holds. Binds *tighter* than juxtaposition, so `a OR b c` is `(a OR b) and c`.

    The other way round is what formal logic does, and it is the wrong answer for a search
    bar: `kind:tv OR kind:movie -is:watched` plainly means "either kind, and not watched",
    which under the usual precedence would parse as "tv, or an unwatched movie". Juxtaposition
    is the *default* operator here and `OR` is a deliberate mark, so the deliberate one wins.
    Parentheses override, and `render` puts them in wherever the default would read wrong.
    """

    parts: tuple[Expr, ...] = ()


@dataclass(frozen=True, slots=True)
class Not:
    """The inner expression does *not* hold.

    Only ever wraps a group. Negating a single clause folds into :attr:`Term.negated`, which
    :func:`neg` is the one place that decides — two spellings of the same query would mean
    every normal-form and round-trip claim about the tree needed an "unless" attached.
    """

    inner: Expr


type Expr = Term | And | Or | Not


def neg(expr: Expr) -> Expr:
    """``expr``, negated, in normal form."""
    match expr:
        case Term():
            return replace(expr, negated=not expr.negated)
        case Not(inner=inner):
            return inner
        case _:
            return Not(expr)
