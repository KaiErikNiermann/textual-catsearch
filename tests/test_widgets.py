"""Behavioural tests for the widgets, driven through Textual's Pilot.

Assertions are about behaviour, not pixels: what the bar holds, what it means, what the rows
filtered by it are, and where focus is. No snapshot baselines — the framework moves fast enough
that SVG diffs would be noise.
"""

from __future__ import annotations

import re
from typing import ClassVar, cast

import pytest
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.pilot import Pilot
from textual.widgets import DataTable

from catalog import BUCKETS, SCHEMA, Work
from textual_catsearch import Cycle, SearchBar, Suggestion, Vocabulary, suggest
from textual_catsearch.widgets import CompletingInput, field_suggester

ROWS = (
    Work(
        title="Sinners",
        kind="movie",
        years=(2025,),
        genres=("Horror",),
        director=("Dir Sinners",),
        freshness="aging",
    ),
    Work(
        title="Weapons", kind="movie", years=(2025,), genres=("Horror",), director=("Dir Weapons",)
    ),
    Work(
        title="Dune: Part Three",
        kind="movie",
        years=(2026,),
        genres=("Sci-Fi",),
        director=("Dir Dune",),
        bucket="upcoming",
    ),
    Work(
        title="The Long Walk",
        kind="movie",
        years=(2025,),
        genres=("Horror",),
        director=("Dir Walk",),
        bucket="watched",
        state="watched",
    ),
)
VOCAB = SCHEMA.vocabulary(ROWS)


