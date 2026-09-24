"""Tests for the query language — lexing, parsing, matching and completion, by example.

Entirely pure: no terminal. Every case builds rows of the catalogue schema directly, so these
run in milliseconds and cover the grammar exhaustively.
"""

from __future__ import annotations

import pytest

from catalog import SCHEMA, Work, keep
from textual_catsearch import (
    And,
    Diagnostic,
    Fault,
    Or,
    Query,
    Term,
    VocabEntry,
    Vocabulary,
    apply,
    lex,
    rank_values,
    render,
    suggest,
    without,
)
from textual_catsearch import parse as _parse


def parse(source: str, *, empty_as_text: bool = False) -> Query[Work]:
    return _parse(source, SCHEMA, empty_as_text=empty_as_text)


# --- the language is total over its own vocabulary -------------------------------------
@pytest.mark.parametrize("field", sorted(SCHEMA.fields))
def test_every_field_answers_a_query_without_matching_everything(field: str) -> None:
    """A field that cannot be matched must not answer ``True`` and widen the result set.

    Asking each field for something no row has must exclude the row.
    """
    hopeless = "9999" if field in {"year", "season"} else "zzzznothing"
    rich = Work(
        years=(2026,),
        season=3,
        genres=("horror",),
        cast=("Alan Ritchson",),
        platforms=(("Netflix", ("US",)),),
    )
    assert keep(f"{field}:{hopeless}", rich) == []


# --- lexing ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("reacher kind:tv", ["reacher", "kind:tv"]),
        ('cast:"Alan Ritchson"', ["cast:Alan Ritchson"]),
        ('"some tv show"', ["some tv show"]),
        ('actors:"name 1, name 2"', ["actors:name 1, name 2"]),
        ("-tag:comedy", ["-tag:comedy"]),
        ("   spaced   out   ", ["spaced", "out"]),
        ("", []),
    ],
)
def test_lex_basics(source: str, expected: list[str]) -> None:
    assert [t.text for t in lex(source)] == expected


def test_lex_keeps_apostrophes_literal() -> None:
    """The reason shlex was rejected: `'` must never be a quote in a search box."""
    assert [t.text for t in lex("Don't Look Up")] == ["Don't", "Look", "Up"]
    assert [t.text for t in lex("The Hitchhiker's Guide")] == ["The", "Hitchhiker's", "Guide"]


def test_lex_tolerates_an_unterminated_quote() -> None:
    """Half-typed quotes are the normal state of a live query bar, not an error."""
    assert [t.text for t in lex('cast:"Alan Rit')] == ["cast:Alan Rit"]


def test_lex_spans_round_trip_to_the_source() -> None:
    source = 'reacher cast:"Alan Ritchson" year:2026'
    for tok in lex(source):
        assert source[tok.start : tok.end].replace('"', "") == tok.text


def test_a_doubled_quote_inside_quotes_is_the_character_itself() -> None:
    assert parse('"The ""Burbs"').terms[0].values == ('The "Burbs',)


# --- parsing --------------------------------------------------------------------------
def test_bare_terms_become_the_search_text() -> None:
    q = parse("the odyssey kind:movie")
    assert q.text == "the odyssey"
    assert q.first("kind") == Term("kind", ("movie",))


def test_comma_values_are_or_ed_within_a_term() -> None:
    assert parse("cast:Ritchson,Sten").terms[0].values == ("Ritchson", "Sten")


def test_a_quoted_comma_is_part_of_the_value_rather_than_a_separator() -> None:
    """Quoting is how you say "this is one string", and it means that.

    A lexer that strips quotes and forgets they had been there splits a comma the user had
    deliberately enclosed — and reads `"kind:tv"` as a kind filter rather than as a title.
    """
    assert parse('cast:"Alan Ritchson, Maria Sten"').terms[0].values == (
        "Alan Ritchson, Maria Sten",
    )
    literal = parse('"kind:tv"').terms[0]
    assert (literal.field, literal.values) == ("name", ("kind:tv",))


def test_negation_accepts_dash_or_bang() -> None:
    assert parse("-tag:comedy").terms[0].negated
    assert parse("!tag:comedy").terms[0].negated


def test_field_aliases_resolve_to_canonical_names() -> None:
    assert parse("actors:x").terms[0].field == "cast"
    assert parse("on:netflix").terms[0].field == "platform"
    assert parse("KIND:tv").terms[0].field == "kind"


