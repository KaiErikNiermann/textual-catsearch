"""The schemas the shared spec is written against, over the rows in ``spec/rows``.

``js/test/harness/schemas.ts`` declares the same three, over the same JSON. They are kept
deliberately plain (every accessor reads a key; every test is a fold or an equality) so the two
declarations cannot disagree about anything but the library under test.

* ``catalog``: every field kind, aliases, a normaliser, relations (``tests/catalog.py``).
* ``units``: number fields with a unit parser (``tests/test_units.py``).
* ``dynamic``: undeclared keys, dotted keys, a ``check``, an ``every`` field, a relation.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

from catalog import SCHEMA as CATALOG
from catalog import Work
from test_units import SCHEMA as UNITS
from test_units import Job
from textual_catsearch import (
    CustomField,
    NumberField,
    Relation,
    Schema,
    TextField,
    VocabEntry,
    Vocabulary,
)
from textual_catsearch.text import fold

__all__ = ["SPEC", "SchemaName", "rows", "schema", "vocabulary"]

SPEC = Path(__file__).resolve().parents[2] / "spec"

type SchemaName = Literal["catalog", "units", "dynamic"]


@dataclass(frozen=True, eq=False)
class Line:
    text: str
    fields: dict[str, str]
    level: int = 0
    parent: Line | None = None


def _kv(key: str) -> CustomField[Line]:
    def test(row: Line, value: str) -> bool:
        have = row.fields.get(key)
        return have is not None and fold(have) == fold(value)

    return CustomField(key, test, empty=lambda row: key not in row.fields, detail="a key")


def _dynamic(key: str) -> CustomField[Line] | None:
    return None if key == "nope" else _kv(key)


def _pair(row: Line, value: str) -> bool:
    key, sep, want = value.partition("=")
    return bool(sep) and row.fields.get(key) == want


def _balanced(value: str) -> str | None:
    return None if value.count("(") == value.count(")") else "unbalanced brackets"


DYNAMIC: Schema[Line] = Schema(
    [
        TextField("text", lambda r: r.text),
        NumberField("level", lambda r: r.level),
        CustomField("re", lambda r, v: fold(v) in fold(r.text), check=_balanced, unquoted="()|*+?"),
        CustomField("kv", _pair, every=True, unquoted="=/"),
    ],
    bare="text",
    relations=[Relation("parent", lambda r: () if r.parent is None else (r.parent,))],
    dynamic=_dynamic,
)


def _work(data: dict[str, Any]) -> Work:
    return Work(
        title=data.get("title", "Reacher: Season 3"),
        aliases=tuple(data.get("aliases", ())),
        kind=data.get("kind", "tv"),
        years=tuple(data.get("years", ())),
        season=data.get("season"),
        genres=tuple(data.get("genres", ())),
        themes=tuple(data.get("themes", ())),
        cast=tuple(data.get("cast", ())),
        director=tuple(data.get("director", ())),
        state=data.get("state", "want"),
        bucket=data.get("bucket", "available"),
        freshness=data.get("freshness", "fresh"),
        blockers=tuple(data.get("blockers", ())),
        early_access=data.get("early_access", False),
        platforms=tuple((s, tuple(m)) for s, m in data.get("platforms", ())),
        sequel_of=tuple(_work(w) for w in data.get("sequel_of", ())),
        prequel_of=tuple(_work(w) for w in data.get("prequel_of", ())),
    )


def _job(data: dict[str, Any]) -> Job:
    return Job(name=data["name"], took=data["took"], year=data.get("year", 2020))


def _line(data: dict[str, Any]) -> Line:
    parent = data.get("parent")
    return Line(
        text=data["text"],
        fields=dict(data["fields"]),
        level=data.get("level", 0),
        parent=None if parent is None else _line(parent),
    )


def schema(name: SchemaName) -> Schema[Any]:
    match name:
        case "catalog":
            return CATALOG
        case "units":
            return UNITS
        case "dynamic":
            return DYNAMIC


@cache
def rows(name: SchemaName) -> tuple[Any, ...]:
    data: list[dict[str, Any]] = json.loads((SPEC / "rows" / f"{name}.json").read_text("utf-8"))
    match name:
        case "catalog":
            return tuple(_work(d) for d in data)
        case "units":
            return tuple(_job(d) for d in data)
        case "dynamic":
            return tuple(_line(d) for d in data)


@cache
def vocabulary(name: SchemaName) -> Vocabulary:
    """The rows' vocabulary; for ``dynamic``, with the data's keys counted per row."""
    found = schema(name).vocabulary(rows(name))
    if name != "dynamic":
        return found
    keys: Counter[str] = Counter()
    for row in rows(name):
        keys.update(list(row.fields))
    return Vocabulary(found.entries, keys=tuple(VocabEntry(k, n) for k, n in keys.items()))
