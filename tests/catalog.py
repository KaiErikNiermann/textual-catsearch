"""A small media catalogue schema the test suite queries — every field kind, and relations.

Shared rather than copied: the example tests exercise the language by example and the
property tests by generation, and a schema that differed between the two would make a
property failure impossible to reproduce from an example.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from textual_catsearch import (
    CustomField,
    EnumField,
    FlagField,
    NumberField,
    Relation,
    Schema,
    TextField,
    parse,
)
from textual_catsearch.text import fold

__all__ = ["BUCKETS", "FLAGS", "KINDS", "SCHEMA", "STATES", "Work", "keep"]

KINDS = ("movie", "tv", "game")
STATES = ("want", "watching", "watched", "dropped")
BUCKETS = ("available", "upcoming", "watched", "shelved")

_KIND_ALIASES = {"film": "movie", "films": "movie", "show": "tv", "tv-show": "tv", "series": "tv"}


@dataclass(frozen=True, slots=True)
class Work:
    """A row, with defaults for everything but what a test cares about."""

    title: str = "Reacher: Season 3"
    aliases: tuple[str, ...] = ()
    kind: str = "tv"
    years: tuple[int, ...] = ()
    season: int | None = None
    genres: tuple[str, ...] = ()
    themes: tuple[str, ...] = ()
    cast: tuple[str, ...] = ()
    director: tuple[str, ...] = ()
    state: str = "want"
    bucket: str = "available"
    freshness: str = "fresh"
    blockers: tuple[str, ...] = ()
    early_access: bool = False
    # (service, markets) — `platform:netflix@us` asks about one pair, not the cross product
    platforms: tuple[tuple[str, tuple[str, ...]], ...] = ()
    sequel_of: tuple[Work, ...] = ()
    prequel_of: tuple[Work, ...] = ()


def _canonical_kind(value: str) -> str:
    key = value.strip().lower()
    return _KIND_ALIASES.get(key, key)


def _on_platform(w: Work, value: str) -> bool:
    """``netflix@us`` -> on Netflix *in the US*; ``netflix`` -> anywhere; ``@us`` -> anything there."""
    name, _, market = value.rpartition("@") if "@" in value else (value, "", "")
    return any(
        fold(name) in fold(service) and (not market or market.upper() in markets)
        for service, markets in w.platforms
    )


def _bucket(name: str) -> Callable[[Work], bool]:
    return lambda w: w.bucket == name


FLAGS: Mapping[str, Callable[[Work], bool]] = {
    **{b: _bucket(b) for b in BUCKETS},
    "blocked": lambda w: bool(w.blockers),
    "dated": lambda w: bool(w.years),
    "tba": lambda w: not w.years,
    "fresh": lambda w: w.freshness == "fresh",
    "aging": lambda w: w.freshness == "aging",
    "stale": lambda w: w.freshness == "stale",
    "early-access": lambda w: w.early_access,
}

SCHEMA: Schema[Work] = Schema(
    [
        TextField("name", lambda w: (w.title, *w.aliases), aliases=("title",), complete=False),
        EnumField("kind", lambda w: w.kind, choices=KINDS, normalize=_canonical_kind),
        NumberField("year", lambda w: w.years),
        NumberField("season", lambda w: w.season),
        TextField("tag", lambda w: (*w.genres, *w.themes)),
        TextField("genre", lambda w: w.genres),
        TextField("theme", lambda w: w.themes),
        TextField("cast", lambda w: w.cast, aliases=("actors", "actor")),
        TextField("director", lambda w: w.director),
        TextField("person", lambda w: (*w.director, *w.cast)),
        EnumField("state", lambda w: w.state, choices=STATES),
        FlagField("is", FLAGS, detail="flag"),
        CustomField(
            "platform",
            _on_platform,
            aliases=("on",),
            unquoted="@",
            empty=lambda w: not w.platforms,
        ),
    ],
    bare="name",
    relations=[
        Relation("sequel-of", lambda w: w.sequel_of, aliases=("sequel-to",)),
        Relation("prequel-of", lambda w: w.prequel_of, aliases=("prequel-to",)),
    ],
)


def keep(source: str, *rows: Work) -> list[str]:
    """The titles a query keeps, in order."""
    return [r.title for r in parse(source, SCHEMA).filter(rows)]
