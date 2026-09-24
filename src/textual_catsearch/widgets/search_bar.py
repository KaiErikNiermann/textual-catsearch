"""The drop-in search bar: a completing input over a schema, plus the candidate strip under it.

Everything a screen needs from a category search in one widget. Hand it a :class:`Schema` and
a :class:`Vocabulary`; it completes field names and values as you type, previews the leading
candidate as a dim tail, walks candidates on tab, and posts :class:`SearchBar.Changed` whenever
what the bar *means* changes — the typed text plus the completion it is previewing, already
parsed. The screen filters its rows by that and nothing else::

    def compose(self) -> ComposeResult:
        yield SearchBar(SCHEMA, SCHEMA.vocabulary(self.rows))
        yield DataTable()

    def on_search_bar_changed(self, event: SearchBar.Changed) -> None:
        self.show(event.query.filter(self.rows))

Completion is *previewed* rather than committed: a half-typed ``is:a`` stands for ``is:aging``
with ``ging`` dimmed after the caret, so a partial term never shows an empty result, and what
the results are filtered by is exactly what the bar displays.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any, ClassVar

from rich.highlighter import Highlighter
from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.events import DescendantBlur, DescendantFocus
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Input, Static

from textual_catsearch.complete import Suggestion, suggest
from textual_catsearch.parser import parse
from textual_catsearch.query import Diagnostic, Fault, Query, notice_of
from textual_catsearch.schema import Schema, Vocabulary
from textual_catsearch.transform import pinned, with_term, without
from textual_catsearch.tree import Term
from textual_catsearch.widgets.completing import WALK_LIMIT, CompletingInput, completion_hint

__all__ = ["SearchBar", "settled"]

OPEN_WHILE_TYPING = frozenset({Fault.UNCLOSED_QUOTE, Fault.UNCLOSED_GROUP})
"""Faults every quote or group has until it is closed: not worth marking while still at the end."""


def settled(diagnostics: tuple[Diagnostic, ...], caret: int, typed: int) -> tuple[Diagnostic, ...]:
    """The diagnostics that are not just the text still being typed.

    ``kind:`` is an empty value for exactly as long as the caret sits after its colon, and every
    ``(`` is unclosed until its ``)`` is typed. Marking those would flash a warning on every
    keystroke, so a span ending at the caret, an open quote or group while the caret is at the
    end, and anything in the previewed completion rather than the typed text are left out.
    When the bar is not focused nothing is being typed: pass a caret past the end (``typed + 1``).
    """
    return tuple(
        d
        for d in diagnostics
        if d.end <= typed
        and d.end != caret
        and not (d.fault in OPEN_WHILE_TYPING and caret == typed)
    )


class _Spans(Highlighter):
    """Styles the diagnostics' spans in the input's text (offsets are code points, as Text's)."""

    def __init__(self) -> None:
        self.spans: tuple[tuple[int, int], ...] = ()
        self.style: Style | str = "underline"

    def highlight(self, text: Text) -> None:
        for start, end in self.spans:
            text.stylize(self.style, start, end)


class SearchBar[Row](Widget):
    """A query bar that completes against a schema and says what it currently means.

    ``implicit_accept`` (on by default) makes a space or leaving the bar take the previewed
    completion, which is right wherever the bar drives something on screen: the results are
    already filtered by the preview, and dropping it would contradict them. ``fields`` narrows
    which field names are offered. ``show_notices`` puts the parser's diagnostics — an unknown
    field, a ``year:soon`` — on the hint line when there are no candidates to show.
    """

    COMPONENT_CLASSES: ClassVar[set[str]] = {"catsearch--diagnostic"}
    """``catsearch--diagnostic`` styles the text a diagnostic is about, in the input."""

    DEFAULT_CSS = """
    SearchBar {
        height: auto;
    }
    SearchBar > .catsearch--diagnostic {
        color: $warning;
        text-style: underline;
    }
    SearchBar > CompletingInput {
        height: 1;
        border: none;
        padding: 0 1;
        background: $panel;
    }
    SearchBar > CompletingInput:focus {
        background: $panel-lighten-1;
    }
    SearchBar > .catsearch--hint {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        background: $panel;
    }
    """

    class Changed(Message):
        """What the bar means changed: ``source`` is the effective text, ``query`` its parse."""

        def __init__(self, bar: SearchBar[Any], source: str, query: Query[Any]) -> None:
            super().__init__()
            self.bar = bar
            self.source = source
            self.query = query

        @property
        def control(self) -> SearchBar[Any]:
            return self.bar

    class Submitted(Message):
        """Enter was pressed in the bar."""

        def __init__(self, bar: SearchBar[Any], source: str, query: Query[Any]) -> None:
            super().__init__()
            self.bar = bar
            self.source = source
            self.query = query

        @property
        def control(self) -> SearchBar[Any]:
            return self.bar

    def __init__(
        self,
        schema: Schema[Row],
        vocabulary: Vocabulary | None = None,
        *,
        value: str = "",
        placeholder: str = "",
        fields: frozenset[str] | None = None,
        limit: int = WALK_LIMIT,
        implicit_accept: bool = True,
        show_notices: bool = True,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self.schema = schema
        self._vocabulary = vocabulary or Vocabulary()
        self._fields = fields
        self._limit = limit
        self._show_notices = show_notices
        self._announced: str | None = None
        self._input = CompletingInput(
            self._suggest,
            value=value,
            placeholder=placeholder,
            implicit_accept=implicit_accept,
        )
        self._spans = _Spans()
        self._input.highlighter = self._spans

    def compose(self) -> ComposeResult:
        yield self._input
        yield Static("", classes="catsearch--hint")

    def on_mount(self) -> None:
        self._input.cursor_position = len(self._input.value)
        self.watch(self._input, "selection", self._caret_moved, init=False)  # the caret
        self._sync()

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        """What the bar marks: the parse's diagnostics, less what is still being typed."""
        typed = len(self._input.value)
        caret = self._input.cursor_position if self._input.has_focus else typed + 1
        return settled(self.parsed.diagnostics, caret, typed)

    # --- what the bar means --------------------------------------------------------------
    @property
    def input(self) -> CompletingInput:
        """The text field itself."""
        return self._input

    @property
    def source(self) -> str:
        """The typed text plus the completion it is previewing — what results should show."""
        return self._input.effective

    @property
    def parsed(self) -> Query[Row]:
        """:attr:`source`, parsed."""
        return parse(self.source, self.schema)

    @property
    def value(self) -> str:
        """The text as typed, without any preview."""
        return self._input.value

    @value.setter
    def value(self, text: str) -> None:
        """Replace the text and park the caret at the end, so the next keystroke continues it."""
        self._input.ghost = ""
        self._input.value = text
        self._input.cursor_position = len(text)

    @property
    def vocabulary(self) -> Vocabulary:
        return self._vocabulary

    @vocabulary.setter
    def vocabulary(self, vocab: Vocabulary) -> None:
        """Swap the values on offer — the rows changed — and start the offer over."""
        self._vocabulary = vocab
        self._input.candidates = self._suggest

    @property
    def picks(self) -> tuple[Suggestion, ...]:
        """The candidates tab is walking, empty when there are none."""
        return self._input.picks

    def pinned(self, field: str, among: Collection[str] | None = None) -> str | None:
        """The value the bar's query pins ``field`` to — which category tab is lit."""
        return pinned(self.parsed, field, among)

    def pin(self, field: str, value: str, *, among: Collection[str] | None = None) -> None:
        """Rewrite the query so it pins ``field`` to ``value``, every other clause intact.

        What a category tab does. ``among`` limits which existing clauses count as the tab
        being replaced, so pinning ``is:read`` over ``is:unread is:starred`` keeps the star.
        """
        rewritten = with_term(self.parsed, Term(field, (value,)), among=among)
        self.value = f"{rewritten} "

    def unpin(self, field: str, *, among: Collection[str] | None = None) -> None:
        """Rewrite the query so nothing pins ``field`` (the "all" tab), other clauses intact."""
        rewritten = without(self.parsed, field, among=among)
        self.value = f"{rewritten} " if rewritten else ""

    def focus(self, scroll_visible: bool = True) -> SearchBar[Row]:
        """Focusing the bar focuses the text field in it."""
        self._input.focus(scroll_visible)
        return self

    # --- plumbing ------------------------------------------------------------------------
    def _suggest(self, source: str, caret: int) -> tuple[Suggestion, ...]:
        return suggest(
            source, caret, self.schema, self._vocabulary, limit=self._limit, fields=self._fields
        )

    @on(Input.Changed)
    @on(CompletingInput.Offered)
    def _on_edit(self, event: Message) -> None:
        event.stop()
        self._sync()

    @on(Input.Submitted)
    def _on_submit(self, event: Input.Submitted) -> None:
        event.stop()
        self.post_message(self.Submitted(self, self.source, self.parsed))

    def on_descendant_focus(self, _: DescendantFocus) -> None:
        self._sync()

    def on_descendant_blur(self, _: DescendantBlur) -> None:
        self._sync()

    def _sync(self) -> None:
        """Repaint the hint, and announce the meaning if it moved."""
        query = self.parsed
        self._paint_hint()
        if self.source != self._announced:
            self._announced = self.source
            self.post_message(self.Changed(self, self.source, query))

    def _caret_moved(self) -> None:
        self._paint_hint()

    def _paint_hint(self) -> None:
        """The candidates, else the diagnostic under the caret, else a summary; marks the spans."""
        if not self.is_mounted:
            return
        shown = self.diagnostics if self._show_notices else ()
        self._mark(shown)
        hint = self.query_one(".catsearch--hint", Static)
        caret = self._input.cursor_position
        here = next((d for d in shown if d.start <= caret <= d.end), None)
        if picks := self._input.picks:
            hint.update(completion_hint(picks, self._input.index))
        elif here is not None:  # the caret is on it: say what is wrong with this one
            hint.update(Text(f"? {here.render()}", style="yellow"))
        elif notice := notice_of(shown):
            hint.update(Text(f"? {notice}", style="yellow"))
        else:
            hint.update("")

    def _mark(self, shown: tuple[Diagnostic, ...]) -> None:
        spans = tuple((d.start, d.end) for d in shown)
        if spans != self._spans.spans:
            self._spans.spans = spans
            self._spans.style = self.get_component_rich_style("catsearch--diagnostic")
            self._input.refresh()
