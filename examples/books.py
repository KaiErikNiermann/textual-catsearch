"""A book library with a Discord-style search bar. Run: ``poetry run python examples/books.py``.

Try ``author:le``, tab, tab; ``year:1960..1980 -is:read``; ``follows.title:dune``; ``series:none``;
press 1/2/3 (from the table) to pin a category.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, cast

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.widgets import DataTable, Footer, Static

from textual_catsearch import (
    EnumField,
    FlagField,
    NumberField,
    Relation,
    Schema,
    SearchBar,
    TextField,
)


@dataclass(frozen=True, slots=True)
class Book:
    title: str
    author: str
    year: int
    format: str
    genres: tuple[str, ...] = ()
    series: str | None = None
    read: bool = False
    follows: tuple[Book, ...] = ()


_DUNE = Book("Dune", "Frank Herbert", 1965, "paperback", ("sci-fi",), "Dune", read=True)
_MESSIAH = Book(
    "Dune Messiah", "Frank Herbert", 1969, "paperback", ("sci-fi",), "Dune", follows=(_DUNE,)
)
_EARTHSEA = Book(
    "A Wizard of Earthsea",
    "Ursula K. Le Guin",
    1968,
    "hardcover",
    ("fantasy",),
    "Earthsea",
    read=True,
)
_TOMBS = Book(
    "The Tombs of Atuan",
    "Ursula K. Le Guin",
    1970,
    "ebook",
    ("fantasy",),
    "Earthsea",
    follows=(_EARTHSEA,),
)

BOOKS: tuple[Book, ...] = (
    _DUNE,
    _MESSIAH,
    _EARTHSEA,
    _TOMBS,
    Book("The Left Hand of Darkness", "Ursula K. Le Guin", 1969, "paperback", ("sci-fi",)),
    Book("Neuromancer", "William Gibson", 1984, "ebook", ("sci-fi", "cyberpunk"), read=True),
    Book("Piranesi", "Susanna Clarke", 2020, "hardcover", ("fantasy",)),
    Book("The Dispossessed", "Ursula K. Le Guin", 1974, "hardcover", ("sci-fi", "utopia")),
)

SCHEMA: Schema[Book] = Schema(
    [
        TextField("title", lambda b: b.title, aliases=("name",), complete=False),
        TextField("author", lambda b: b.author, aliases=("by",)),
        TextField("genre", lambda b: b.genres, aliases=("tag",)),
        TextField("series", lambda b: b.series),
        EnumField("format", lambda b: b.format, choices=("hardcover", "paperback", "ebook")),
        NumberField("year", lambda b: b.year),
        FlagField("is", {"read": lambda b: b.read, "unread": lambda b: not b.read}),
    ],
    bare="title",
    relations=[Relation("follows", lambda b: b.follows)],
)

CATEGORIES = ("unread", "read")


class Library(App[None]):
    CSS = """
    #count { height: 1; padding: 0 1; color: $text-muted; }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("1", "pin('unread')", "Unread"),
        Binding("2", "pin('read')", "Read"),
        Binding("slash", "search", "Search"),
        Binding("tab", "focus_next", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield SearchBar(
            SCHEMA,
            SCHEMA.vocabulary(BOOKS),
            placeholder='search — e.g. author:"le guin" year:<1970 -is:read',
            id="search",
        )
        yield DataTable[str](id="books", cursor_type="row", zebra_stripes=True)
        yield Static(id="count")
        yield Footer()

    @property
    def search(self) -> SearchBar[Book]:
        return cast("SearchBar[Book]", self.query_one("#search", SearchBar))

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("Title", "Author", "Year", "Format", "Read")
        self.search.focus()

    def on_search_bar_changed(self, event: SearchBar.Changed) -> None:
        shown = cast("list[Book]", event.query.filter(BOOKS))
        table = cast("DataTable[str]", self.query_one("#books", DataTable))
        table.clear()
        for b in shown:
            table.add_row(b.title, b.author, str(b.year), b.format, "✓" if b.read else "")
        pinned = self.search.pinned("is", CATEGORIES) or "all"
        self.query_one("#count", Static).update(f"{len(shown)}/{len(BOOKS)} · {pinned}")

    def on_search_bar_submitted(self) -> None:
        self.query_one(DataTable).focus()

    def action_pin(self, category: str) -> None:
        self.search.pin("is", category, among=CATEGORIES)

    def action_search(self) -> None:
        self.search.focus()


if __name__ == "__main__":
    Library().run()
