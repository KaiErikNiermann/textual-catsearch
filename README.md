# textual-catsearch

Discord-style category search for [Textual](https://textual.textualize.io/) apps. You declare the fields your rows have; you get a query language over them, filtering, and a search bar that completes field names and values as you type.

```
author:"le guin" year:1960..1980 -is:read
(format:ebook OR format:hardcover) genre:sci-fi
follows.title:dune series:none
```

The bar previews the leading completion as a dim tail (so `is:u` already filters as `is:upcoming`), tab takes it, tab again walks to the next candidate, shift+tab walks back, and a space or leaving the bar accepts what is shown.

## Install

```sh
poetry add textual-catsearch   # or: pip install textual-catsearch
```

Requires Python 3.13+ and Textual 8.

## Quick start

```python
from dataclasses import dataclass

from textual.app import App, ComposeResult
from textual.widgets import DataTable

from textual_catsearch import EnumField, FlagField, NumberField, Schema, SearchBar, TextField


@dataclass(frozen=True)
class Book:
    title: str
    author: str
    year: int
    format: str
    read: bool = False


SCHEMA: Schema[Book] = Schema(
    [
        TextField("title", lambda b: b.title, complete=False),
        TextField("author", lambda b: b.author, aliases=("by",)),
        EnumField("format", lambda b: b.format, choices=("hardcover", "paperback", "ebook")),
        NumberField("year", lambda b: b.year),
        FlagField("is", {"read": lambda b: b.read, "unread": lambda b: not b.read}),
    ],
    bare="title",  # which field bare words search
)


class Library(App[None]):
    def compose(self) -> ComposeResult:
        yield SearchBar(SCHEMA, SCHEMA.vocabulary(BOOKS))
        yield DataTable()

    def on_search_bar_changed(self, event: SearchBar.Changed) -> None:
        rows = event.query.filter(BOOKS)
        ...  # repaint the table
```

A complete, runnable version is in [`examples/books.py`](examples/books.py): `poetry run python examples/books.py`.

## The language

| Syntax | Meaning |
| --- | --- |
| `dune messiah` | bare words search the `bare` field; every word must match |
| `author:herbert` | a field; comma-separated values are alternatives (`genre:sci-fi,fantasy`) |
| `author:"Le Guin"` | quotes make one value; `""` inside quotes is a literal quote |
| `-genre:horror`, `!genre:horror` | negation |
| `a OR b`, `a \| b` | alternation, binding tighter than juxtaposition: `a OR b c` is `(a OR b) c` |
| `(…)`, `-(…)` | grouping, and negating a group |
| `year:2020..2026`, `year:>=2020`, `year:<1970` | ranges on number fields |
| `series:none` | rows with nothing under the field |
| `follows.year:<1970` | ask the question of the rows a relation leads to |

A key written twice ORs (`format:ebook format:hardcover` is `format:ebook,hardcover`); different keys AND. The parser never raises: an unknown field is searched as text, a half-typed `kind:` constrains nothing, and every recovery is reported as a `Diagnostic` (`query.notice` gives one line for a status bar; the `SearchBar` shows it on its hint line).

## Field kinds

| Kind | Matches | Completes from |
| --- | --- | --- |
| `TextField(name, get)` | case- and accent-insensitive substring | values on the rows, plus `choices` |
| `EnumField(name, get, normalize=…)` | case- and accent-insensitive equality; `normalize` maps synonyms | values on the rows, plus `choices` |
| `NumberField(name, get)` | range containment | a hand-built `Vocabulary`, if any |
| `FlagField(name, {flag: predicate})` | named predicates (`is:read`) | the flag names |
| `CustomField(name, test, empty=…, unquoted=…, check=…, every=…)` | `test(row, value)` decides; `check(value)` may say why a value cannot be used, reported as an `invalid-value` diagnostic on the value; with `every=True` the values are conditions that must all hold rather than alternatives | `choices` or a hand-built `Vocabulary` |
| `Relation(name, follow)` | a path step: `name.field:value` | offered as `name.` |

Accessors may return one value, an iterable of values, or `None`; a lone string is one value, never its characters. Every field takes `aliases=` and `detail=` (the label shown next to its completions). `Schema` refuses names claimed twice, aliases that shadow a field, and names that cannot be typed as a key.

`Schema.vocabulary(rows)` counts each value once per row, merges spellings that fold together, and ranks by use; rebuild it when the rows change and assign it to `SearchBar.vocabulary`.

## Dynamic fields

Some rows carry keys the app cannot list in advance: a log line's `status=` or `"http": {"status": ...}`, a record's labels, a JSON document's properties. `Schema(..., dynamic=make)` lets a query name them as it names any field: a key no field, alias or relation path claims is handed to `make(key)`, which returns the field for it (named `key`) or `None` to decline it.

```python
def kv(key: str) -> CustomField[Line] | None:
    return CustomField(key, lambda line, value: line.fields.get(key) == value, empty=lambda line: key not in line.fields)

SCHEMA = Schema([TextField("text", lambda r: r.text), NumberField("level", ...)], bare="text", dynamic=kv)

parse("status:500,502 http.status:503 -userId:7", SCHEMA)
```

- A key is taken as typed, case and all, dots included: data keys are not the schema's lowercase names, so `userId` and `userid` are two keys, and `http.status` (when `http` is no relation) is one key, not a path.
- Declared names always win: `level:3` is the declared field in any case (`Level:3` too), and `parent.level:3` a declared path, never the data's own `level` key. An app that also wants that key offers an explicit field for it (pm's log search keeps `kv:level=warn`).
- `make` is asked once per key; its answer, `None` included, is kept for the 4096 most recently used keys (`DYNAMIC_KEYS`), so a long-lived bar does not grow without bound.
- A key `make` declines, or one that cannot be a key (`[A-Za-z0-9_][A-Za-z0-9_.-]*`), reads as text with an `unknown-field` diagnostic, as without `dynamic`.
- The data's keys complete after the declared names: pass them as `Vocabulary(keys=(VocabEntry("status", uses), ...))`. Values complete through the field `make` returns, as for any field.

