"""What the query language claims for *every* input, not for the inputs someone thought of.

The example tests next door say what particular queries mean. These say what the language is:
that parsing is total, that writing a query back out and reading it again is the identity,
that conjunction behaves like conjunction. Those are the claims the rest of the design leans on
— a query that can be transformed rather than string-edited assumes ``parse`` and ``render``
are inverses, and assuming it is not the same as checking it.

Sources are built **well-formed by construction** rather than generated and filtered. The
fraction of random strings that are interesting queries is small enough that filtering would
spend the budget on rejects, and worse, it would cripple shrinking — a counterexample that
shrinks to something unreadable is a counterexample nobody acts on.
"""

from __future__ import annotations

import unicodedata

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from catalog import BUCKETS, FLAGS, KINDS, SCHEMA, STATES, Work
from query_checks import check
from textual_catsearch import (
    NOTHING,
    And,
    Not,
    Query,
    Term,
    Vocabulary,
    fold,
    holds,
    lex,
    neg,
    quote,
    render,
    suggest,
)
from textual_catsearch import parse as _parse
from textual_catsearch.lexer import separated
from textual_catsearch.query import Fault
from textual_catsearch.schema import FlagField, NumberField


def parse(source: str) -> Query[Work]:
    return _parse(source, SCHEMA)


# Fixpoints and full-vocabulary sweeps are not slow, but they are slower than the default
# per-example deadline allows for once shrinking starts, and a deadline flake reads exactly
# like a real failure.
_SETTINGS = settings(deadline=None, suppress_health_check=[HealthCheck.too_slow])


# --- generating sources -----------------------------------------------------------------
# A value that survives being written out and read back. The exclusions are the grammar's,
# not arbitrary: `"` is a lexer toggle rather than a character, `,` splits a field value into
# two, and leading or trailing space is stripped on the way in.
_INNER = st.text(
    alphabet=st.characters(
        min_codepoint=32, max_codepoint=0x2FFF, blacklist_characters='",:\t\n\r'
    ),
    min_size=0,
    max_size=12,
)
_EDGE = st.characters(min_codepoint=33, max_codepoint=0x2FFF, blacklist_characters='",:-!@')


def _join(head: str, middle: str, tail: str) -> str:
    return f"{head}{middle}{tail}".strip()


def _span(lo: int, hi: int) -> str:
    return f"{lo}..{hi}"


def _compared(op: str, n: int) -> str:
    return f"{op}{n}"


_VALUE = st.builds(_join, _EDGE, _INNER, _EDGE).filter(bool)

_NUMBER = st.integers(min_value=0, max_value=9999)
_NUMERIC_VALUE = st.one_of(
    _NUMBER.map(str),
    st.builds(_span, _NUMBER, _NUMBER),
    st.builds(_compared, st.sampled_from([">", "<", ">=", "<="]), _NUMBER),
)

_NUMERIC_FIELDS = sorted(n for n, s in SCHEMA.fields.items() if isinstance(s, NumberField))
_TEXT_FIELDS = sorted(
    n for n, s in SCHEMA.fields.items() if not isinstance(s, NumberField | FlagField)
)
# Everything `field:none` is defined for — every kind but the flag, whose values are questions
# rather than data.
_ABSENCE_FIELDS = sorted(n for n, s in SCHEMA.fields.items() if not isinstance(s, FlagField))
_HOPS = sorted(SCHEMA.relations)


@st.composite
def _clause(draw: st.DrawFn) -> str:
    """One token: a bare word, or ``field:value`` with one or more comma-separated values."""
    sign = draw(st.sampled_from(["", "-", "!"]))
    shape = draw(st.sampled_from(["bare", "text", "numeric", "flag", "absent", "path"]))
    if shape == "bare":
        return f"{sign}{quote(draw(_VALUE))}"
    if shape == "flag":
        return f"{sign}is:{draw(st.sampled_from(sorted(FLAGS)))}"
    if shape == "path":
        # A clause asked one or two hops away. It renders back, it narrows, and negating it
        # is negating the whole question — every law below has to hold of it too.
        hops = draw(st.lists(st.sampled_from(_HOPS), min_size=1, max_size=2))
        tail = draw(st.sampled_from([*_TEXT_FIELDS, *_NUMERIC_FIELDS]))
        value = draw(_VALUE if tail in _TEXT_FIELDS else _NUMERIC_VALUE)
        return f"{sign}{'.'.join((*hops, tail))}:{quote(value)}"
    if shape == "absent":
        # `field:none` is a clause like any other and has to survive every law above: it
        # renders back, it narrows, and negating it is the same as asking for anything there.
        return f"{sign}{draw(st.sampled_from(_ABSENCE_FIELDS))}:{NOTHING}"
    field = draw(st.sampled_from(_TEXT_FIELDS if shape == "text" else _NUMERIC_FIELDS))
    values = draw(st.lists(_VALUE if shape == "text" else _NUMERIC_VALUE, min_size=1, max_size=3))
    return f"{sign}{field}:" + ",".join(quote(v) for v in values)


