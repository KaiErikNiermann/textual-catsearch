"""Completion: what the token under the caret could become — a field name, or a value for one."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from textual_catsearch.lexer import QUOTE, active_span, separated
from textual_catsearch.parser import open_groups
from textual_catsearch.render import quote
from textual_catsearch.schema import Completions, Schema, VocabEntry, Vocabulary, unquoted
from textual_catsearch.text import fold, word_prefixed

__all__ = ["Suggestion", "apply", "rank_values", "suggest"]


@dataclass(frozen=True, slots=True)
class Suggestion:
    """One completion. Splice with :func:`apply`.

    ``kind`` says which half of the grammar it completes: a ``field`` suggestion turns a bare
    word into ``field:`` (or a relation into ``relation.``), a ``value`` suggestion fills in
    what follows the colon. The widget treats them differently — only a value completion is
    worth previewing, because only it narrows the result set rather than emptying it.
    """

    insert: str
    label: str
    detail: str
    start: int
    end: int
    kind: Literal["field", "value"] = "value"


def apply(source: str, suggestion: Suggestion) -> str:
    """``source`` with ``suggestion`` spliced over the token it was derived from."""
    return source[: suggestion.start] + suggestion.insert + source[suggestion.end :]


def rank_values[Row](
    schema: Schema[Row], field: str, vocab: Vocabulary, needle: str, *, limit: int = 8
) -> Completions:
    """The completable ``(value, detail)`` pairs for one field, best match first.

    ``needle`` is folded here, so it may be passed as typed. The ranking half of
    :func:`suggest`, public because the query bar is not the only place that completes a value:
    a form field for one of the same values wants the same candidates in the same order, and
    only differs in how it splices the answer back.
    """
    folded = fold(needle)
    pool = schema.completions(field, vocab)
    hits = [(e, d) for e, d in pool if word_prefixed(e.value, folded)]
    if not hits:  # nothing *starts* with it, so fall back to anywhere-in-the-value
        hits = [(e, d) for e, d in pool if folded in fold(e.value)]
    hits.sort(key=lambda ed: _rank(ed[0], folded))
    return tuple(hits[:limit])


def _rank(entry: VocabEntry, needle: str) -> tuple[bool, int, str]:
    """Whole-value prefix first, then the most used, then alphabetical."""
    return (not fold(entry.value).startswith(needle), -entry.uses, entry.value)


@dataclass(frozen=True, slots=True)
class _Slot:
    """Where a completion splices, and what it has to carry back in unchanged.

    ``prefix`` is whatever opens a group and whatever negates; ``stem`` is the path already
    walked (``parent.``). Both ride back out on the insertion, so completing inside
    ``(kind:tv -parent.ye`` splices into the group and the path rather than past them.
    ``caret`` is where the cursor sits in the source, which picks the segment of a comma list.
    """

    start: int
    end: int
    prefix: str
    stem: str
    caret: int


def suggest[Row](
    source: str,
    cursor: int,
    schema: Schema[Row],
    vocab: Vocabulary | None = None,
    *,
    limit: int = 8,
    fields: frozenset[str] | None = None,
) -> tuple[Suggestion, ...]:
    """Completions for the token under the cursor — field names, then values for that field.

    ``fields`` narrows which field and relation *names* are offered, defaulting to all of them:
    a box where some fields mean nothing can stop offering them. Values are unaffected — a
    field you managed to type still completes.

    Pure, so it is unit-testable without a terminal and reusable for shell completion.
    """
    start, end = active_span(source, cursor)
    end -= _closers(source, start, end)
    token = source[start:end]
    body = token.lstrip("(")
    negated = body[:1] in ("-", "!")
    head, sep, value = (body[1:] if negated else body).partition(":")
    walked, _, tail = head.rpartition(".")
    vocab = vocab or Vocabulary()
    prefix = token[: len(token) - len(body) + negated]
    if walked and any(schema.relation(piece) is None for piece in walked.split(".")):
        # A dotted key that is not a path is a name: one of the data's keys, if the schema
        # takes those, else nothing that completes.
        at = _Slot(start=start, end=end, prefix=prefix, stem="", caret=cursor)
        return _dotted(schema, head, sep, value, vocab, at, limit)
    at = _Slot(
        start=start, end=end, prefix=prefix, stem=head[: len(head) - len(tail)], caret=cursor
    )
    if not sep:
        offered = schema.names if fields is None else fields
        declared = _field_names(schema, tail, offered, at, limit)
        return (*declared, *_key_names(schema, tail, vocab, at, limit - len(declared)))
    spec = schema.field(tail)
    if spec is None:
        return ()
    return _field_values(schema, spec.name, value, vocab, at, limit)


def _closers(source: str, start: int, end: int) -> int:
    """How many of the ``)`` ending the token at ``[start, end)`` close a group.

    Those are grammar, not the value: ``(kind:mo)`` completes ``mo`` and keeps its bracket. A
    ``)`` with no group open is text — ``title:(2021)`` — and stays in, as the parser keeps it.
    """
    token = source[start:end]
    if token.count(QUOTE) % 2:  # inside an open quote, a bracket is a character
        return 0
    body = token.rstrip(")")
    return min(len(token) - len(body), open_groups(source[:start] + body))


def _field_names[Row](
    schema: Schema[Row], head: str, offered: frozenset[str], at: _Slot, limit: int
) -> tuple[Suggestion, ...]:
    """Name completions for a token with no colon in it yet: ``field:`` and ``relation.``."""
    needle = head.strip().strip(QUOTE).lower()
    names = sorted(n for n in offered if n.startswith(needle) and n != schema.bare)
    return tuple(_name_suggestion(name, name in schema.relations, at) for name in names[:limit])


def _key_names[Row](
    schema: Schema[Row], head: str, vocab: Vocabulary, at: _Slot, limit: int
) -> tuple[Suggestion, ...]:
    """The data's own keys a ``dynamic`` schema takes, after its declared names: most used
    first, those a declared name already covers left out."""
    if not schema.is_dynamic or limit <= 0:
        return ()
    needle = fold(head.strip().strip(QUOTE))
    keys = [
        entry
        for entry in vocab.keys
        if fold(entry.value).startswith(needle) and schema.declared(entry.value) is None
    ]
    keys.sort(key=lambda e: (-e.uses, e.value))
    return tuple(_key_suggestion(entry, at) for entry in keys[:limit])


def _key_suggestion(entry: VocabEntry, at: _Slot) -> Suggestion:
    written = f"{entry.value}:"
    return Suggestion(
        insert=f"{at.prefix}{written}",
        label=written,
        detail=f"key · {entry.uses}" if entry.uses else "key",
        start=at.start,
        end=at.end,
        kind="field",
    )


def _dotted[Row](
    schema: Schema[Row],
    head: str,
    sep: str,
    value: str,
    vocab: Vocabulary,
    at: _Slot,
    limit: int,
) -> tuple[Suggestion, ...]:
    """A dotted key that is no path: the data's key it begins, or that key's values."""
    if not schema.is_dynamic:
        return ()
    if not sep:
        return _key_names(schema, head, vocab, at, limit)
    spec = schema.dynamic_field(head)
    return () if spec is None else _field_values(schema, spec.name, value, vocab, at, limit)


def _name_suggestion(name: str, relation: bool, at: _Slot) -> Suggestion:
    written = f"{at.stem}{name}{'.' if relation else ':'}"
    return Suggestion(
        insert=f"{at.prefix}{written}",
        label=written,
        detail="relation" if relation else "field",
        start=at.start,
        end=at.end,
        kind="field",
    )


def _field_values[Row](
    schema: Schema[Row], field: str, value: str, vocab: Vocabulary, at: _Slot, limit: int
) -> tuple[Suggestion, ...]:
    """Value completions for the segment of a comma list the caret is in.

    Only that segment is quoted. Quoting the whole accumulated list instead turned
    ``tag:horror,body h`` into ``tag:"horror,body horror"`` — one value with a comma in it,
    which is the opposite of the two the user was building, and unrecoverable without deleting
    the quotes by hand. What they already typed on either side rides back out exactly as typed.

    The segment is the one under the caret rather than the last one, so going back to fix
    ``hor`` in ``tag:hor,myst`` completes ``hor``; and only an unquoted comma ends one, so the
    comma in ``cast:"Smith, Jo`` is part of the name being typed.
    """
    spec = schema.field(field)
    if spec is None:
        return ()
    # `value` is the tail of the token, so this is the caret's offset into it — clamped, since a
    # caret back in the field name still completes the value, and the spans cover [0, len].
    caret = max(0, min(at.caret - (at.end - len(value)), len(value)))
    lo, hi = next(span for span in separated(value, ",") if span[0] <= caret <= span[1])
    lead, segment, rest = value[:lo], value[lo:hi], value[hi:]
    extra = unquoted(spec)
    return tuple(
        Suggestion(
            insert=f"{at.prefix}{at.stem}{field}:{lead}{quote(entry.value, extra)}{rest}",
            label=entry.value,
            detail=f"{detail} · {entry.uses}" if entry.uses else detail,
            start=at.start,
            end=at.end,
        )
        for entry, detail in rank_values(
            schema, field, vocab, segment.strip().strip(QUOTE), limit=limit
        )
    )
