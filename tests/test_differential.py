"""Differential: the TypeScript port and this package, asked the same generated cases.

The golden fixtures pin the answers to a fixed corpus; this pins the answers to whatever
Hypothesis thinks of. Every case goes to a running ``js/test/harness/oracle.ts`` and to
``conformance.ops.run``, and the two JSON answers must be equal. A disagreement shrinks to the
smallest case that shows it.

``CATSEARCH_DIFF_EXAMPLES`` raises the budget per test (default 200) for a long fuzzing run.
Without ``node`` the tests skip, unless ``CATSEARCH_REQUIRE_NODE`` is set, which CI does.
"""

from __future__ import annotations

import json
import os
import random
from collections.abc import Iterator
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from catalog import BUCKETS
from conformance.corpus import AWKWARD, random_source
from conformance.ops import encode_expr, run
from conformance.oracle import Oracle, node
from conformance.schemas import SchemaName, schema
from test_props import _SOURCE  # pyright: ignore[reportPrivateUsage] — the shared generator
from textual_catsearch import Term, parse

_EXAMPLES = int(os.environ.get("CATSEARCH_DIFF_EXAMPLES", "200"))
_SETTINGS = settings(
    max_examples=_EXAMPLES,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)


@pytest.fixture(scope="module")
def oracle() -> Iterator[Oracle]:
    executable = node()
    if executable is None:
        if os.environ.get("CATSEARCH_REQUIRE_NODE"):
            pytest.fail("CATSEARCH_REQUIRE_NODE is set and there is no node")
        pytest.skip("no node to run the TypeScript port with")
    with Oracle(executable) as running:
        yield running


def _same(oracle: Oracle, case: dict[str, Any]) -> None:
    expected = json.loads(json.dumps(run(case)))
    got = oracle.ask(case)
    assert got == expected, f"\ncase     {case!r}\npython   {expected!r}\ntypescript {got!r}"


# --- generating inputs ------------------------------------------------------------------------
# Characters the reference's Unicode has assigned, and lone surrogates: the JS engine's Unicode
# may be newer, and how it normalises a character Python has never heard of is no disagreement
# (see `_fold_block` in conformance/ops.py).
_CHAR = st.characters(exclude_categories=("Cn",)) | st.characters(
    min_codepoint=0xD800, max_codepoint=0xDFFF
)
_TEXT = st.text(_CHAR, max_size=40)
_PIECES = (
    *AWKWARD,
    "kind:", "year:", "took:", "status:", "http.status:", "sequel-of.", "parent.", "nope:",
    "is:", "on:", "re:", "kv:", "(", ")", "-(", " OR ", " | ", " ", "-", "!", '"', "'", ":",
    ",", ">", ">=", "<", "..", "none", "tv", "5m", "2021", "@us", "=", "\t",
)  # fmt: skip
_SOUP = st.lists(st.sampled_from(_PIECES), max_size=14).map("".join)
_SCHEMA = st.sampled_from(("catalog", "units", "dynamic"))


@st.composite
def _walked(draw: st.DrawFn, name: SchemaName) -> str:
    """The fixtures' own random walk over the grammar, seeded by Hypothesis."""
    return random_source(random.Random(draw(st.integers(0, 2**32))), name)


@st.composite
def _source_for(draw: st.DrawFn) -> tuple[SchemaName, str]:
    name: SchemaName = draw(_SCHEMA)
    source = draw(st.one_of(_SOURCE, _TEXT, _SOUP, _walked(name)))
    return name, source


# --- the tests ------------------------------------------------------------------------------
@_SETTINGS
@given(_source_for(), st.booleans())
def test_parse_agrees(oracle: Oracle, named: tuple[SchemaName, str], empty_as_text: bool) -> None:
    name, source = named
    _same(oracle, {"op": "parse", "schema": name, "source": source, "emptyAsText": empty_as_text})
    _same(oracle, {"op": "match", "schema": name, "source": source})


@_SETTINGS
@given(_source_for(), st.data())
def test_completion_agrees(
    oracle: Oracle, named: tuple[SchemaName, str], data: st.DataObject
) -> None:
    name, source = named
    cursor = data.draw(st.integers(0, len(source)))
    limit = data.draw(st.sampled_from((8, 1, 3, 20)))
    _same(
        oracle,
        {"op": "suggest", "schema": name, "source": source, "cursor": cursor, "limit": limit},
    )
    _same(oracle, {"op": "active_span", "source": source, "cursor": cursor})


@_SETTINGS
@given(_source_for())
def test_lexing_and_grouping_agree(oracle: Oracle, named: tuple[SchemaName, str]) -> None:
    _, source = named
    _same(oracle, {"op": "lex", "source": source})
    _same(oracle, {"op": "open_groups", "source": source})


@_SETTINGS
@given(_source_for())
def test_rendering_agrees(oracle: Oracle, named: tuple[SchemaName, str]) -> None:
    """A tree rendered on its own, apart from the parse that made it."""
    name, source = named
    expr = encode_expr(parse(source, schema(name)).expr)
    _same(oracle, {"op": "render", "schema": name, "expr": expr})


@_SETTINGS
@given(st.one_of(_SOURCE, _SOUP, _walked("catalog")), st.sampled_from(BUCKETS))
def test_transforms_agree(oracle: Oracle, source: str, bucket: str) -> None:
    base = {"schema": "catalog", "source": source}
    among = list(BUCKETS)
    pin = encode_expr(Term("is", (bucket,)))
    _same(oracle, {"op": "pinned", **base, "field": "is", "among": among})
    _same(oracle, {"op": "with_term", **base, "term": pin, "among": among})
    _same(oracle, {"op": "without", **base, "field": "is", "among": among})
    _same(oracle, {"op": "without", **base, "field": "kind"})


@_SETTINGS
@given(_TEXT, _TEXT, st.sampled_from(("", "<>=.", "@", "()|*+?", ":+")))
def test_text_operations_agree(oracle: Oracle, text: str, other: str, extra: str) -> None:
    _same(oracle, {"op": "fold", "text": text})
    _same(oracle, {"op": "word_prefixed", "value": text, "needle": other})
    _same(oracle, {"op": "quote", "value": text, "extra": extra})


@_SETTINGS
@given(_SCHEMA, _TEXT, st.sampled_from((1, 3, 8, 50)))
def test_ranking_agrees(oracle: Oracle, name: SchemaName, needle: str, limit: int) -> None:
    for field in (*schema(name).fields, "status"):
        _same(
            oracle, {"op": "rank", "schema": name, "field": field, "needle": needle, "limit": limit}
        )
