"""The inputs the golden fixtures hold answers for.

Three sources, so the spec covers what the Python suite already pins down, what is known to be
awkward, and what nobody thought of:

* every string literal in the Python test suite (what the suite queries, by example);
* a curated list of edge cases: scripts, astral characters, invisible characters, digits from
  other scripts, huge numbers, quoting and bracket corner cases;
* a seeded random walk over the grammar of each schema, deterministic so regenerating the
  fixtures changes nothing unless the reference did.
"""

from __future__ import annotations

import ast
import random
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from conformance.schemas import SchemaName, schema

__all__ = ["AWKWARD", "CURATED", "extracted", "generated", "random_source"]

_TESTS = Path(__file__).resolve().parents[1]
_TEST_FILES: Final = (
    "test_query.py",
    "test_props.py",
    "test_units.py",
    "test_dynamic.py",
    "test_schema.py",
    "test_widgets.py",
)

AWKWARD: Final[tuple[str, ...]] = (
    "нет", "скоро", "عربي", "漢字", "薬屋", "ヱヴァ", "한국어", "🇯🇵", "👨‍👩‍👧", "😀", "𝔘𝔫𝔦",
    "x́", "é́", "\x00", "a\x00b", "—", "：", "（", "）", "“", "”", "‮",
    "​", "　", "Ｄ", "ß", "İ", "ﬁ", "Σ", "ς", "ẞ", "﻿", "\x1c", "\x85",
    " ", "٣", "１２", "𝟙𝟚", "\ud800", "Ꭰ", "ꭰ", "Å", "Å", "ǅ", "ŉ",
)  # fmt: skip

CURATED: Final[tuple[str, ...]] = (
    "",
    " ",
    'reacher kind:tv cast:"Alan Ritchson" year:2026',
    '"the odyssey" -tag:comedy is:upcoming',
    "(kind:tv OR kind:movie) -(tag:horror year:<2000)",
    "kind:tv OR kind:movie -is:watched",
    "a OR ()",
    "(-(()))",
    "((((((((((((((((((((((((((((((((((a))))))))))))))))))))))))))))))))))",
    "-((a b) OR c)",
    "OR",
    "a OR",
    "| a",
    '"OR"',
    "title:(2021)",
    "(kind:mo)",
    "tag:none",
    'tag:"none"',
    "tag:NONE,horror",
    "-tag:none",
    "is:none",
    "on:netflix@us",
    "on:@de",
    "platform:none",
    "sequel-of.year:<2022",
    "sequel-to.name:dune",
    "prequel-of.sequel-of.kind:movie",
    "nope.year:2020",
    "sequel-of:x",
    "author:'Ursula Le Guin'",
    "title:\"The author:'Le Guin' and book\"",
    "Don't Look Up",
    "'71",
    'name:"The ""Burbs"',
    '"unclosed',
    'cast:"Smith, Jo',
    "cast:O.Connor",
    'cast:"O.Connor"',
    "cast:a,,b,",
    "kind:",
    "kind: tv",
    "year:soon",
    "year:2020..2026",
    "year:..2026",
    "year:2020..",
    "year:..",
    "year:>=2026",
    "year:<=2026",
    "year:>2020",
    "year:<2030",
    "year:>",
    "year:1_000",
    "year:_1",
    "year:1__0",
    "year:+2021",
    "year:-5",
    "year:٢٠٢١",
    "year:２０２１",
    "year:𝟚𝟘𝟚𝟙",
    "year:9007199254740993",
    "year:>9007199254740993",
    "year:" + "9" * 400,
    "year:" + "9" * 4301,
    "season:none,3",
    "kind:film",
    "kind:SERIES",
    "Kind:TV",
    "ACTOR:zendaya",
    "is:unknownflag",
    "is:early-access",
    "-30-",
    "!a",
    "!kind:tv",
    "-",
    "--a",
    "a,b",
    "name:a,b",
    "name:kind:tv",
    "Andor: Season 2",
    ":x",
    "x:",
    "::",
    "a)",
    "(a",
    "((a",
    "a))",
    "(a))",
    ")",
    "Mr. Robot",
    "Wall-E",
    "#Alive",
    "cafe",
    "ＤＵＮＥ",
    "STRASSE",
    "\tkind:tv\n",
    "a　b",
    "a b",
    "a﻿b",
    "a\x1cb",
    "took:>5m",
    "took:>=5m",
    "took:<1m",
    "took:1m..1h",
    "took:2h",
    "took:5m..1m",
    "took:" + "9" * 400,
    "took:1.5h",
    "took:٥m",
    "status:500",
    "status:500,200",
    "userId:7",
    "http.status:503",
    "Level:3",
    "level:3",
    "parent.level:1",
    "parent.status:100",
    "nope:x",
    "re:(a",
    're:"(a)"',
    "re:a|b",
    "kv:status=500 kv:path=/api/users",
    "kv:status=500,path=/health",
    "Größe:groß",
    "text:ünïcode",
)