class Browse(App[None]):
    """The shape every consumer has: a bar, and a list it filters."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("1", "bucket('available')", show=False),
        Binding("3", "bucket('watched')", show=False),
        Binding("tab", "focus_next", show=False),
        Binding("shift+tab", "focus_previous", show=False),
    ]

    def __init__(self, value: str = "") -> None:
        super().__init__()
        self.value = value
        self.shown: list[str] = []
        self.changes = 0

    def compose(self) -> ComposeResult:
        yield SearchBar(SCHEMA, VOCAB, value=self.value, id="bar")
        yield DataTable[str](id="rows")

    @property
    def bar(self) -> SearchBar[Work]:
        # `query_one` isinstance-checks, so it cannot take the parameterised type.
        return cast("SearchBar[Work]", self.query_one("#bar", SearchBar))

    def on_search_bar_changed(self, event: SearchBar.Changed) -> None:
        self.changes += 1
        # The event is a snapshot: by the time it is handled the bar may have moved on.
        self.shown = [w.title for w in event.query.filter(ROWS)]

    def action_bucket(self, name: str) -> None:
        self.bar.pin("is", name, among=BUCKETS)


async def _type(pilot: Pilot[None], text: str) -> SearchBar[Work]:
    app = pilot.app
    assert isinstance(app, Browse)
    app.bar.value = ""
    app.bar.focus()
    await pilot.press(*text)
    await pilot.pause()
    return app.bar


def _hint(app: Browse) -> str:
    return str(app.query_one(".catsearch--hint").render())


# --- the bar means what it shows ------------------------------------------------------------
async def test_typing_filters_live() -> None:
    app = Browse()
    async with app.run_test(size=(120, 24)) as pilot:
        bar = await _type(pilot, "genre:horror -is:watched")
        assert app.shown == ["Sinners", "Weapons"]
        assert bar.parsed.filter(ROWS) == [ROWS[0], ROWS[1]]


async def test_a_half_typed_value_previews_instead_of_showing_nothing() -> None:
    """`is:u` matches no flag, so filtering by it as typed would empty the list.

    It stands for the `is:upcoming` it is one keystroke away from instead: the completion is
    painted as the bar's dim tail and the list shows what accepting it would give.
    """
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        bar = await _type(pilot, "is:u")
        assert bar.value == "is:u"  # nothing was written into the bar
        assert bar.input.ghost == "is:upcoming"
        assert bar.source == "is:upcoming"
        assert app.shown == ["Dune: Part Three"]


async def test_tab_takes_the_offered_completion_then_walks_on() -> None:
    """The tail is a hint, and a hint you cannot pick up leaves the term to be typed out.

    So the first tab writes what is on offer into the bar and the next steps on to the
    following candidate, rewriting the term in place — with the caret left at the end of it,
    so a space carries straight on into the next filter.
    """
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        bar = await _type(pilot, "is:a")
        assert bar.value == "is:a"  # typing alone still writes nothing
        assert bar.source == "is:aging"  # first of the `a` flags
        await pilot.press("tab")
        await pilot.pause()
        assert bar.value == "is:aging"  # ...and tab takes it
        assert bar.input.ghost == ""  # nothing left to offer in grey
        await pilot.press("tab")
        await pilot.pause()
        assert bar.value == "is:available"
        assert app.shown == ["Sinners", "Weapons"]
        await pilot.press("shift+tab")  # and back
        await pilot.pause()
        assert bar.value == "is:aging"
        await pilot.press(*" kind:movie")  # the term is finished, so typing continues
        await pilot.pause()
        assert bar.value == "is:aging kind:movie"


async def test_shift_tab_takes_the_candidate_before_the_offered_one() -> None:
    """Nothing has been taken yet, so stepping back means the one behind the offer."""
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        bar = await _type(pilot, "is:a")
        await pilot.press("shift+tab")
        await pilot.pause()
        assert bar.value == "is:early-access"  # the last `a` flag, wrapping backwards


async def test_the_preview_is_scoped_to_what_was_typed() -> None:
    """`is:a` must not walk through `dated` — the typed `a` has ruled it out already."""
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        bar = await _type(pilot, "is:a")
        assert [p.label for p in bar.picks] == ["aging", "available", "early-access"]
        assert "aging" in _hint(app) and "1/3" in _hint(app)


async def test_space_takes_the_previewed_completion() -> None:
    """Space ends the token, so it has to mean "keep what I can see"."""
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        bar = await _type(pilot, "is:u ")
        assert bar.value == "is:upcoming "
        assert app.shown == ["Dune: Part Three"]


async def test_leaving_the_bar_commits_the_preview() -> None:
    """The tail stops being painted on blur, so the filter must stop being invisible."""
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        bar = await _type(pilot, "is:u")
        app.query_one("#rows").focus()
        await pilot.pause()
        assert bar.value == "is:upcoming"
        assert app.shown == ["Dune: Part Three"]


async def test_without_implicit_accept_leaving_keeps_what_was_typed() -> None:
    """Where a field is only text, taking the offer on the way out would swallow a deliberate
    freeform value that happens to be a prefix of a known one."""

    class Form(App[None]):
        def compose(self) -> ComposeResult:
            yield SearchBar(SCHEMA, VOCAB, implicit_accept=False, id="bar")
            yield DataTable[str]()

    app = Form()
    async with app.run_test(size=(140, 24)) as pilot:
        bar = cast("SearchBar[Work]", app.query_one("#bar", SearchBar))
        bar.focus()
        await pilot.press(*"is:u")
        app.query_one(DataTable).focus()
        await pilot.pause()
        assert bar.value == "is:u"


async def test_ctrl_backspace_deletes_the_word_to_the_left() -> None:
    """Textual binds ctrl+backspace to delete_right_word; nobody means that."""
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        bar = await _type(pilot, "kind:movie genre:horror")
        await pilot.press("ctrl+backspace")
        await pilot.pause()
        assert bar.value == "kind:movie genre:"
        await pilot.press("ctrl+backspace", "ctrl+backspace")
        await pilot.pause()
        assert bar.value == "kind:"  # `:` is a word boundary, so `genre:` was two


async def test_submitting_is_announced() -> None:
    seen: list[str] = []

    class Submit(App[None]):
        def compose(self) -> ComposeResult:
            yield SearchBar(SCHEMA, VOCAB)

        def on_search_bar_submitted(self, event: SearchBar.Submitted) -> None:
            seen.append(event.source)

    app = Submit()
    async with app.run_test(size=(140, 24)) as pilot:
        app.query_one(SearchBar).focus()
        await pilot.press(*"kind:tv", "enter")
        await pilot.pause()
        assert seen == ["kind:tv"]


# --- the walk -------------------------------------------------------------------------------
async def _tab_walk(pilot: Pilot[None], start: str, presses: int) -> list[str]:
    """Tab ``presses`` times from ``start``, collecting what the bar means after each press."""
    app = pilot.app
    assert isinstance(app, Browse)
    bar = app.bar
    bar.focus()
    bar.value = start
    seen: list[str] = []
    for _ in range(presses):
        await pilot.press("tab")
        await pilot.pause()
        seen.append(bar.source)
    return seen


async def test_tab_cycles_through_the_completions() -> None:
    """Tab used to fill the first match and then stall — the list has to be walkable."""
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        seen = await _tab_walk(pilot, "is:", 4)
        assert len(set(seen)) == 4, seen
        assert all(v.startswith("is:") for v in seen)


async def test_tab_cycle_wraps_and_shift_tab_walks_back() -> None:
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        first = (await _tab_walk(pilot, "is:", 1))[0]
        total = len(suggest("is:", 3, SCHEMA, VOCAB, limit=40))
        for _ in range(total):  # all the way round
            await pilot.press("tab")
            await pilot.pause()
        assert app.bar.source == first
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.bar.source != first


async def test_typing_ends_the_walk() -> None:
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        await _tab_walk(pilot, "is:", 2)
        await pilot.press("space", *"gen")
        await pilot.pause()
        before = app.bar.value
        assert before.endswith(" gen")
        await pilot.press("tab")
        await pilot.pause()
        assert app.bar.value == f"{before}re:"  # a fresh walk on the new token


async def test_a_sole_completion_hands_off_to_the_next_stage() -> None:
    """`gen` -> `genre:` has nowhere to cycle, so it must hand off to the values.

    The field name goes in on the first tab and the offer moves straight on to what can follow
    the colon, so the second tab takes a value and the third walks to the next one.
    """
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        bar = await _type(pilot, "gen")
        await pilot.press("tab")
        await pilot.pause()
        assert bar.value == "genre:"
        offered = bar.source
        assert offered.startswith("genre:") and offered != "genre:"
        await pilot.press("tab")
        await pilot.pause()
        assert bar.value == offered
        await pilot.press("tab")
        await pilot.pause()
        assert bar.value != offered


async def test_tab_is_focus_movement_once_there_is_nothing_to_complete() -> None:
    """The bar binds tab for its walk, and the app's tab still works everywhere else."""
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        app.query_one("#rows").focus()
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.focused is app.bar.input