@pytest.mark.parametrize(
    ("source", "lo", "hi"),
    [
        ("year:2026", 2026, 2026),
        ("year:2020..2026", 2020, 2026),
        ("year:..2026", None, 2026),
        ("year:>=2026", 2026, None),
        ("year:<=2030", None, 2030),
        ("year:>2026", 2027, None),
        ("year:<2030", None, 2029),
    ],
)
def test_year_ranges(source: str, lo: int | None, hi: int | None) -> None:
    rng = parse(source).terms[0].ranges[0]
    assert (rng.lo, rng.hi) == (lo, hi)


def test_unknown_field_degrades_to_text_rather_than_vanishing() -> None:
    """`Andor: Season 2` is a title, not a typo'd field — it must still search."""
    q = parse("Andor: Season 2")
    assert q.unknown_fields == ("Andor",)
    assert "Andor:" in q.text
    assert keep("Andor: Season 2", Work(title="Andor: Season 2")) == ["Andor: Season 2"]


@pytest.mark.parametrize("fault", sorted(Fault), ids=str)
def test_every_fault_has_a_wording(fault: Fault) -> None:
    """The wording is a table, so a fault added without an entry raises where it is displayed.

    Which is a status line under a search bar, mid-keystroke — the worst place to find out.
    """
    rendered = Diagnostic(fault, "cast:x", 0, 6).render()
    assert rendered.strip()
    assert "{" not in rendered


@pytest.mark.parametrize(
    ("source", "held"),
    [
        ("cast:O.Connor", "."),
        ("tag:a|b", "|"),
        ("kind:one-of[tv,film]", "[]"),
        ("genre:sci-fi*", "*"),
        ("person:A24+Neon", "+"),
    ],
)
def test_punctuation_an_unquoted_value_may_not_carry_is_named(source: str, held: str) -> None:
    """Reserved, and said so — the alphabet is `[A-Za-z0-9_-]` plus the field's own operators.

    Drawn wider than today's grammar needs on purpose. An unquoted value that may hold any
    punctuation is one the grammar can never take a character back from, because by then every
    saved query already means something.
    """
    found = parse(source).diagnostics
    assert [(d.fault, d.text) for d in found] == [(Fault.RESERVED, held)]


def test_a_reserved_value_still_means_what_it_said_and_renders_the_quotes_in() -> None:
    """Nothing breaks. The clause reads as though the value had been quoted, and writing it back
    puts the quotes in — so a query that goes through the tree migrates itself.
    """
    row = Work(cast=("Josh O.Connor",))
    assert keep("cast:O.Connor", row) == [row.title]
    assert render(parse("cast:O.Connor").expr, SCHEMA) == 'cast:"O.Connor"'
    assert parse('cast:"O.Connor"').diagnostics == ()


def test_the_operators_a_field_declares_are_not_reserved_for_it() -> None:
    """`year:` reads ranges, so it keeps `<>=.`; `platform:` declares an `@` market."""
    for source in ("year:2020..2026", "year:>=2026", "on:netflix@us"):
        assert parse(source).diagnostics == (), source
    # ...and a field that declares neither does not get them for free.
    assert parse("tag:>=2026").diagnostics[0].fault is Fault.RESERVED


def test_a_bare_word_is_free_text_and_keeps_its_punctuation() -> None:
    """The commonest thing anyone types must not need quotes."""
    for source in ("Mr. Robot", "Wall-E", "#Alive", "Se7en"):
        assert parse(source).diagnostics == (), source
        assert render(parse(source).expr, SCHEMA) == source


def test_a_half_typed_field_constrains_nothing() -> None:
    assert parse("kind:").terms == ()


def test_a_half_typed_field_is_text_when_the_string_names_something() -> None:
    """Dropping it would eat a word out of the name being typed."""
    assert parse("Person: Someone", empty_as_text=True).text == "Person: Someone"
    assert parse("kind:", empty_as_text=True).terms == (Term("name", ("kind:",)),)


def test_parse_never_raises_on_junk() -> None:
    for junk in ('""', '"', ":::", "-", "year:abc", "  :  ", "a:b:c"):
        assert isinstance(parse(junk), Query)


