# Python API

Everything below is importable from `textual_catsearch`. The widgets import Textual on first use; the rest does not need it.

```{eval-rst}
.. currentmodule:: textual_catsearch
```

## Parsing and matching

```{eval-rst}
.. autofunction:: parse
.. autoclass:: Query
   :members:
.. autoclass:: Diagnostic
   :members:
.. autoclass:: Fault
   :members:
   :undoc-members:
.. autofunction:: holds
```

## Schema and fields

```{eval-rst}
.. autoclass:: Schema
   :members:
.. autodata:: Field
.. autoclass:: TextField
.. autoclass:: EnumField
.. autoclass:: NumberField
.. autoclass:: FlagField
.. autoclass:: CustomField
.. autoclass:: Relation
.. autoclass:: Vocabulary
   :members:
.. autoclass:: VocabEntry
```

## Rendering and text

```{eval-rst}
.. autofunction:: render
.. autofunction:: quote
.. autofunction:: fold
```

## Completion

```{eval-rst}
.. autofunction:: suggest
.. autofunction:: apply
.. autofunction:: rank_values
.. autoclass:: Suggestion
```

## Editing queries

The transforms behind category tabs: each returns new query text.

```{eval-rst}
.. autofunction:: pinned
.. autofunction:: with_term
.. autofunction:: without
```

## Query trees

```{eval-rst}
.. autodata:: Expr
.. autoclass:: Term
.. autoclass:: And
.. autoclass:: Or
.. autoclass:: Not
.. autoclass:: NumRange
.. autofunction:: neg
.. autodata:: NOTHING
```

## Lexing

```{eval-rst}
.. autofunction:: lex
.. autoclass:: Token
.. autofunction:: active_span
```

## Widgets

```{eval-rst}
.. autoclass:: SearchBar
   :members: Changed, Submitted, value, parsed, source, vocabulary, diagnostics, picks, pin, pinned, unpin
.. autoclass:: CompletingInput
.. autoclass:: TextInput
.. autoclass:: Cycle
```