# --- categories and hints -------------------------------------------------------------------
async def test_category_keys_rewrite_the_query() -> None:
    """Tabs are sugar over the language: pressing one shows its syntax in the bar."""
    app = Browse(value="genre:horror")
    async with app.run_test(size=(140, 24)) as pilot:
        app.query_one("#rows").focus()
        await pilot.press("3")
        await pilot.pause()
        assert app.bar.value == "is:watched genre:horror "
        assert app.shown == ["The Long Walk"]
        assert app.bar.pinned("is", BUCKETS) == "watched"
        await pilot.press("1")
        await pilot.pause()
        assert app.bar.value == "is:available genre:horror "


async def test_the_hint_line_reports_what_the_parser_noticed() -> None:
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        await _type(pilot, "year:soon ")
        app.query_one("#rows").focus()
        await pilot.pause()
        assert "not a number" in _hint(app)


async def test_swapping_the_vocabulary_changes_what_is_offered() -> None:
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        bar = await _type(pilot, "cast:")
        assert bar.picks == ()
        bar.vocabulary = VOCAB.merged(SCHEMA.vocabulary([Work(cast=("Alan Ritchson",))]))
        await pilot.pause()
        assert [p.label for p in bar.picks] == ["Alan Ritchson"]


async def test_changes_are_announced_once_per_meaning() -> None:
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        await _type(pilot, "kind:movie")
        before = app.changes
        app.bar.value = "kind:movie"  # the same text again
        await pilot.pause()
        assert app.changes == before


# --- the pieces on their own ----------------------------------------------------------------
def test_a_field_suggester_completes_the_whole_value() -> None:
    """What a form field needs: the candidate replaces everything typed, not a token."""
    picks: tuple[Suggestion, ...] = tuple(field_suggester(SCHEMA, "director", VOCAB)("dir sin", 7))
    assert picks, "the rows all have a director"
    assert all(p.start == 0 and p.end == len("dir sin") for p in picks)
    assert all(p.insert == p.label for p in picks)  # no field: prefix, no quoting


def test_a_field_suggester_is_scoped_to_its_field() -> None:
    assert field_suggester(SCHEMA, "director", VOCAB)("", 0)
    assert tuple(field_suggester(SCHEMA, "cast", VOCAB)("", 0)) == ()


