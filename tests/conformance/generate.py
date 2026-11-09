"""Write the golden fixtures: every corpus case with the Python reference's answer.

Run from ``tests/`` as ``poetry run python -m conformance.generate``. Each fixture file is
JSON Lines, one ``{"case": ..., "expect": ...}`` per line, so a change in behaviour diffs as
the lines it changed. ``test_conformance`` regenerates in memory and fails when the files are
stale, so the spec cannot drift from the reference unnoticed.
"""

from __future__ import annotations

import json
import random
import sys
import unicodedata
from collections.abc import Iterator, Mapping
from typing import Any, Final

from catalog import BUCKETS
from conformance.corpus import AWKWARD, CURATED, extracted, generated
from conformance.ops import encode_expr, run
from conformance.schemas import SPEC, SchemaName, schema
from textual_catsearch import Term, parse

__all__ = ["FIXTURES", "META", "fixtures", "render_file"]

FIXTURES: Final = SPEC / "fixtures"
META: Final = FIXTURES / "meta.json"

type Case = dict[str, Any]

_SCHEMAS: Final[tuple[SchemaName, ...]] = ("catalog", "units", "dynamic")
_GENERATED: Final = 250
_SEED: Final = 0


def _cursors(source: str) -> tuple[int, ...]:
    return tuple(dict.fromkeys((0, len(source) // 2, len(source))))


def _sources(name: SchemaName) -> tuple[str, ...]:
    pool = (*CURATED, *extracted(), *generated(name, _GENERATED, _SEED))
    return tuple(dict.fromkeys(pool))


def _query_cases(name: SchemaName) -> Iterator[tuple[str, Case]]:
    for source in _sources(name):
        yield "parse", {"op": "parse", "schema": name, "source": source}
        if ":" in source:  # the flag only changes what an empty `field:` value means
            yield "parse", {"op": "parse", "schema": name, "source": source, "emptyAsText": True}
        yield "match", {"op": "match", "schema": name, "source": source}
        for cursor in _cursors(source):
            yield "suggest", {"op": "suggest", "schema": name, "source": source, "cursor": cursor}
        if name == "catalog":
            yield "lex", {"op": "lex", "source": source}
            yield "open_groups", {"op": "open_groups", "source": source}


def _transform_cases() -> Iterator[tuple[str, Case]]:
    pin = encode_expr(Term("is", ("watched",)))
    kind = encode_expr(Term("kind", ("movie",)))
    for source in (*CURATED[:40], *generated("catalog", 80, 1)):
        base = {"schema": "catalog", "source": source}
        yield "transform", {"op": "pinned", **base, "field": "is", "among": list(BUCKETS)}
        yield "transform", {"op": "pinned", **base, "field": "kind"}
        yield "transform", {"op": "with_term", **base, "term": pin, "among": list(BUCKETS)}
        yield "transform", {"op": "with_term", **base, "term": kind}
        yield "transform", {"op": "without", **base, "field": "is", "among": list(BUCKETS)}
        yield "transform", {"op": "without", **base, "field": "kind"}


def _value_cases() -> Iterator[tuple[str, Case]]:
    values = (*AWKWARD, "", "none", "None", "OR", "|", "-30-", "!x", "a b", "a,b", 'say "hi"')
    values += ("O.Connor", "netflix@us", ">=5", "1..2", "plain", "snake_case", "kebab-case")
    for value in values:
        for extra in ("", "<>=.", "@", "()|*+?"):
            yield "quote", {"op": "quote", "value": value, "extra": extra}
    for name in _SCHEMAS:
        yield "vocabulary", {"op": "vocabulary", "schema": name}
        for field in (*schema(name).fields, "status", "nope"):
            yield "vocabulary", {"op": "completions", "schema": name, "field": field}
            for needle in ("", "d", "Dun", "sci", "zz", "é", "ho", "5", "a"):
                yield "rank", {"op": "rank", "schema": name, "field": field, "needle": needle}
        yield "suggest", {"op": "suggest", "schema": name, "source": "", "cursor": 0, "limit": 3}
        yield (
            "suggest",
            {
                "op": "suggest",
                "schema": name,
                "source": "s",
                "cursor": 1,
                "fields": ["season", "state"],
            },
        )
        yield (
            "suggest",
            {"op": "suggest", "schema": name, "source": "k", "cursor": 1, "vocab": False},
        )


def _text_cases() -> Iterator[tuple[str, Case]]:
    rng = random.Random(_SEED)
    words = (*AWKWARD, "Café", "CAFE", "Straße", "İstanbul", "ﬁle", "Ｄｕｎｅ", "é", "Ǆ")
    for _ in range(300):
        text = "".join(rng.choice(words) for _ in range(rng.randrange(1, 5)))
        yield "fold", {"op": "fold", "text": text}
        yield "fold", {"op": "word_prefixed", "value": text, "needle": rng.choice(words)}
    blocks = (
        *((s, s + 0x1000) for s in range(0, 0x40000, 0x1000)),
        *((s, s + 0x10000) for s in range(0x40000, 0x110000, 0x10000)),
    )
    for start, end in blocks:
        yield (
            "fold",
            {
                "op": "fold_block",
                "start": start,
                "end": end,
                "unassigned": _unassigned(start, end),
            },
        )


def _unassigned(start: int, end: int) -> list[list[int]]:
    """Inclusive ranges of code points this interpreter's Unicode has not assigned."""
    out: list[list[int]] = []
    for cp in range(start, end):
        if unicodedata.category(chr(cp)) != "Cn":
            continue
        if out and out[-1][1] == cp - 1:
            out[-1][1] = cp
        else:
            out.append([cp, cp])
    return out


def _render_cases() -> Iterator[tuple[str, Case]]:
    """Trees `parse` produced, rendered on their own: the renderer's half of the round trip."""
    for name in _SCHEMAS:
        for source in generated(name, 120, 2):
            expr = encode_expr(parse(source, schema(name)).expr)
            yield "render", {"op": "render", "schema": name, "expr": expr}


def fixtures() -> dict[str, list[Mapping[str, Any]]]:
    """Every fixture file's records, keyed by file stem."""
    out: dict[str, list[Mapping[str, Any]]] = {}
    streams = (
        *(_query_cases(name) for name in _SCHEMAS),
        _transform_cases(),
        _value_cases(),
        _text_cases(),
        _render_cases(),
    )
    for stream in streams:
        for stem, case in stream:
            out.setdefault(stem, []).append({"case": case, "expect": run(case)})
    return out


def render_file(records: list[Mapping[str, Any]]) -> str:
    # ASCII-only: a lone surrogate in a case is valid JSON escaped and unencodable raw.
    return "".join(json.dumps(r, ensure_ascii=True, sort_keys=True) + "\n" for r in records)


def meta() -> str:
    return json.dumps(
        {"unicode": unicodedata.unidata_version, "python": sys.version.split()[0]}, indent=2
    )


if __name__ == "__main__":
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for stale in FIXTURES.glob("*.jsonl"):
        stale.unlink()
    for stem, records in fixtures().items():
        (FIXTURES / f"{stem}.jsonl").write_text(render_file(records), "utf-8")
    META.write_text(meta() + "\n", "utf-8")