def _joined(parts: list[str]) -> str:
    return " ".join(parts)


def _bracketed(inner: str) -> str:
    return f"({inner})"


def _alternated(parts: list[str]) -> str:
    return " OR ".join(parts)


def _expression(depth: int) -> st.SearchStrategy[str]:
    """Sources with brackets and ``OR`` in them, nested a bounded number of times."""
    atom = _clause()
    if depth > 0:
        deeper = _expression(depth - 1)
        atom = st.one_of(
            atom,
            deeper.map(_bracketed),
            st.lists(deeper.map(_bracketed) | _clause(), min_size=2, max_size=3).map(_alternated),
        )
    return st.lists(atom, min_size=0, max_size=4).map(_joined)


_SOURCE = _expression(2)


# --- totality -----------------------------------------------------------------------------
@_SETTINGS
@given(st.text(max_size=200))
def test_parsing_is_total(source: str) -> None:
    """The bar is parsed on every keystroke, so half-typed *is* the normal input.

    A parser that can raise on some byte sequence is a query bar that can crash, and the
    string that reaches it is whatever the user is midway through typing.
    """
    assert isinstance(parse(source), Query)
    assert isinstance(_parse(source, SCHEMA, empty_as_text=True), Query)


@_SETTINGS
@given(st.text(alphabet=st.sampled_from("ab:()\"' -|.,<>=é\t"), max_size=60) | st.text(max_size=60))
def test_every_diagnostic_points_into_what_was_typed(source: str) -> None:
    """A span is for drawing under the text, so it has to be somewhere in it, and hold what the
    diagnostic is about: never empty, never past the end, never a neighbour's characters."""
    for d in parse(source).diagnostics:
        assert 0 <= d.start < d.end <= len(source), (source, d)
        pointed = source[d.start : d.end]
        if d.fault is Fault.UNCLOSED_QUOTE:
            assert pointed.startswith(('"', "'")) and d.end == len(source)
        else:
            assert set(d.text) <= set(pointed) | QUOTES, (source, d)  # `'v'` reads as `"v"`


# Text that breaks offset arithmetic somewhere: more than one code point per glyph (flags, ZWJ
# families, combining marks), two cells per code point (CJK, fullwidth), right-to-left runs and
# the controls that flip them, NUL, and punctuation that looks like the grammar's but is not.
_AWKWARD = (
    "нет", "скоро", "الرسالة", "عربي", "漢字", "薬屋", "ヱヴァ", "한국어", "🇯🇵", "👨‍👩‍👧",
    "😀", "x́", "e\u0301\u0301", "\x00", "a\x00b", "—", "–", "：", "（", "）", "“", "”",
    "\u202e", "\u200b", "\u3000", "Ｄ", "ß", "İ",
)  # fmt: skip
QUOTES = frozenset("'\"")
_GRAMMAR = ("kind:", "year:", "nope:", "(", ")", " OR ", " ", "-", '"', ":", ",", ">")


@_SETTINGS
@given(st.lists(st.sampled_from(_AWKWARD + _GRAMMAR), max_size=12).map("".join))
def test_spans_stay_exact_through_scripts_emoji_and_control_characters(source: str) -> None:
    """Offsets are code points into exactly what was typed, whatever the text is made of."""
    for d in parse(source).diagnostics:
        assert 0 <= d.start < d.end <= len(source), (source, d)
        pointed = source[d.start : d.end]
        if d.fault is Fault.UNCLOSED_QUOTE:
            assert pointed.startswith(('"', "'")) and d.end == len(source)
        else:
            assert set(d.text) <= set(pointed) | QUOTES, (source, d)  # `'v'` reads as `"v"`