async def test_a_completing_input_works_without_a_schema() -> None:
    """The input is generic over where candidates come from."""
    words = ("apple", "apricot", "banana")

    def fruit(text: str, _caret: int) -> tuple[Suggestion, ...]:
        return tuple(Suggestion(w, w, "fruit", 0, len(text)) for w in words if w.startswith(text))

    class Fruit(App[None]):
        def compose(self) -> ComposeResult:
            yield CompletingInput(fruit)

    app = Fruit()
    async with app.run_test(size=(80, 10)) as pilot:
        field = app.query_one(CompletingInput)
        field.focus()
        await pilot.press("a", "p", "tab")
        await pilot.pause()
        assert field.value == "apple"
        await pilot.press("tab")
        await pilot.pause()
        assert field.value == "apricot"


async def test_a_cycle_steps_and_wraps() -> None:
    seen: list[str] = []

    class Pick(App[None]):
        def compose(self) -> ComposeResult:
            yield Cycle(("tv", "movie", "game"))

        def on_cycle_changed(self, event: Cycle.Changed) -> None:
            seen.append(event.value)

    app = Pick()
    async with app.run_test(size=(40, 5)) as pilot:
        app.query_one(Cycle).focus()
        await pilot.press("right", "right", "right", "left")
        await pilot.pause()
        assert seen[-4:] == ["movie", "game", "tv", "game"]
        assert re.search(r"game", str(app.query_one(Cycle).render()))


def test_an_empty_vocabulary_is_fine() -> None:
    assert suggest("cast:x", 6, SCHEMA, Vocabulary()) == ()


# --- diagnostics are drawn where they are ---------------------------------------------------
def _underlined(app: Browse) -> str:
    """The input's text as drawn with an underline: the diagnostic spans, cell for cell."""
    strip = app.bar.input.render_line(0)
    return "".join(seg.text for seg in strip if seg.style is not None and seg.style.underline)


async def _settle(pilot: Pilot[None], source: str) -> Browse:
    """Set the bar's text as a paste would, then leave it: what it marks once nobody types."""
    app = pilot.app
    assert isinstance(app, Browse)
    app.bar.value = source
    app.query_one("#rows").focus()
    await pilot.pause()
    return app


@pytest.mark.parametrize(
    ("source", "marked"),
    [
        ("nope:1 kind:movie", "nope"),
        ("kind:movie year:soon", "year:soon"),
        ("(kind:movie", "("),
        ("kind:movie)", ")"),
        ("title:O.Connor", "."),
        ("kind:movie year:>|", "year:>|"),
        ("нет:1", "нет"),
        ("نعم:x", "نعم"),
        ("漢字:1 kind:movie", "漢字"),
        ("ＤＵＮＥ:x", "ＤＵＮＥ"),
        ("🇯🇵:x", "🇯🇵"),
        ("👨‍👩‍👧:x", "👨‍👩‍👧"),
        ("é́:x", "é́"),
        ("year:— kind:movie", "year:—"),
        ("title:café title:проект", ""),
    ],
)
async def test_a_diagnostic_is_underlined_exactly_where_it_is(source: str, marked: str) -> None:
    """Whatever the script, the underline covers the characters the diagnostic names and no
    neighbour: offsets are code points, and the drawing turns them into the right cells."""
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        await _settle(pilot, source)
        assert _underlined(app) == marked


async def test_control_characters_neither_crash_nor_shift_the_marks() -> None:
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        await _settle(pilot, "a\x00b:x nope:1")
        assert "nope" in _underlined(app)
        assert app.bar.diagnostics[-1].text == "nope"


async def test_what_is_still_being_typed_is_not_marked() -> None:
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        await _type(pilot, "(kind:movie")
        assert _underlined(app) == "", "every ( is unclosed until its ) is typed"
        assert app.bar.diagnostics == ()
        app.query_one("#rows").focus()
        await pilot.pause()
        assert _underlined(app) == "(", "left open, it is marked"


async def test_the_hint_names_the_diagnostic_under_the_caret() -> None:
    app = Browse()
    async with app.run_test(size=(140, 24)) as pilot:
        await _settle(pilot, "year:soon nope:1")
        app.bar.focus()
        await pilot.pause()  # focusing puts the caret at the end
        app.bar.input.cursor_position = 2
        await pilot.pause()
        assert "not a number" in _hint(app) and "not a field" not in _hint(app)
        app.bar.input.cursor_position = 12
        await pilot.pause()
        assert "nope: not a field" in _hint(app)


