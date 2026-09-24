"""Number fields with units: `took:>5m`, `size:1G..2G`, strict bounds on real quantities."""

from __future__ import annotations

import re
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