@pytest.mark.parametrize(
    ("source", "pointed"),
    [
        ("нет:1", "нет"),
        ("kind:tv نعم:x", "نعم"),
        ("(year:скоро", "year:скоро"),
        ("year:漢字", "year:漢字"),
        ("🇯🇵:x", "🇯🇵"),
        ("👨‍👩‍👧:x kind:tv", "👨‍👩‍👧"),
        ("e\u0301\u0301:x", "e\u0301\u0301"),
        ("a\x00b:x", "a\x00b"),
        ("kind:tv — year:—", "year:—"),
        ("\u202eevil:x", "\u202eevil"),
    ],
)
def test_a_span_covers_whole_characters_however_they_are_spelled(source: str, pointed: str) -> None:
    assert pointed in [source[d.start : d.end] for d in parse(source).diagnostics]


@pytest.mark.parametrize("depth", [1, 32, 33, 400, 5000])
def test_parsing_is_total_however_deep_the_brackets_go(depth: int) -> None:
    """Nesting costs a stack frame a level, so without a ceiling a bar full of `(` raises.

    Generated text never reaches this — the odds of drawing four hundred consecutive brackets
    are nil — which is why it is written out rather than sampled, and why the fuzzer was what
    found it: mutation grows a run of one byte, and random generation does not.
    """
    check("(" * depth)
    check("(" * depth + "kind:tv" + ")" * depth)


@_SETTINGS
@given(st.text(max_size=200))
def test_rendering_anything_parsed_is_total(source: str) -> None:
    assert isinstance(render(parse(source).expr, SCHEMA), str)


@_SETTINGS
@given(st.text(max_size=200))
def test_completion_is_total_at_every_caret(source: str) -> None:
    """``suggest`` runs on each keystroke too, at whatever offset the caret happens to be."""
    for cursor in range(len(source) + 1):
        assert isinstance(suggest(source, cursor, SCHEMA, Vocabulary()), tuple)


@given(st.text(alphabet=st.sampled_from('ab,"é'), max_size=30))
def test_completion_splits_a_comma_list_where_the_lexer_does(source: str) -> None:
    """Completion reads offsets off raw text and the parser reads quote-flagged runs: two
    readers of one rule, so they are checked against each other rather than trusted to agree."""
    spans = separated(source, ",")
    assert ",".join(source[lo:hi] for lo, hi in spans) == source
    (token,) = lex(source) or (None,)
    if token is not None:
        assert len(spans) == len(token.body.split(","))


# --- parse and render are inverses ---------------------------------------------------------
@_SETTINGS
@given(_SOURCE)
def test_a_query_written_back_out_parses_to_the_same_query(source: str) -> None:
    """``parse ∘ render == id`` on the trees ``parse`` can produce.

    This is the claim the whole seam rests on: it is what lets a query be *transformed* —
    projected into the add bar, or re-bucketed — by editing the tree and writing it out,
    rather than by splicing strings and hoping the quoting survives.
    """
    parsed = parse(source).expr
    assert parse(render(parsed, SCHEMA)).expr == parsed


@_SETTINGS
@given(st.text(max_size=200))
def test_rendering_reaches_a_fixed_point_after_one_pass(source: str) -> None:
    """Even on junk. Rendering normalises; normalising twice must not differ from once."""
    once = render(parse(source).expr, SCHEMA)
    assert render(parse(once).expr, SCHEMA) == once


# --- the tree behaves like the logic it looks like -------------------------------------------
@_SETTINGS
@given(_SOURCE)
def test_negating_twice_is_the_identity(source: str) -> None:
    """``neg`` is the only thing that negates, so that a query has one spelling, not two."""
    expr = parse(source).expr
    assert neg(neg(expr)) == expr


@_SETTINGS
@given(_SOURCE)
def test_a_negation_is_never_left_wrapping_a_single_clause(source: str) -> None:
    """The normal form: ``-kind:tv`` is a negated clause, never ``Not`` around a clause.

    Two spellings of one query would mean every claim on this page needed an "unless"
    attached, and the round-trip above would be false for one of them.
    """
    expr = neg(parse(source).expr)
    assert not (isinstance(expr, Not) and isinstance(expr.inner, Term))


