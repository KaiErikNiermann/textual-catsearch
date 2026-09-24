"""The schema: what a declaration accepts, refuses, and derives."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from catalog import BUCKETS, SCHEMA, Work
from textual_catsearch import (
    CustomField,
    EnumField,
    FlagField,
    NumberField,
    Relation,
    Schema,
    Term,
    TextField,
    VocabEntry,
    Vocabulary,
    parse,
    pinned,
    with_term,
)
from textual_catsearch.schema import numbers_of, strings_of


@dataclass(frozen=True, slots=True)
class Book:
    title: str
    author: str = ""


def _title() -> TextField[Book]:
    return TextField("title", lambda b: b.title)


# --- declaration -----------------------------------------------------------------------------
def test_a_name_claimed_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="claimed twice"):
        Schema([_title(), TextField("title", lambda b: b.author)], bare="title")


def test_an_alias_may_not_shadow_a_field() -> None:
    """Alias resolution runs first, so the shadowed field would become unreachable."""
    with pytest.raises(ValueError, match="shadows"):
        Schema(
            [_title(), TextField("author", lambda b: b.author, aliases=("title",))], bare="title"
        )


def test_an_alias_claimed_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="alias claimed twice"):
        Schema[Book](
            [
                TextField("title", lambda b: b.title, aliases=("t",)),
                TextField("author", lambda b: b.author, aliases=("t",)),
            ],
            bare="title",
        )


def test_a_relation_and_a_field_share_one_namespace() -> None:
    with pytest.raises(ValueError, match="claimed twice"):
        Schema([_title()], bare="title", relations=[Relation("title", lambda _: ())])


@pytest.mark.parametrize("name", ["Title", "a.b", "a:b", "-neg", "", "with space"])
def test_a_name_must_be_typeable_as_a_key(name: str) -> None:
    """Keys are lowercased on the way in, `.` steps a path, `:` ends a key, `-` negates."""
    with pytest.raises(ValueError, match="must match"):
        Schema([_title(), TextField(name, lambda b: b.author)], bare="title")


def test_bare_words_need_a_text_field_to_search() -> None:
    with pytest.raises(ValueError, match="bare field"):
        Schema([_title()], bare="nope")
    with pytest.raises(ValueError, match="bare field"):
        Schema([_title(), NumberField("year", lambda _: 1)], bare="year")


def test_lookups_resolve_aliases_and_case() -> None:
    assert SCHEMA.canonical("ACTORS") == "cast"
    field = SCHEMA.field("Actor")
    assert field is not None and field.name == "cast"
    relation = SCHEMA.relation("sequel-to")
    assert relation is not None and relation.name == "sequel-of"
    assert SCHEMA.field("nope") is None


# --- accessors -------------------------------------------------------------------------------
def test_a_lone_string_is_one_value_not_its_characters() -> None:
    """`lambda b: b.title` is the commonest accessor, and iterating it would match every title
    containing an `e` against `title:e`."""
    assert strings_of("Dune") == ("Dune",)
    assert strings_of(("a", "", "b")) == ("a", "b")
    assert strings_of(None) == ()
    assert strings_of("") == ()
    assert numbers_of(3) == (3,)
    assert numbers_of([1, 2]) == (1, 2)
    assert numbers_of(None) == ()


def test_a_single_valued_accessor_matches_as_a_whole() -> None:
    schema = Schema([_title()], bare="title")
    assert parse("title:x", schema).filter([Book("Dune")]) == []


# --- vocabulary ------------------------------------------------------------------------------
def test_the_vocabulary_is_derived_from_the_rows() -> None:
    rows = [
        Work(title="A", genres=("Horror",), cast=("Ann",)),
        Work(title="B", genres=("horror", "Comedy")),
        Work(title="C", genres=("Comedy", "comedy", "horror")),
    ]
    vocab = SCHEMA.vocabulary(rows)
    # counted once per row, spellings that fold together are one entry under the first spelling
    assert vocab.of("genre") == (VocabEntry("Horror", 3), VocabEntry("Comedy", 2))
    assert vocab.of("cast") == (VocabEntry("Ann", 1),)
    assert vocab.of("name") == ()  # `complete=False`
    assert vocab.of("year") == ()  # numbers are not listed


def test_choices_follow_the_values_rows_actually_carry() -> None:
    vocab = SCHEMA.vocabulary([Work(kind="tv"), Work(kind="tv"), Work(kind="game")])
    ranked = [e for e, _ in SCHEMA.completions("kind", vocab)]
    assert ranked == [VocabEntry("tv", 2), VocabEntry("game", 1), VocabEntry("movie")]


def test_flags_complete_from_their_own_table() -> None:
    names = [e.value for e, _ in SCHEMA.completions("is", Vocabulary())]
    assert set(BUCKETS) <= set(names)


def test_vocabularies_merge() -> None:
    a = Vocabulary({"tag": (VocabEntry("x", 2),)})
    b = Vocabulary({"tag": (VocabEntry("X", 9), VocabEntry("y")), "cast": (VocabEntry("z"),)})
    merged = a.merged(b)
    assert merged.of("tag") == (VocabEntry("x", 2), VocabEntry("y"))
    assert merged.of("cast") == (VocabEntry("z"),)


def test_an_enum_field_without_choices_still_completes_from_rows() -> None:
    schema = Schema([_title(), EnumField("author", lambda b: b.author)], bare="title")
    vocab = schema.vocabulary([Book("a", "Le Guin"), Book("b", "Le Guin"), Book("c", "Banks")])
    assert [e.value for e, _ in schema.completions("author", vocab)] == ["Le Guin", "Banks"]


def test_a_flag_field_needs_no_vocabulary() -> None:
    schema = Schema([_title(), FlagField("is", {"long": lambda b: len(b.title) > 5})], bare="title")
    assert parse("is:long", schema).filter([Book("Dune"), Book("Neuromancer")]) == [
        Book("Neuromancer")
    ]


# --- pinning a category ------------------------------------------------------------------------
def _pin(source: str, bucket: str) -> str:
    return with_term(parse(source, SCHEMA), Term("is", (bucket,)), among=BUCKETS)


def test_pinning_is_idempotent_and_preserves_other_terms() -> None:
    assert _pin("", "available") == "is:available"
    assert _pin("is:available x", "watched") == "is:watched x"
    assert _pin(_pin("tag:horror", "upcoming"), "upcoming") == "is:upcoming tag:horror"


def test_pinning_only_replaces_the_categories_named() -> None:
    """`is:blocked` is a flag, not a tab — pinning a bucket must leave it standing.

    Repeated keys are one clause, so it survives as an alternative beside the new bucket.
    """
    assert _pin("is:blocked is:available", "watched") == "is:watched,blocked"
    assert _pin("is:blocked", "watched") == "is:watched is:blocked"
    assert with_term(parse("is:blocked", SCHEMA), Term("is", ("tba",))) == "is:tba"


def test_the_pinned_value_is_read_off_the_conjunctive_core() -> None:
    """A category named inside a disjunction pins nothing — lighting a tab for it would say
    the view is narrower than it is."""
    assert pinned(parse("is:blocked is:upcoming x", SCHEMA), "is", BUCKETS) == "upcoming"
    assert pinned(parse("is:upcoming OR is:available", SCHEMA), "is", BUCKETS) is None
    assert pinned(parse("-is:upcoming", SCHEMA), "is", BUCKETS) is None
    assert pinned(parse("sequel-of.is:upcoming", SCHEMA), "is", BUCKETS) is None
    assert pinned(parse("is:blocked", SCHEMA), "is") == "blocked"


def test_bare_words_can_go_to_a_custom_field_with_its_own_matching() -> None:
    """A schema can give free text its own rule: here smart case, capitals exact."""

    def smart(row: str, word: str) -> bool:
        return word in row if any(c.isupper() for c in word) else word.lower() in row.lower()

    schema: Schema[str] = Schema([CustomField("text", smart)], bare="text")
    rows = ["Disk full", "disk ok"]
    assert parse("disk", schema).filter(rows) == rows
    assert parse("Disk", schema).filter(rows) == ["Disk full"]
    assert parse("-Disk", schema).filter(rows) == ["disk ok"]
