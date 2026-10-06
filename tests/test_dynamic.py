"""A dynamic schema: keys it does not declare are asked of `dynamic`, as written (case, dots and
all), after every declared field and path; completed from the data's keys; never shadowing a
declared name."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from textual_catsearch import (
    CustomField,
    NumberField,
    Relation,
    Schema,
    TextField,
    VocabEntry,
    Vocabulary,
    parse,
    render,
    suggest,
)
from textual_catsearch.query import Fault
from textual_catsearch.schema import DYNAMIC_KEYS


@dataclass(frozen=True)
class Line:
    text: str
    fields: dict[str, str]
    level: int = 0
    parent: Line | None = None


def _kv(key: str) -> CustomField[Line]:
    def test(row: Line, value: str) -> bool:
        have = row.fields.get(key)
        return have is not None and (
            value.lstrip("<>=") == have
            if value[:1] not in "<>"
            else float(have) >= float(value[2:])
        )

    return CustomField(key, test, empty=lambda row: key not in row.fields, detail="a key")


ASKED: list[str] = []


def _dynamic(key: str) -> CustomField[Line] | None:
    ASKED.append(key)
    return None if key == "nope" else _kv(key)


SCHEMA: Schema[Line] = Schema(
    [
        TextField("text", lambda r: r.text),
        NumberField("level", lambda r: r.level),
    ],
    bare="text",
    relations=[Relation("parent", lambda r: () if r.parent is None else (r.parent,))],
    dynamic=_dynamic,
)
ROWS = [
    Line("a", {"status": "500", "userId": "7", "http.status": "503"}),
    Line("b", {"status": "200", "level": "9"}, level=3),
    Line("c", {}),
]


def kept(source: str) -> list[str]:
    return [r.text for r in parse(source, SCHEMA).filter(ROWS)]


def test_an_undeclared_key_is_a_field_of_its_own() -> None:
    query = parse("status:500", SCHEMA)
    assert not query.diagnostics
    assert kept("status:500") == ["a"]
    assert kept("status:500,200") == ["a", "b"], "a comma list of alternatives, as any field"
    assert kept("-status:500") == ["b", "c"]
    assert kept("status:none") == ["c"]


def test_a_key_keeps_its_case_and_its_dots() -> None:
    assert kept("userId:7") == ["a"]
    assert kept("http.status:503") == ["a"], "a dotted key that is no path is asked whole"
    assert (
        render(parse("userId:7 http.status:503", SCHEMA).expr, SCHEMA) == "userId:7 http.status:503"
    )


def test_a_declared_field_or_path_always_wins() -> None:
    ASKED.clear()
    assert kept("level:3") == ["b"], "the declared level, not the data's key"
    assert kept("parent.level:3") == [], "a declared path"
    assert "level" not in ASKED and "Level" not in ASKED
    assert kept("Level:3") == ["b"], "declared names are read in any case"


def test_a_key_dynamic_declines_is_read_as_text_as_any_unknown_field() -> None:
    query = parse("nope:x", SCHEMA)
    assert [d.fault for d in query.diagnostics] == [Fault.UNKNOWN_FIELD]


def test_a_key_is_asked_of_dynamic_once() -> None:
    asked: list[str] = []

    def counting(key: str) -> CustomField[Line] | None:
        asked.append(key)
        return _kv(key)

    fresh: Schema[Line] = Schema(
        [TextField("text", lambda r: r.text)], bare="text", dynamic=counting
    )
    parse("status:500 status:200 -status:1", fresh).filter(ROWS)
    parse("status:200", fresh).filter(ROWS)
    assert asked == ["status"]


def test_the_keys_kept_are_bounded() -> None:
    """Every key typed is asked about, so a table kept for the schema's life only ever grew —
    in a long-lived bar, by every key anyone edited. The oldest are forgotten and asked again."""
    asked: list[str] = []

    def declining(key: str) -> None:
        asked.append(key)

    fresh: Schema[Line] = Schema(
        [TextField("text", lambda r: r.text)], bare="text", dynamic=declining
    )
    for i in range(DYNAMIC_KEYS + 1):
        parse(f"k{i}:x", fresh)
    parse(f"k{DYNAMIC_KEYS}:x", fresh)  # the newest is still kept
    assert len(asked) == DYNAMIC_KEYS + 1
    parse("k0:x", fresh)  # the oldest was let go
    assert asked[-1] == "k0"


def test_a_field_dynamic_makes_must_carry_the_key_as_its_name() -> None:
    schema: Schema[Line] = Schema(
        [TextField("text", lambda r: r.text)],
        bare="text",
        dynamic=lambda key: _kv(key.lower()),
    )
    with pytest.raises(ValueError, match="not the key"):
        parse("Status:1", schema)


VOCAB = Vocabulary(
    keys=(
        VocabEntry("status", 9),
        VocabEntry("http.status", 4),
        VocabEntry("userId", 2),
        VocabEntry("level", 5),
    )
)


def _labels(source: str) -> list[str]:
    return [s.label for s in suggest(source, len(source), SCHEMA, VOCAB)]


def test_keys_complete_after_the_declared_names() -> None:
    assert _labels("le") == ["level:"], "the declared field, not the data's key again"
    assert _labels("st") == ["status:"]
    assert _labels("u") == ["userId:"]
    assert _labels("http.s") == ["http.status:"], "a dotted key completes whole"
    assert _labels("-st") == ["status:"]
    assert [s.insert for s in suggest("-st", 3, SCHEMA, VOCAB)] == ["-status:"]


def test_without_dynamic_nothing_changes() -> None:
    plain: Schema[Line] = Schema([TextField("text", lambda r: r.text)], bare="text")
    assert [d.fault for d in parse("status:500", plain).diagnostics] == [Fault.UNKNOWN_FIELD]
    assert [s.label for s in suggest("st", 2, plain, VOCAB)] == []
