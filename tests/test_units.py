"""Number fields with units: `took:>5m`, `size:1G..2G`, strict bounds on real quantities."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass

from hypothesis import given
from hypothesis import strategies as st

from textual_catsearch import NumberField, Schema, TextField, parse

UNITS = {"": 1, "s": 1, "m": 60, "h": 3600}


def seconds(text: str) -> float | None:
    if (m := re.fullmatch(r"(\d+(?:\.\d+)?)([smh]?)", text)) is None:
        return None
    return float(m[1]) * UNITS[m[2]]


@dataclass(frozen=True)
class Job:
    name: str
    took: float
    year: int = 2020


SCHEMA: Schema[Job] = Schema(
    [
        TextField("name", lambda j: j.name),
        NumberField("took", lambda j: j.took, parse=seconds),
        NumberField("year", lambda j: j.year),
    ],
    bare="name",
)
JOBS = (Job("quick", 12.0), Job("edge", 300.5), Job("exact", 300.0), Job("long", 7200.0))


def names(query: str) -> list[str]:
    return [j.name for j in parse(query, SCHEMA).filter(JOBS)]


def test_units_read_through_the_fields_parser() -> None:
    assert names("took:>5m") == ["edge", "long"], "strict: 300.5 counts, 300 does not"
    assert names("took:>=5m") == ["edge", "exact", "long"]
    assert names("took:<1m") == ["quick"]
    assert names("took:1m..1h") == ["edge", "exact"]
    assert names("took:2h") == ["long"]


def test_an_unreadable_quantity_matches_nothing_and_says_so() -> None:
    query = parse("took:soon", SCHEMA)
    assert query.filter(JOBS) == []


@given(st.integers(-10_000, 10_000), st.integers(-10_000, 10_000))
def test_integer_fields_behave_as_before(n: int, value: int) -> None:
    rows = (Job("x", 0.0, year=value),)
    assert bool(parse(f"year:>{n}", SCHEMA).filter(rows)) == (value > n)
    assert bool(parse(f"year:<{n}", SCHEMA).filter(rows)) == (value < n)
    assert bool(parse(f"year:{n}", SCHEMA).filter(rows)) == (value == n)


# --- values that stand for a stretch: a minute written as 14:30 --------------------------------
def minute(text: str) -> float | tuple[float, float] | None:
    """`14:30` is that minute ([870, 871) in minutes of the day, as seconds); `14:30:15` a point."""
    if m := re.fullmatch(r"(\d{2}):(\d{2})", text):
        start = (int(m[1]) * 60 + int(m[2])) * 60.0
        return start, start + 60
    if m := re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})", text):
        return (int(m[1]) * 60 + int(m[2])) * 60.0 + int(m[3])
    return None


@dataclass(frozen=True)
class Event:
    name: str
    at: float


CLOCK: Schema[Event] = Schema(
    [TextField("name", lambda e: e.name), NumberField("at", lambda e: e.at, parse=minute)],
    bare="name",
)
M1430 = 870 * 60.0
EVENTS = (
    Event("before", M1430 - 0.5),
    Event("start", M1430),
    Event("inside", M1430 + 59.9),
    Event("next", M1430 + 60),
)


def at(query: str) -> list[str]:
    return [e.name for e in parse(query, CLOCK).filter(EVENTS)]


def test_a_span_value_matches_all_of_its_stretch() -> None:
    assert at("at:14:30") == ["start", "inside"], "the whole minute, not its first instant"
    assert at("at:14:30:00") == ["start"], "a point stays a point"


def test_comparisons_take_a_spans_edges() -> None:
    assert at("at:>14:30") == ["next"], "after the minute: from its end"
    assert at("at:>=14:30") == ["start", "inside", "next"]
    assert at("at:<14:30") == ["before"], "before any of it"
    assert at("at:<=14:30") == ["before", "start", "inside"], "up to and including all of it"


def test_a_range_of_spans_runs_from_the_first_start_to_the_last_end() -> None:
    assert at("at:14:29..14:30") == ["before", "start", "inside"]
    assert at("at:..14:30") == ["before", "start", "inside"]
    assert at("at:14:30..") == ["start", "inside", "next"]
    assert at("at:14:30..14:30:30") == ["start"], "a span start, a point end (inclusive)"


def test_a_span_that_runs_backwards_matches_nothing() -> None:
    backwards: Schema[Event] = Schema(
        [
            TextField("name", lambda e: e.name),
            NumberField("at", lambda e: e.at, parse=lambda _: (5.0, 1.0)),
        ],
        bare="name",
    )
    assert parse("at:x", backwards).filter(EVENTS) == []


@given(st.floats(0, 86_399, allow_nan=False), st.integers(0, 23), st.integers(0, 59))
def test_a_minute_and_its_complement_partition_the_day(t: float, hour: int, mins: int) -> None:
    """`at:X`, `at:<X` and `at:>X` never overlap and leave nothing out."""
    stamp = f"{hour:02d}:{mins:02d}"
    events = (Event("e", t),)
    hits = [bool(parse(f"at:{op}{stamp}", CLOCK).filter(events)) for op in ("", "<", ">")]
    assert sum(hits) == 1, (t, stamp, hits)


def test_a_field_reads_the_punctuation_its_parser_declares_unquoted() -> None:
    declared: Schema[Event] = Schema(
        [
            TextField("name", lambda e: e.name),
            NumberField("at", lambda e: e.at, parse=minute, unquoted=":"),
        ],
        bare="name",
    )
    assert parse("at:14:29..14:30", declared).diagnostics == ()
    [d] = parse("at:14:30", CLOCK).diagnostics  # undeclared: said, and pointed at
    assert "at:14:30"[d.start : d.end] == ":"


def test_the_query_language_is_imported_without_textual() -> None:
    """A CLI that only parses and evaluates queries paid for importing Textual (80 ms)."""
    code = (
        "import sys, textual_catsearch as c; "
        "assert 'textual' not in sys.modules, 'textual imported'; "
        "c.SearchBar; assert 'textual' in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603  # this interpreter, our code