# --- matching -------------------------------------------------------------------------
def test_empty_query_matches_everything() -> None:
    assert keep("", Work(title="A"), Work(title="B")) == ["A", "B"]


def test_bare_term_matches_title_and_aliases() -> None:
    row = Work(title="The Odyssey", aliases=("Odyssey",))
    assert keep("odyssey", row) == ["The Odyssey"]
    assert keep("the ody", row) == ["The Odyssey"]


def test_multiple_bare_terms_are_and_ed() -> None:
    row = Work(title="Dune: Part Two")
    assert keep("dune two", row) == ["Dune: Part Two"]
    assert keep("dune three", row) == []


def test_matching_ignores_case_and_accents() -> None:
    assert keep("cafe", Work(title="Café Society")) == ["Café Society"]
    assert keep("ＤＵＮＥ", Work(title="Dune")) == ["Dune"]


def test_fields_ask_different_questions() -> None:
    row = Work(title="Tenet", director=("Christopher Nolan",), cast=("John David Washington",))
    assert keep("director:nolan", row) == ["Tenet"]
    assert keep("cast:nolan", row) == []
    assert keep("person:nolan", row) == ["Tenet"]


def test_a_broad_field_spans_what_narrow_ones_split() -> None:
    row = Work(genres=("Sci-Fi",), themes=("body horror",))
    assert keep("tag:sci-fi", row) != []
    assert keep("tag:body", row) != []
    assert keep("genre:sci-fi", row) != []
    assert keep("genre:body", row) == []
    assert keep('theme:"body horror"', row) != []


def test_a_number_field_matches_any_of_its_values() -> None:
    row = Work(years=(2026, 2027))
    assert keep("year:2026", row) != []
    assert keep("year:2027", row) != []
    assert keep("year:2025", row) == []


def test_a_row_with_no_number_matches_no_range() -> None:
    assert keep("year:2026", Work()) == []


def test_negation_inverts_the_term() -> None:
    horror = Work(title="H", genres=("horror",))
    comedy = Work(title="C", genres=("comedy",))
    assert keep("-tag:comedy", horror, comedy) == ["H"]


def test_flags() -> None:
    avail = Work(title="A", bucket="available")
    upcoming = Work(title="U", bucket="upcoming", blockers=("region",))
    assert keep("is:available", avail, upcoming) == ["A"]
    assert keep("is:blocked", avail, upcoming) == ["U"]
    assert keep("is:tba", avail, upcoming) == ["A", "U"]
    assert keep("is:AVAILABLE", avail, upcoming) == ["A"]
    assert keep("is:nonsense", avail, upcoming) == []


def test_an_enum_is_exact_where_text_is_a_substring() -> None:
    """A closed vocabulary — `state:watch` is a typo, not a prefix search."""
    row = Work(title="Dune", state="watched")
    assert keep("state:watched", row) == ["Dune"]
    assert keep("state:watch", row) == []


def test_an_enum_normalises_the_query_value() -> None:
    film = Work(title="Dune", kind="movie")
    assert keep("kind:film", film) == ["Dune"]
    assert keep("kind:tv-show", film) == []


def test_terms_compose_with_and() -> None:
    rows = (
        Work(title="A", kind="movie", years=(2026,)),
        Work(title="B", kind="tv", years=(2026,)),
        Work(title="C", kind="movie", years=(2025,)),
    )
    assert keep("kind:movie year:2026", *rows) == ["A"]