def extracted() -> tuple[str, ...]:
    """Every string literal in the Python tests that is not a docstring, deduplicated."""
    found: dict[str, None] = {}
    for name in _TEST_FILES:
        tree = ast.parse((_TESTS / name).read_text("utf-8"))
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef | ast.AsyncFunctionDef)
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
        }
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings
                and len(node.value) <= 160
            ):
                found.setdefault(node.value, None)
    return tuple(found)


# --- the random walk -------------------------------------------------------------------------
_WORDS: Final = (
    "reacher", "dune", "Dune", "café", "cafe", "the", "odyssey", "Part", "Two", "zendaya",
    "Chalamet", "horror", "Sci-Fi", "body horror", "desert", "steam", "netflix", "us", "DE",
    "OR", "or", "none", "NONE", "500", "/api", "level", "a", "b", "x", "Straße", "Брат", "薬屋",
)  # fmt: skip
_PUNCT: Final = ("", "", "", ",", ".", ":", "-", "!", "(", ")", "'", '"', "@", "=", "|", "#", "_")


def _value(rng: random.Random) -> str:
    match rng.randrange(9):
        case 0:
            return str(rng.randrange(-5, 3000))
        case 1:
            return f"{rng.randrange(0, 3000)}..{rng.randrange(0, 3000)}"
        case 2:
            return f"{rng.choice(['>', '<', '>=', '<='])}{rng.randrange(0, 3000)}"
        case 3:
            return f"{rng.randrange(0, 90)}{rng.choice(['', 's', 'm', 'h', 'x'])}"
        case 4:
            return rng.choice(AWKWARD)
        case 5:
            return rng.choice(_WORDS) + rng.choice(_PUNCT) + rng.choice(("", *_WORDS))
        case _:
            return rng.choice(_WORDS)


def _quoted(rng: random.Random, text: str) -> str:
    match rng.randrange(6):
        case 0:
            return '"' + text.replace('"', '""') + '"'
        case 1:
            return "'" + text + "'"
        case 2:
            return '"' + text  # left open
        case _:
            return text


def _key(rng: random.Random, name: SchemaName) -> str:
    s = schema(name)
    pool = [*s.fields, *(a for f in s.fields.values() for a in f.aliases), "nope", "x"]
    key = rng.choice(pool)
    if s.relations and rng.randrange(4) == 0:
        key = f"{rng.choice([*s.relations])}.{key}"
    if name == "dynamic" and rng.randrange(3) == 0:
        key = rng.choice(["status", "userId", "http.status", "path", "Größe", "a.b"])
    return key.upper() if rng.randrange(12) == 0 else key


def _clause(rng: random.Random, name: SchemaName) -> str:
    sign = rng.choice(("", "", "", "-", "!"))
    if rng.randrange(3) == 0:
        return sign + _quoted(rng, _value(rng))
    values = ",".join(_quoted(rng, _value(rng)) for _ in range(rng.choice((1, 1, 1, 2, 3))))
    return f"{sign}{_key(rng, name)}:{values}"


def _expression(rng: random.Random, name: SchemaName, depth: int) -> str:
    parts: list[str] = []
    for _ in range(rng.randrange(0, 4)):
        match rng.randrange(6) if depth > 0 else 9:
            case 0:
                parts.append(rng.choice(("", "-")) + "(" + _expression(rng, name, depth - 1) + ")")
            case 1:
                parts.append(
                    " OR ".join(_expression(rng, name, depth - 1) or "a" for _ in range(2))
                )
            case _:
                parts.append(_clause(rng, name))
    return rng.choice((" ", " ", "  ", "\t")).join(parts)


def random_source(rng: random.Random, name: SchemaName) -> str:
    """One query, built from the grammar's pieces and then perhaps damaged."""
    text = _expression(rng, name, 2)
    if text and rng.randrange(5) == 0:  # damage: what a half-typed or mis-edited query is
        at = rng.randrange(len(text) + 1)
        text = text[:at] + rng.choice(("(", ")", '"', ",", ":", " OR", "-", *AWKWARD)) + text[at:]
    if text and rng.randrange(6) == 0:
        text = text[: rng.randrange(len(text) + 1)]
    return text


def generated(name: SchemaName, n: int, seed: int) -> Iterator[str]:
    rng = random.Random(f"{name}:{seed}")
    for _ in range(n):
        yield random_source(rng, name)


if __name__ == "__main__":
    for line in generated("catalog", int(sys.argv[1]) if len(sys.argv) > 1 else 10, 0):
        print(repr(line))