# --- a query longer than the bar -------------------------------------------------------------
def _drawn(app: Browse) -> str:
    return "".join(seg.text for seg in app.bar.input.render_line(0))


def _word_at_caret(app: Browse) -> str:
    value, caret = app.bar.value, app.bar.input.cursor_position
    start = value.rfind(" ", 0, caret) + 1
    end = value.find(" ", caret)
    return value[start : end if end >= 0 else len(value)]


@pytest.mark.parametrize(
    "words",
    [
        [f"w{i:02d}" for i in range(40)],  # 160 cells in a 40-cell terminal
        [f"漢{i:02d}" for i in range(40)],  # two cells a character: the scroll counts cells
        [f"👨‍👩‍👧{i:02d}" for i in range(20)],  # several code points a glyph
    ],
)
async def test_a_long_query_scrolls_to_keep_the_caret_in_view(words: list[str]) -> None:
    """Typing past the edge follows the caret; home, end and the arrows take the view along,
    so every part of a long query can be seen and edited, not just its first screenful."""
    app = Browse()
    async with app.run_test(size=(40, 10)) as pilot:
        app.bar.focus()
        await pilot.pause()
        text = " ".join(words)
        if "\u200d" in text:  # a joiner is not a key Textual inserts; it arrives in a paste
            app.bar.input.insert_text_at_cursor(text)
        else:
            await pilot.press(*text)
        await pilot.pause()
        assert words[-1] in _drawn(app) and words[0] not in _drawn(app), "the end, as typed"
        await pilot.press("home")
        await pilot.pause()
        assert words[0] in _drawn(app) and words[-1] not in _drawn(app)
        for _ in range(len(" ".join(words)) // 2):
            await pilot.press("right")
        await pilot.pause()
        middle = _word_at_caret(app)
        assert middle in _drawn(app), f"the caret's word {middle!r} is on screen"
        assert words[0] not in _drawn(app) and words[-1] not in _drawn(app)
        await pilot.press("end")
        await pilot.pause()
        assert words[-1] in _drawn(app)


async def test_a_mark_scrolled_out_of_view_comes_back_with_it() -> None:
    app = Browse()
    async with app.run_test(size=(40, 10)) as pilot:
        await _settle(pilot, "nope:1 " + " ".join(f"w{i:02d}" for i in range(30)))
        app.bar.focus()
        await pilot.pause()  # the caret goes to the end: the mark is off screen
        assert "nope" not in _drawn(app)
        await pilot.press("home")
        await pilot.pause()
        assert _underlined(app) == "nope"


@pytest.mark.parametrize(
    "words",
    [
        [f"w{i:02d}" for i in range(40)],
        [f"漢{i:02d}" for i in range(40)],
        [f"👨‍👩‍👧{i:02d}" for i in range(20)],
        [f"🇯🇵{i:02d}" for i in range(20)],
        [f"é{i:02d}" for i in range(40)],
    ],
)
async def test_a_pasted_query_longer_than_the_bar_shows_its_end(words: list[str]) -> None:
    """Textual scrolls to the caret before layout widens the field for a paste, so the view
    stayed at the start with the caret off screen; the input brings it back after layout."""
    app = Browse()
    async with app.run_test(size=(40, 10)) as pilot:
        app.bar.focus()
        await pilot.pause()
        app.bar.input.post_message(events.Paste(" ".join(words)))
        await pilot.pause()
        await pilot.pause()
        assert words[-1] in _drawn(app) and words[0] not in _drawn(app)


@pytest.mark.parametrize("label", ["zz[/x]", "[@click=app.quit]k", "[link=https://e.x]l[/]", "[b"])
def test_a_label_is_shown_as_it_is_never_as_markup(label: str) -> None:
    """Completions are the data's own words (a JSON key a command printed, a directory name):
    `[/x]` in one raised MarkupError and closed the app, `[link=...]` made a live link."""
    from textual_catsearch.complete import Suggestion
    from textual_catsearch.widgets.completing import completion_hint
    from textual_catsearch.widgets.cycle import Cycle

    picks = [Suggestion(label, label, "key", 0, 1), Suggestion("ok", "ok", "key", 0, 1)]
    for active in (0, 1):
        hint = completion_hint(picks, active)
        assert label in hint.plain
        assert not any(span.style and "link" in str(span.style) for span in hint.spans)
    assert label in Cycle([label]).render().plain