_WORKS = st.builds(
    Work,
    title=st.sampled_from(["Reacher", "Dune", "Killing Eve", "Honey"]),
    kind=st.sampled_from(KINDS),
    years=st.lists(st.integers(min_value=1990, max_value=2030), max_size=2).map(tuple),
    season=st.none() | st.integers(min_value=1, max_value=5),
    genres=st.lists(st.sampled_from(["horror", "comedy", "drama"]), max_size=2).map(tuple),
    bucket=st.sampled_from(BUCKETS),
    state=st.sampled_from(STATES),
)
_ROWS = st.lists(
    st.builds(
        Work,
        title=st.sampled_from(["Reacher", "Dune", "Killing Eve", "Honey"]),
        kind=st.sampled_from(KINDS),
        years=st.lists(st.integers(min_value=1990, max_value=2030), max_size=2).map(tuple),
        season=st.none() | st.integers(min_value=1, max_value=5),
        genres=st.lists(st.sampled_from(["horror", "comedy", "drama"]), max_size=2).map(tuple),
        bucket=st.sampled_from(BUCKETS),
        state=st.sampled_from(STATES),
        sequel_of=st.lists(_WORKS, max_size=2).map(tuple),
    ),
    min_size=1,
    max_size=6,
)


@_SETTINGS
@given(_SOURCE, _SOURCE, _ROWS)
def test_conjunction_is_intersection(left: str, right: str, rows: list[Work]) -> None:
    """``a b`` keeps exactly the rows ``a`` keeps and ``b`` keeps — nothing more, nothing less."""
    both = And((parse(left).expr, parse(right).expr))
    kept = {i for i, r in enumerate(rows) if holds(both, r, SCHEMA)}
    assert kept == {i for i, r in enumerate(rows) if parse(left).matches(r)} & {
        i for i, r in enumerate(rows) if parse(right).matches(r)
    }


def _values_for(field: str) -> st.SearchStrategy[str]:
    match SCHEMA.fields[field]:
        case NumberField():
            return _NUMERIC_VALUE
        case FlagField():
            return st.sampled_from(sorted(FLAGS))
        case _:
            return _VALUE


_ASKABLE = sorted(SCHEMA.fields)


@st.composite
def _distinct_clauses(draw: st.DrawFn) -> tuple[str, ...]:
    """Clauses on *distinct* fields, so none of them folds into another.

    Distinct on purpose: a key written twice widens by design — ``kind:tv kind:movie`` asks
    for either — so the claim below is about adding a new question, not another answer to one
    already asked.
    """
    picked = draw(st.lists(st.sampled_from(_ASKABLE), min_size=1, max_size=4, unique=True))
    signs = draw(st.lists(st.sampled_from(["", "-"]), min_size=len(picked), max_size=len(picked)))
    return tuple(
        f"{sign}{field}:{quote(draw(_values_for(field)))}"
        for field, sign in zip(picked, signs, strict=True)
    )


@_SETTINGS
@given(_distinct_clauses(), _ROWS)
def test_adding_a_clause_never_adds_a_row(clauses: tuple[str, ...], rows: list[Work]) -> None:
    """Every clause narrows. This is the one the shape properties above could not see.

    They ask whether a string parses, renders and reads back — all true of a clause that was
    *dropped*, because a clause that is not in the tree cannot make the tree disagree with
    itself. So ``year:soon`` parsed, rendered, round-tripped, reported its diagnostic, and
    silently searched every year; ``kind:tv year:soon`` came back with games. What no
    tree-level property can state, and this one does, is that the tree still answers the
    question the string asked.
    """

    def kept(source: str) -> set[int]:
        return {i for i, r in enumerate(rows) if parse(source).matches(r)}

    for i in range(len(clauses)):
        assert kept(" ".join(clauses[: i + 1])) <= kept(" ".join(clauses[:i]))


@_SETTINGS
@given(_SOURCE, _ROWS)
def test_the_order_clauses_were_typed_in_does_not_change_the_answer(
    source: str, rows: list[Work]
) -> None:
    expr = parse(source).expr
    assert isinstance(expr, And)
    flipped = And(tuple(reversed(expr.parts)))
    for row in rows:
        assert holds(expr, row, SCHEMA) is holds(flipped, row, SCHEMA)


@_SETTINGS
@given(_ROWS)
def test_an_empty_query_keeps_everything(rows: list[Work]) -> None:
    assert len(parse("   ").filter(rows)) == len(rows)


