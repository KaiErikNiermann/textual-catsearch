"""A ←/→ picker over a short, closed list of values.

A category with a handful of values — a state, a kind, a sort order — is picked by stepping
along the list rather than by searching it. Emits :class:`Cycle.Changed` and never writes
anything; what the step means is up to the screen.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

from rich.text import Text
from textual.binding import Binding, BindingType
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from textual_catsearch.text import printable

__all__ = ["Cycle"]


class Cycle(Widget):
    """Step through ``values`` with ←/→. Renders as ``◂ value ▸`` unless told otherwise."""

    can_focus = True
    index: reactive[int] = reactive(0)

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("left,h", "step(-1)", "Prev", show=False),
        Binding("right,l", "step(1)", "Next", show=False),
    ]

    class Changed(Message):
        """The selection moved. ``value`` is the label now showing."""

        def __init__(self, cycle: Cycle, value: str) -> None:
            super().__init__()
            self.cycle = cycle
            self.value = value

        @property
        def control(self) -> Cycle:
            return self.cycle

    def __init__(self, values: Sequence[str], *, index: int = 0, id: str | None = None) -> None:
        # Refused here rather than at the first render, where an empty list or a stray index
        # surfaced as an IndexError from deep inside Textual's paint.
        if not values:
            raise ValueError("a Cycle needs at least one value")
        if not -len(values) <= index < len(values):
            raise ValueError(f"index {index} is outside the {len(values)} values")
        super().__init__(id=id)
        self.values = tuple(values)
        self.index = index % len(values)  # `-1`, the last, as Python indexes

    @property
    def value(self) -> str:
        """The label currently selected."""
        return self.values[self.index]

    def render(self) -> Text:
        # a value, not markup, and its control characters shown rather than sent
        return Text.assemble(("◂", "dim"), f" {printable(self.value)} ", ("▸", "dim"))

    def action_step(self, delta: int) -> None:
        self.index = (self.index + delta) % len(self.values)

    def watch_index(self) -> None:
        self.refresh()
        self.post_message(self.Changed(self, self.value))
