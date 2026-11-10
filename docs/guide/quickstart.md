# Quickstart

Both versions start the same way: describe a row as a schema of named fields, then parse queries against it.

## Python

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


BOOKS = [
    Book("The Dispossessed", "Ursula K. Le Guin", 1974, "paperback", read=True),
    Book("Dune", "Frank Herbert", 1965, "hardcover"),
]

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

A complete, runnable app is [`examples/books.py`](https://github.com/KaiErikNiermann/textual-catsearch/blob/master/examples/books.py): `poetry run python examples/books.py`.

Without the widget, the language is plain functions:

```python
from textual_catsearch import parse, render, suggest

query = parse('by:"le guin" -is:read', SCHEMA)
query.filter(BOOKS)  # the rows it keeps
query.notice  # what the parser noticed, for a status line ("" when nothing)
render(query.expr, SCHEMA)  # 'author:"le guin" -is:read'
suggest("by:le", 5, SCHEMA, SCHEMA.vocabulary(BOOKS))  # completions for the token under the caret
```

## TypeScript

The same schema, with camelCase names and options as objects:

```ts
import { Schema, enumField, flagField, numberField, parse, render, suggest, textField } from "catsearch";

interface Book {
  title: string;
  author: string;
  year: number;
  format: string;
  read: boolean;
}

const schema = new Schema<Book>(
  [
    textField({ name: "title", get: (b) => b.title, complete: false }),
    textField({ name: "author", get: (b) => b.author, aliases: ["by"] }),
    enumField({ name: "format", get: (b) => b.format, choices: ["hardcover", "paperback", "ebook"] }),
    numberField({ name: "year", get: (b) => b.year }),
    flagField({ name: "is", flags: { read: (b) => b.read, unread: (b) => !b.read } }),
  ],
  { bare: "title" },
);

const query = parse('by:"le guin" -is:read', schema);
query.filter(books);
render(query.expr, schema);
suggest("by:le", 5, schema, schema.vocabulary(books));
```

Offsets in the TypeScript version (`Diagnostic.start`, `Suggestion.start`, the cursor passed to `suggest`) are UTF-16 code units, as the DOM counts them; Python counts code points. The [demo](../demo.md) wires this into a search bar with a dropdown of completions.

## Next

- [Usage guide](usage.md): the query syntax, the field kinds, dynamic fields and the widgets.
- [Python API](../reference/python.md) and [TypeScript API](../reference/typescript.md).
