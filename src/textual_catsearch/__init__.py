"""Discord-style category search for Textual apps.

Declare the fields your rows have as a :class:`Schema`; get a query language over them
(``author:"le guin" year:1960..1980 -is:read``), filtering, rendering back to text, and
completion of field names and values. :class:`SearchBar` puts all of it in one widget.

The widgets are imported on first use: the query language needs no Textual, and a program that
only parses and evaluates queries (a CLI) does not pay for importing it.
"""

from typing import TYPE_CHECKING, Any

from textual_catsearch.complete import Suggestion, apply, rank_values, suggest
from textual_catsearch.evaluate import holds
from textual_catsearch.lexer import Token, active_span, lex
from textual_catsearch.parser import parse
from textual_catsearch.query import NOTHING, Diagnostic, Fault, Query
from textual_catsearch.render import quote, render
from textual_catsearch.schema import (
    CustomField,
    EnumField,
    Field,
    FlagField,
    NumberField,
    Relation,
    Schema,
    TextField,
    VocabEntry,
    Vocabulary,
)
from textual_catsearch.text import fold
from textual_catsearch.transform import pinned, with_term, without
from textual_catsearch.tree import And, Expr, Not, NumRange, Or, Term, neg

__all__ = [
    "NOTHING",
    "And",
    "CompletingInput",
    "CustomField",
    "Cycle",
    "Diagnostic",
    "EnumField",
    "Expr",
    "Fault",
    "Field",
    "FlagField",
    "Not",
    "NumRange",
    "NumberField",
    "Or",
    "Query",
    "Relation",
    "Schema",
    "SearchBar",
    "Suggestion",
    "Term",
    "TextField",
    "TextInput",
    "Token",
    "VocabEntry",
    "Vocabulary",
    "active_span",
    "apply",
    "fold",
    "holds",
    "lex",
    "neg",
    "parse",
    "pinned",
    "quote",
    "rank_values",
    "render",
    "suggest",
    "with_term",
    "without",
]

if TYPE_CHECKING:
    from textual_catsearch.widgets import CompletingInput, Cycle, SearchBar, TextInput

_WIDGETS = frozenset({"CompletingInput", "Cycle", "SearchBar", "TextInput"})


def __getattr__(name: str) -> Any:
    if name in _WIDGETS:
        from textual_catsearch import widgets

        return getattr(widgets, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
