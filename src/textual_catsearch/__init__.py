"""Discord-style category search for Textual apps.

Declare the fields your rows have as a :class:`Schema`; get a query language over them
(``author:"le guin" year:1960..1980 -is:read``), filtering, rendering back to text, and
completion of field names and values. :class:`SearchBar` puts all of it in one widget.
"""

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
from textual_catsearch.widgets import CompletingInput, Cycle, SearchBar, TextInput

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
