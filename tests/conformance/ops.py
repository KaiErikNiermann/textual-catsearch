"""One case in, one JSON answer out: the operations the spec holds both implementations to.

``js/test/harness/ops.ts`` is the TypeScript twin and must answer every case identically. A
case is ``{"op": <name>, ...arguments}``; offsets in and out are code points, as Python counts
them (the TypeScript harness converts to and from UTF-16). Numbers JSON cannot carry
(infinities, NaN) are written as strings, so a range read from ``took:>1e999`` survives.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from conformance.schemas import SchemaName, rows, schema, vocabulary
from textual_catsearch import (
    And,
    Diagnostic,
    Expr,
    Not,
    NumRange,
    Or,
    Suggestion,
    Term,
    active_span,
    apply,
    fold,
    lex,
    parse,
    pinned,
    quote,
    rank_values,
    render,
    suggest,
    with_term,
    without,
)
from textual_catsearch.parser import open_groups
from textual_catsearch.text import word_prefixed

__all__ = ["OPS", "decode_expr", "encode_expr", "run"]

type Json = Any
type Case = Mapping[str, Json]


# --- encoding ------------------------------------------------------------------------------
def number(n: float) -> Json:
    """A bound as JSON: a finite float, or a string for what JSON cannot write."""
    if isinstance(n, int):
        try:
            n = float(n)
        except OverflowError:
            return "inf" if n > 0 else "-inf"
    if math.isnan(n):
        return "nan"
    if math.isinf(n):
        return "inf" if n > 0 else "-inf"
    return n


def _unnumber(n: Json) -> float:
    return float(n) if isinstance(n, str) else n


def _bound(n: float | None) -> Json:
    return None if n is None else number(n)


def _range(r: NumRange) -> Json:
    return {
        "lo": _bound(r.lo),
        "hi": _bound(r.hi),
        "loStrict": r.lo_strict,
        "hiStrict": r.hi_strict,
    }


def encode_expr(expr: Expr) -> Json:
    match expr:
        case Term():
            return {
                "kind": "term",
                "field": expr.field,
                "values": list(expr.values),
                "ranges": [_range(r) for r in expr.ranges],
                "negated": expr.negated,
                "absent": expr.absent,
                "via": list(expr.via),
            }
        case And(parts=parts):
            return {"kind": "and", "parts": [encode_expr(p) for p in parts]}
        case Or(parts=parts):
            return {"kind": "or", "parts": [encode_expr(p) for p in parts]}
        case Not(inner=inner):
            return {"kind": "not", "inner": encode_expr(inner)}


def decode_expr(data: Json) -> Expr:
    match data["kind"]:
        case "term":
            return Term(
                data["field"],
                tuple(data["values"]),
                tuple(
                    NumRange(
                        None if r["lo"] is None else _unnumber(r["lo"]),
                        None if r["hi"] is None else _unnumber(r["hi"]),
                        r["loStrict"],
                        r["hiStrict"],
                    )
                    for r in data["ranges"]
                ),
                data["negated"],
                data["absent"],
                tuple(data["via"]),
            )
        case "and":
            return And(tuple(decode_expr(p) for p in data["parts"]))
        case "or":
            return Or(tuple(decode_expr(p) for p in data["parts"]))
        case _:
            return Not(decode_expr(data["inner"]))


def _diagnostic(d: Diagnostic) -> Json:
    return {
        "fault": d.fault.value,
        "text": d.text,
        "start": d.start,
        "end": d.end,
        "reason": d.reason,
        "message": d.render(),
    }


def _suggestion(s: Suggestion) -> Json:
    return {
        "insert": s.insert,
        "label": s.label,
        "detail": s.detail,
        "start": s.start,
        "end": s.end,
        "kind": s.kind,
    }


# --- the operations ------------------------------------------------------------------------
def _name(case: Case) -> SchemaName:
    return case["schema"]


def _fold(case: Case) -> Json:
    return fold(case["text"])


def _fold_block(case: Case) -> Json:
    """Every code point in ``[start, end)`` folded alone: a digest, so a whole plane fits.

    Surrogates are skipped, and so are the ``unassigned`` ranges the case lists: what the
    reference's Unicode version had not assigned yet. Normalisation comes from the JS engine,
    whose Unicode may be newer, and a character the reference cannot know is no disagreement.
    """
    skip = [range(a, b + 1) for a, b in case.get("unassigned", ())]
    digest = hashlib.sha256()
    for cp in range(case["start"], case["end"]):
        if not 0xD800 <= cp <= 0xDFFF and not any(cp in r for r in skip):
            digest.update(fold(chr(cp)).encode("utf-8") + b"\n")
    return digest.hexdigest()


def _word_prefixed(case: Case) -> Json:
    return word_prefixed(case["value"], fold(case["needle"]))


def _lex(case: Case) -> Json:
    return [
        {"runs": [[text, quoted] for text, quoted in t.body.runs], "start": t.start, "end": t.end}
        for t in lex(case["source"])
    ]


def _active_span(case: Case) -> Json:
    return list(active_span(case["source"], case["cursor"]))


def _parse(case: Case) -> Json:
    s = schema(_name(case))
    query = parse(case["source"], s, empty_as_text=case.get("emptyAsText", False))
    return {
        "expr": encode_expr(query.expr),
        "diagnostics": [_diagnostic(d) for d in query.diagnostics],
        "notice": query.notice,
        "rendered": render(query.expr, s),
        "text": query.text,
        "unknownFields": list(query.unknown_fields),
        "isEmpty": query.is_empty,
    }


def _match(case: Case) -> Json:
    name = _name(case)
    query = parse(case["source"], schema(name))
    return [i for i, row in enumerate(rows(name)) if query.matches(row)]


def _render(case: Case) -> Json:
    return render(decode_expr(case["expr"]), schema(_name(case)))


def _quote(case: Case) -> Json:
    return quote(case["value"], case.get("extra", ""))


def _suggest(case: Case) -> Json:
    name = _name(case)
    fields = case.get("fields")
    found = suggest(
        case["source"],
        case["cursor"],
        schema(name),
        vocabulary(name) if case.get("vocab", True) else None,
        limit=case.get("limit", 8),
        fields=None if fields is None else frozenset(fields),
    )
    return [{**_suggestion(s), "applied": apply(case["source"], s)} for s in found]


def _rank(case: Case) -> Json:
    name = _name(case)
    ranked = rank_values(
        schema(name), case["field"], vocabulary(name), case["needle"], limit=case.get("limit", 8)
    )
    return [[entry.value, entry.uses, detail] for entry, detail in ranked]


def _vocabulary(case: Case) -> Json:
    vocab = vocabulary(_name(case))
    return {
        "entries": [[k, [[e.value, e.uses] for e in v]] for k, v in vocab.entries.items()],
        "keys": [[e.value, e.uses] for e in vocab.keys],
    }


def _completions(case: Case) -> Json:
    name = _name(case)
    return [
        [entry.value, entry.uses, detail]
        for entry, detail in schema(name).completions(case["field"], vocabulary(name))
    ]


def _among(case: Case) -> Sequence[str] | None:
    return case.get("among")


def _pinned(case: Case) -> Json:
    query = parse(case["source"], schema(_name(case)))
    return pinned(query, case["field"], _among(case))


def _with_term(case: Case) -> Json:
    query = parse(case["source"], schema(_name(case)))
    term = decode_expr(case["term"])
    if not isinstance(term, Term):
        raise TypeError("with_term needs a term")
    return with_term(query, term, among=_among(case))


def _without(case: Case) -> Json:
    query = parse(case["source"], schema(_name(case)))
    return without(query, case["field"], among=_among(case))


def _open_groups(case: Case) -> Json:
    return open_groups(case["source"])


OPS: Mapping[str, Callable[[Case], Json]] = {
    "fold": _fold,
    "fold_block": _fold_block,
    "word_prefixed": _word_prefixed,
    "lex": _lex,
    "active_span": _active_span,
    "parse": _parse,
    "match": _match,
    "render": _render,
    "quote": _quote,
    "suggest": _suggest,
    "rank": _rank,
    "vocabulary": _vocabulary,
    "completions": _completions,
    "pinned": _pinned,
    "with_term": _with_term,
    "without": _without,
    "open_groups": _open_groups,
}


def run(case: Case) -> Json:
    """The reference answer to one case."""
    return OPS[case["op"]](case)
