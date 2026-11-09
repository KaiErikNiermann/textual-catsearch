"""The shared spec is the reference's answers, current: fixtures and Unicode tables up to date.

The TypeScript suite checks the port against ``spec/fixtures``; this checks that those files
are what the Python package answers today, so a change in behaviour cannot leave the spec
describing the old one. Regenerate with ``poetry run python -m conformance.generate`` (and
``conformance.unicode_tables``) from ``tests/``.

Only under the Unicode version the fixtures were written with: an older interpreter folds
newer characters differently, which says nothing about the code.
"""

from __future__ import annotations

import json
import unicodedata

import pytest

from conformance import unicode_tables
from conformance.generate import FIXTURES, META, fixtures, render_file

_WRITTEN_UNDER = json.loads(META.read_text("utf-8"))["unicode"]
pytestmark = pytest.mark.skipif(
    unicodedata.unidata_version != _WRITTEN_UNDER,
    reason=f"fixtures written under Unicode {_WRITTEN_UNDER}, "
    f"this is {unicodedata.unidata_version}",
)

_EXPECTED = fixtures()


def test_the_fixture_files_are_exactly_the_generated_ones() -> None:
    on_disk = {p.stem for p in FIXTURES.glob("*.jsonl")}
    assert on_disk == set(_EXPECTED), "regenerate: python -m conformance.generate"


@pytest.mark.parametrize("stem", sorted(_EXPECTED))
def test_fixtures_are_the_references_answers(stem: str) -> None:
    written = (FIXTURES / f"{stem}.jsonl").read_text("utf-8")
    assert written == render_file(_EXPECTED[stem]), (
        f"spec/fixtures/{stem}.jsonl is stale: python -m conformance.generate"
    )


def test_the_unicode_tables_are_current() -> None:
    assert unicode_tables.TARGET.read_text("utf-8") == unicode_tables.render(), (
        "js/src/unicode-data.ts is stale: python -m conformance.unicode_tables"
    )