@_SETTINGS
@given(_SOURCE, _ROWS)
def test_a_query_and_its_negation_partition_the_rows(source: str, rows: list[Work]) -> None:
    """Nothing is both kept and dropped, and nothing falls between the two."""
    expr = parse(source).expr
    kept = [r for r in rows if holds(expr, r, SCHEMA)]
    dropped = [r for r in rows if holds(Not(expr), r, SCHEMA)]
    assert len(kept) + len(dropped) == len(rows)


# --- text people actually paste ---------------------------------------------------------------
# Titles arrive by copy-paste, from sources that disagree about how to spell the same name.
# Each block below is a way that has gone wrong somewhere real: decomposed accents from macOS,
# fullwidth Latin from a Japanese IME, a zero-width space carried out of an HTML title, a
# right-to-left override, an unpaired surrogate from a bad decode.
_SCRIPTS = st.sampled_from(
    [
        "Café Society",  # NFC
        "Café Society",  # NFD — the same name, a different string
        "ＤＵＮＥ",
        "Straße",
        "İstanbul",
        "ﬁlm noir",
        "рпг",
        "ヱヴァンゲリヲン新劇場版",
        "薬屋のひとりごと",
        "الرسالة",
        "עלמה",
        "Ai​ka",
        "‮evil‬",
        "🇯🇵 emoji 😀",
        "x́" * 8,
        'The "Burbs',
        "a b",
        "　leading ideographic space",
        "ǅezva",
        "ⅯⅭⅯⅬⅩⅩ",
    ]
)
_HOSTILE = st.one_of(
    _SCRIPTS,
    st.text(
        alphabet=st.characters(codec="utf-8", min_codepoint=1),
        max_size=60,
    ),
    st.text(max_size=60),  # hypothesis' own default, which includes lone surrogates
)


@_SETTINGS
@given(_HOSTILE)
def test_pasted_text_never_breaks_the_language(text: str) -> None:
    """Whatever lands in the bar is parsed, written back out, and read again unchanged."""
    parsed = parse(text)
    assert parse(render(parsed.expr, SCHEMA)).expr == parsed.expr
    for cursor in (0, len(text) // 2, len(text)):
        suggest(text, cursor, SCHEMA, Vocabulary())


@_SETTINGS
@given(_HOSTILE)
def test_a_name_can_always_be_found_by_typing_it(text: str) -> None:
    """The property the whole fold exists for.

    A title is stored exactly as it was pasted. Typing that same title back must find it —
    whatever it is made of. Without folding, every accented, fullwidth, ligatured or
    zero-width-spaced name fails, which is the worst kind of search bug: the row is visibly
    on screen and the search box says there is nothing there.
    """
    if not fold(text).strip():
        return  # a name made only of invisible characters is not a name
    row = Work(title=text)
    assert parse(quote(text)).filter([row]) == [row]


@_SETTINGS
@given(_HOSTILE)
def test_folding_is_idempotent(text: str) -> None:
    assert fold(fold(text)) == fold(text)


@_SETTINGS
@given(_SCRIPTS)
def test_a_name_folds_the_same_however_it_was_normalised(text: str) -> None:
    """The four Unicode normal forms are four spellings of one name, and must compare equal."""
    forms = {fold(unicodedata.normalize(form, text)) for form in ("NFC", "NFD", "NFKC", "NFKD")}
    assert len(forms) == 1


@_SETTINGS
@given(_SCRIPTS, _SCRIPTS)
def test_folding_never_collapses_two_different_scripts(a: str, b: str) -> None:
    """Latin ``A`` and Cyrillic ``А`` look identical; answering one with the other would lie."""
    if fold(a) == fold(b):
        assert {unicodedata.name(c, "").split()[0] for c in fold(a) if c.isalpha()} == {
            unicodedata.name(c, "").split()[0] for c in fold(b) if c.isalpha()
        }


# --- hand-picked seeds -------------------------------------------------------------------------
# Inputs a fuzzer found or a person would think to try; the same claims, run as plain examples.
_SEEDS = [
    "(-(()))",
    '"The ""Burbs"',
    "kind:tv OR",
    "sequel-of.sequel-of.name:dune",
    "tag:none,horror -tag:none",
    "a OR () b",
    "-(-(kind:tv))",
    ")))(((",
    "name:kind:tv",
    "name:a,b",
    "cast:'Alan Ritchson' Don't",
    "on:netflix@us year:>=2020 is:early-access",
]


@pytest.mark.parametrize("seed", _SEEDS)
def test_every_seed_holds(seed: str) -> None:
    check(seed)
