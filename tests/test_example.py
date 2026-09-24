"""The example app boots, filters, completes and pins — so the README's promise stays true."""

from __future__ import annotations

from typing import cast

from books import BOOKS, Library
from textual.widgets import DataTable


async def test_the_example_library_searches() -> None:
    app = Library()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        table = cast("DataTable[str]", app.query_one("#books", DataTable))
        assert table.row_count == len(BOOKS)
        await pilot.press(*"by:le", "tab")
        await pilot.pause()
        assert app.search.value == 'author:"Ursula K. Le Guin"'
        assert table.row_count == 4
        table.focus()
        await pilot.press("1")
        await pilot.pause()
        assert app.search.pinned("is") == "unread"
        assert table.row_count == 3
        app.search.value = "follows.title:dune"
        await pilot.pause()
        assert table.row_count == 1
