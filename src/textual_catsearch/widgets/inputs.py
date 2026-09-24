"""The text field every catsearch widget types into.

It also keeps the caret in view after a paste. Textual scrolls to the caret as the caret
moves, which for a paste is before layout has widened the field to the new text: the scroll is
clamped to the old width, nothing retries it, and a query pasted past the edge leaves the view
at its start with the caret out of sight. Typing hides this because each key moves the caret
by one cell.

Textual's ``Input`` binds ``ctrl+backspace`` and ``alt+backspace`` to ``delete_right_word`` —
backwards from what those chords mean in a shell, a browser or an editor, and from Textual's
own ``ctrl+w``. At the end of a line, which is where a query is usually being edited, deleting
rightward has nothing to delete, so the chord reads as dead rather than as wrong.
"""

from __future__ import annotations

from typing import ClassVar

from rich.cells import cell_len
from textual import on
from textual.binding import Binding, BindingType
from textual.geometry import Region
from textual.widgets import Input

__all__ = ["TextInput"]


class TextInput(Input):
    """An ``Input`` whose word-delete chords delete the word behind the caret.

    Three chords for one gesture because the terminal decides which of them arrives:
    ``ctrl+backspace`` only when the kitty keyboard protocol is disambiguating it, and
    ``ctrl+h`` for the terminals that send ``^H`` and cannot tell it from a plain backspace.
    ``alt+backspace`` is the one that works everywhere.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding(
            "ctrl+backspace,ctrl+h,alt+backspace",
            "delete_left_word",
            "Delete word left",
            show=False,
        ),
    ]

    @on(Input.Changed)
    def _caret_follows(self) -> None:
        # After the layout pass the change causes, when the field is as wide as its text.
        self.call_after_refresh(self.caret_into_view)

    def caret_into_view(self) -> None:
        """Scroll the least that shows the caret (in cells: wide and joined glyphs count)."""
        caret = cell_len(self.value[: self.cursor_position])
        self.scroll_to_region(Region(caret, 0, 1, 1), force=True, animate=False)