# --- a custom field ---------------------------------------------------------------------
def _where(*lines: tuple[str, tuple[str, ...]]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    return lines


def test_a_custom_field_decides_for_itself() -> None:
    """`on:netflix@us` asks one question about one pair, which no built-in kind can."""
    row = Work(platforms=_where(("Netflix", ("US", "CA"))))
    assert parse("on:netflix@us").matches(row)
    assert not parse("on:netflix@jp").matches(row)
    assert parse("on:netflix").matches(row)
    assert parse("on:@ca").matches(row)
    assert not parse("-on:netflix@us").matches(row)


def test_a_custom_field_answers_absence_when_it_says_how() -> None:
    assert keep("on:none", Work(title="A"), Work(title="B", platforms=_where(("X", ())))) == ["A"]


# --- completion -----------------------------------------------------------------------
_VOCAB = Vocabulary(
    {
        "tag": (VocabEntry("horror", 9), VocabEntry("body horror", 2)),
        "genre": (VocabEntry("horror", 9),),
        "theme": (VocabEntry("body horror", 2),),
        "person": (VocabEntry("Alan Ritchson", 3), VocabEntry("Denis Villeneuve", 7)),
        "director": (VocabEntry("Denis Villeneuve", 7),),
        "cast": (VocabEntry("Alan Ritchson", 3), VocabEntry("Timothee Chalamet", 2)),
        "platform": (VocabEntry("Netflix", 12),),
    }
)


def _suggest(source: str, cursor: int, *, limit: int = 8) -> tuple[str, ...]:
    return tuple(s.insert for s in suggest(source, cursor, SCHEMA, _VOCAB, limit=limit))


def _labels(source: str, cursor: int | None = None, *, limit: int = 8) -> list[str]:
    at = len(source) if cursor is None else cursor
    return [s.label for s in suggest(source, at, SCHEMA, _VOCAB, limit=limit)]


def test_suggests_field_names_at_a_token_start() -> None:
    assert "cast:" in _suggest("ca", 2)


def test_suggests_values_after_a_colon() -> None:
    out = suggest("cast:rit", 8, SCHEMA, _VOCAB)
    assert out[0].insert == 'cast:"Alan Ritchson"'
    assert out[0].label == "Alan Ritchson"


def test_value_completion_is_scoped_to_the_field() -> None:
    """`director:` offering an actor suggests a name that provably cannot match."""
    assert _labels("director:") == ["Denis Villeneuve"]
    assert _labels("cast:") == ["Alan Ritchson", "Timothee Chalamet"]


def test_value_suggestions_are_ranked_by_usage() -> None:
    assert _labels("person:") == ["Denis Villeneuve", "Alan Ritchson"]


def test_a_field_nobody_uses_offers_nothing_rather_than_everything() -> None:
    assert suggest("year:", 5, SCHEMA, _VOCAB) == ()


def test_choices_complete_without_a_vocabulary() -> None:
    assert "kind:movie" in _suggest("kind:mov", 8)
    assert "state:watching" in _suggest("state:watch", 11)


def test_value_completion_is_scoped_to_the_typed_prefix() -> None:
    """A typed character has to narrow the list, or tab walks through what it ruled out."""
    # `early-access` is in because "access" starts with the typed letter — the match is at a
    # word start, not anywhere in the string, which is what keeps `dated` and `stale` out.
    assert _labels("is:a", limit=20) == ["aging", "available", "early-access"]


def test_a_word_start_counts_as_a_prefix() -> None:
    """Names are looked up by whichever part of them comes to mind."""
    assert _labels("cast:rit")[0] == "Alan Ritchson"


def test_a_mid_word_fragment_still_finds_something_rather_than_nothing() -> None:
    """Nothing starts with `itch`, so the substring fallback takes over."""
    assert _labels("cast:itch")[0] == "Alan Ritchson"


def test_field_and_value_suggestions_are_told_apart() -> None:
    """The widget previews a value completion and splices a field one — hence the tag."""
    assert all(s.kind == "field" for s in suggest("ca", 2, SCHEMA, _VOCAB))
    assert all(s.kind == "value" for s in suggest("cast:", 5, SCHEMA, _VOCAB))


def test_the_bare_field_is_never_offered_as_a_name() -> None:
    """Typing `na` is far likelier the start of a title than a request for `name:`."""
    assert "name:" not in _suggest("na", 2)


def test_offered_names_can_be_narrowed() -> None:
    picks = suggest("", 0, SCHEMA, _VOCAB, limit=99, fields=frozenset({"kind", "year"}))
    assert [p.label for p in picks] == ["kind:", "year:"]


def test_rank_values_is_the_shared_half_of_completion() -> None:
    """A form's `director` field wants the same candidates the query bar would offer."""
    assert [e.value for e, _ in rank_values(SCHEMA, "director", _VOCAB, "")] == ["Denis Villeneuve"]
    assert [e.value for e, _ in rank_values(SCHEMA, "cast", _VOCAB, "Rit")] == ["Alan Ritchson"]
    assert rank_values(SCHEMA, "cast", _VOCAB, "zzz") == ()


def test_rank_values_resolves_a_field_alias() -> None:
    assert rank_values(SCHEMA, "actor", _VOCAB, "") == rank_values(SCHEMA, "cast", _VOCAB, "")


def test_suggestion_splices_back_into_the_source() -> None:
    """The contract the widget relies on: source[:start] + insert + source[end:]."""
    source = "kind:tv cast:rit year:2026"
    assert apply(source, suggest(source, 16, SCHEMA, _VOCAB)[0]) == (
        'kind:tv cast:"Alan Ritchson" year:2026'
    )


def test_completion_mid_string_leaves_the_tail_alone() -> None:
    source = "ca year:2026"
    assert apply(source, suggest(source, 2, SCHEMA, _VOCAB)[0]) == "cast: year:2026"


def test_completes_only_the_segment_under_the_caret_in_a_comma_list() -> None:
    """And quotes only that segment — the comma the user typed is a separator, not a letter.

    Quoting the whole accumulated list gave back `cast:"Denis,Alan Ritchson"`: one value with a
    comma inside it rather than the two being built.
    """
    source = "cast:Denis,rit"
    top = suggest(source, len(source), SCHEMA, _VOCAB)[0]
    assert top.insert == 'cast:Denis,"Alan Ritchson"'
    assert parse(top.insert).terms[0].values == ("Denis", "Alan Ritchson")


def test_negation_and_groups_are_preserved_through_completion() -> None:
    assert _suggest("-genre:hor", 10)[0] == "-genre:horror"
    assert _suggest("(-genre:hor", 11)[0] == "(-genre:horror"


def test_an_alias_completes_to_its_canonical_field() -> None:
    assert _suggest("on:net", 6)[0] == "platform:Netflix"


# --- single-quoted values -------------------------------------------------------------------
def test_a_shell_shaped_single_quoted_value_is_understood() -> None:
    assert parse("cast:'Alan Ritchson'").terms[0].values == ("Alan Ritchson",)


@pytest.mark.parametrize("source", ["Don't Look Up", "'71", "'71 Don't Look Up"])
def test_an_apostrophe_outside_a_value_is_left_alone(source: str) -> None:
    """The lexer's reason for refusing `'` as a quote still holds everywhere else."""
    assert parse(source).text == source


def test_the_normaliser_declines_a_value_whose_pair_is_ambiguous() -> None:
    """An inner apostrophe means `'...'` is not unambiguously a wrapper, so nothing is undone."""
    assert parse("name:'Don't Look Up'").text == "'Don't Look Up'"


def test_a_double_quoted_value_containing_an_apostrophe_is_untouched() -> None:
    assert parse('cast:"Josh O\'Connor"').terms[0].values == ("Josh O'Connor",)


# --- asking somewhere else ----------------------------------------------------------------
def _chain() -> tuple[Work, ...]:
    """Dune, its sequel, and the sequel of that — a path to walk down."""
    dune = Work(title="Dune", years=(2021,))
    two = Work(title="Part Two", years=(2024,), sequel_of=(dune,))
    three = Work(title="Part Three", years=(2026,), sequel_of=(two,))
    return dune, two, three


def test_a_clause_can_ask_its_question_of_the_row_an_edge_points_at() -> None:
    """`sequel-of.year:2021` is a question about the predecessor, asked from here."""
    assert keep("sequel-of.year:2021", *_chain()) == ["Part Two"]
    assert keep("sequel-of.name:dune", *_chain()) == ["Part Two"]
    assert keep("sequel-to.name:dune", *_chain()) == ["Part Two"]  # an alias is a hop too
    assert keep("sequel-of.year:<2000", *_chain()) == []


def test_a_path_composes() -> None:
    """Two hops, and the second is asked of wherever the first arrived."""
    assert keep("sequel-of.sequel-of.year:2021", *_chain()) == ["Part Three"]
    # and a hop that leads nowhere leads nowhere, rather than falling back to here
    assert keep("sequel-of.sequel-of.sequel-of.year:2021", *_chain()) == []


def test_a_path_can_ask_about_absence_over_there() -> None:
    assert keep("sequel-of.year:none", Work(title="X", sequel_of=(Work(title="Y"),))) == ["X"]


def test_a_path_renders_back_the_way_it_was_written() -> None:
    for source in ("sequel-of.year:<2020", "sequel-of.sequel-of.name:dune", "-prequel-of.kind:tv"):
        assert render(parse(source).expr, SCHEMA) == source


def test_a_dotted_key_that_is_not_a_path_is_a_title() -> None:
    """All or nothing, and that is the never-fail rule rather than strictness."""
    assert parse("a.b:c").terms[0].field == "name"
    assert parse("sequel-of.nonsense:c").terms[0].field == "name"
    assert parse("nonsense.year:2021").terms[0].field == "name"
    assert parse("sequel-of:dune").terms[0].field == "name"  # a relation asks nothing alone


def test_two_clauses_asking_in_different_places_do_not_merge() -> None:
    """Repeated keys OR together, and a path is a different key however it ends."""
    parsed = parse("kind:tv sequel-of.kind:movie")
    assert len(parsed.terms) == 2
    assert {t.via for t in parsed.terms} == {(), ("sequel-of",)}


def test_relation_names_complete_as_a_step() -> None:
    picks = suggest("seq", 3, SCHEMA)
    assert [(p.label, p.detail) for p in picks] == [("sequel-of.", "relation")]


def test_completion_continues_along_a_path() -> None:
    assert [p.insert for p in suggest("sequel-of.ye", 12, SCHEMA)] == ["sequel-of.year:"]
    picks = suggest("-sequel-of.genre:hor", 20, SCHEMA, _VOCAB)
    assert picks[0].insert == "-sequel-of.genre:horror"


def test_a_dotted_title_does_not_complete() -> None:
    assert suggest("Mr.Rob", 6, SCHEMA) == ()


# --- asking about absence -------------------------------------------------------------------
def test_a_field_can_be_asked_for_the_rows_that_have_nothing_under_it() -> None:
    """The question `-tag:x` cannot put.

    Negating a value asks "not this one", and a row with no tags answers yes to that as surely
    as a row tagged comedy does. That left the other question — which of these has no tags at
    all — unaskable.
    """
    tagged = Work(title="Weapons", genres=("horror",))
    bare = Work(title="Meagen")
    assert keep("tag:none", tagged, bare) == ["Meagen"]
    assert keep("-tag:none", tagged, bare) == ["Weapons"]


def test_the_word_in_quotes_is_still_a_value() -> None:
    """A reserved word with no way to mean itself is a word taken out of the data."""
    named = Work(title="Nothing", genres=("none",))
    bare = Work(title="Meagen")
    assert keep('tag:"none"', named, bare) == ["Nothing"]
    assert render(parse('tag:"none"').expr, SCHEMA) == 'tag:"none"'
    assert render(parse("tag:none").expr, SCHEMA) == "tag:none"


def test_absence_is_one_more_alternative_among_the_values() -> None:
    """`tag:none,horror` is untagged *or* tagged horror — the same OR every value list is."""
    horror = Work(title="Weapons", genres=("horror",))
    comedy = Work(title="Barbie", genres=("comedy",))
    bare = Work(title="Meagen")
    assert keep("tag:none,horror", horror, comedy, bare) == ["Weapons", "Meagen"]
    # and it merges across clauses the way any repeated key does
    assert keep("tag:none tag:horror", horror, comedy, bare) == ["Weapons", "Meagen"]


def test_a_flag_has_no_absence_to_ask_about() -> None:
    assert keep("is:none", Work(title="Weapons")) == []


# --- alternatives and groups -------------------------------------------------------------
def test_or_keeps_a_row_that_satisfies_either_side() -> None:
    tv, film, game = (
        Work(title="Reacher", kind="tv"),
        Work(title="Dune", kind="movie"),
        Work(title="Hollow Knight", kind="game"),
    )
    assert keep("kind:tv OR kind:movie", tv, film, game) == ["Reacher", "Dune"]
    assert keep("kind:tv | kind:game", tv, film, game) == ["Reacher", "Hollow Knight"]


def test_a_key_written_twice_offers_alternatives() -> None:
    """OR within a key, AND across keys — a row has one kind, so AND would match nothing."""
    assert parse("kind:tv kind:movie").terms == (Term("kind", ("tv", "movie")),)
    assert render(parse("kind:tv kind:movie").expr, SCHEMA) == "kind:tv,movie"


def test_or_binds_tighter_than_juxtaposition() -> None:
    """`a OR b c` is `(a OR b) and c` — the reading a search bar wants, not logic's."""
    watched_tv = Work(title="Reacher", kind="tv", state="watched")
    fresh_film = Work(title="Dune", kind="movie")
    assert keep("kind:tv OR kind:movie -state:watched", watched_tv, fresh_film) == ["Dune"]


def test_brackets_override_the_default_reading() -> None:
    watched_tv = Work(title="Reacher", kind="tv", state="watched")
    fresh_film = Work(title="Dune", kind="movie")
    kept = keep("kind:tv OR (kind:movie -state:watched)", watched_tv, fresh_film)
    assert kept == ["Reacher", "Dune"]


def test_a_negated_group() -> None:
    rows = (Work(title="A", kind="tv", years=(2026,)), Work(title="B", kind="tv"))
    assert keep("-(kind:tv year:2026)", *rows) == ["B"]
    assert render(parse("-(kind:tv year:2026)").expr, SCHEMA) == "-(kind:tv year:2026)"


def test_a_bracket_only_closes_a_group_that_is_open() -> None:
    """Which is what keeps a value that merely contains brackets from being torn apart."""
    assert parse("title:(2021)").terms[0].values == ("(2021)",)
    assert parse('"Fallout (TV)"').terms[0].values == ("Fallout (TV)",)


def test_a_quoted_or_is_a_title_rather_than_an_operator() -> None:
    assert parse('"OR"').terms[0].values == ("OR",)
    expr = parse("a OR b").expr
    assert isinstance(expr, And)
    assert isinstance(expr.parts[0], Or)


@pytest.mark.parametrize(
    ("source", "fault", "pointed"),
    [
        ("(kind:tv", Fault.UNCLOSED_GROUP, "("),
        ("kind:tv)", Fault.STRAY_CLOSE, ")"),
        ("kind:tv OR", Fault.DANGLING_OR, "OR"),
        ("year:soon", Fault.NOT_A_NUMBER, "year:soon"),
        ("(year:soon", Fault.NOT_A_NUMBER, "year:soon"),
        ('cast:"unclosed', Fault.UNCLOSED_QUOTE, '"unclosed'),
        ("nonsense:x", Fault.UNKNOWN_FIELD, "nonsense"),
        ("kind:tv nonsense:x", Fault.UNKNOWN_FIELD, "nonsense"),
        ("kind:", Fault.EMPTY_VALUE, "kind:"),
        ("(" * 40, Fault.TOO_NESTED, "("),
    ],
)
def test_a_malformed_query_is_reported_rather_than_refused(
    source: str, fault: Fault, pointed: str
) -> None:
    """Half-typed is the normal state of a query bar, so nothing here is an error.

    The clause still degrades to the most useful reading; the reason is carried out with the
    tree instead of being dropped on the floor, with the span of what it is about.
    """
    parsed = parse(source)
    found = next(d for d in parsed.diagnostics if d.fault is fault)
    assert found.render()
    assert source[found.start : found.end] == pointed


def test_a_non_number_narrows_instead_of_vanishing() -> None:
    """`kind:tv year:soon` must not come back with every year."""
    assert keep("kind:tv year:soon", Work(years=(2026,))) == []


def test_the_notice_is_capped_for_a_status_line() -> None:
    notice = parse("a:1 b:2 c:3").notice
    assert notice.endswith("· +1")
    assert parse("kind:tv").notice == ""


def test_without_clears_a_tab_and_keeps_everything_else() -> None:
    q = parse("is:upcoming,airing tag:drama -kind:tv")
    assert without(q, "is", among=("upcoming", "released")) == "is:airing tag:drama -kind:tv"
    assert without(parse("is:upcoming"), "is", among=("upcoming", "released")) == ""
    assert without(parse("(is:upcoming OR tag:x) tag:y"), "is") == "(is:upcoming OR tag:x) tag:y", (
        "a disjunction pins nothing"
    )


@pytest.mark.parametrize(
    "source",
    [
        "title:проект",
        "title:Ünïcode",
        "title:備份",
        "title:café",
        "title:🚀",
        "title:a—b",
        "title:ＤＵＮＥ",
    ],
)
def test_text_in_any_script_is_a_value_not_a_warning(source: str) -> None:
    """Only ASCII punctuation can become grammar; a word in Cyrillic or an emoji never will."""
    assert parse(source).diagnostics == ()