## Widgets

- `SearchBar(schema, vocabulary, *, value, placeholder, fields, limit, implicit_accept, show_notices)` is the drop-in: a completing input plus the candidate strip under it. It posts `SearchBar.Changed(source, query)` whenever what the bar means changes and `SearchBar.Submitted` on enter. `pin(field, value, among=…)` and `pinned(field, among)` implement category tabs as edits to the query, so pressing a tab shows its syntax in the bar. With `show_notices`, each diagnostic's span is underlined in the text (style it with the `catsearch--diagnostic` component class) and the hint line names the one under the caret; what is still being typed (a value ending at the caret, a quote or bracket still open at the end) is not marked. `SearchBar.diagnostics` gives what is marked.
- `CompletingInput(suggester, *, implicit_accept)` is the input on its own, completing against any `(text, caret) -> Sequence[Suggestion]` function. `field_suggester(schema, field, vocab)` builds one that completes a whole form field against one field's values.
- `TextInput` is a Textual `Input` whose ctrl/alt+backspace delete the word to the left.
- `Cycle(values)` is a ←/→ picker over a short list.

`query_one` isinstance-checks, so it cannot take `SearchBar[Book]`; cast the result: `cast("SearchBar[Book]", self.query_one(SearchBar))`.

## Without a terminal

Everything under the widgets is pure and usable on its own — for a CLI, shell completion, or tests:

```python
from textual_catsearch import parse, render, suggest

query = parse('by:"le guin" -is:read', SCHEMA)
query.filter(BOOKS)  # the rows it keeps
render(query.expr, SCHEMA)  # 'author:"le guin" -is:read'
suggest("by:le", 5, SCHEMA, vocab)  # completions for the token under the caret
```

`render` is the inverse of `parse` (`parse(render(e)) == e`, checked by property tests), so queries can be edited as trees and written back out.

## Development

```sh
poetry install
poetry run pytest
poetry run pyright
poetry run ruff check . && poetry run ruff format --check .
poetry run radon cc -s -n C src   # nothing should print
```
