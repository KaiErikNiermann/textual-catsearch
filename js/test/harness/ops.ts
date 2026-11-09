/**
 * One case in, one JSON answer out: the twin of `tests/conformance/ops.py`, answering every
 * case exactly as the Python reference does. Offsets in cases and answers are code points, as
 * Python counts them; the library works in UTF-16 code units, converted here at the edge.
 */

import { createHash } from "node:crypto";

import {
  activeSpan,
  apply,
  describe as describeDiagnostic,
  fold,
  lex,
  openGroups,
  parse,
  pinned,
  quote,
  rankValues,
  render,
  suggest,
  withTerm,
  without,
  wordPrefixed,
} from "../../src/index.ts";
import type { Diagnostic, Expr, NumRange, Query, Schema, Suggestion, Term } from "../../src/index.ts";
import { SCHEMA_NAMES, rowsOf, schemaOf, vocabularyOf } from "./schemas.ts";
import type { SchemaName } from "./schemas.ts";

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type Case = { readonly op: string } & Readonly<Record<string, Json>>;

// --- offsets --------------------------------------------------------------------------------
/** A code point offset into `text` as a UTF-16 offset. */
export function toUnits(text: string, codePoints: number): number {
  let units = 0;
  let seen = 0;
  for (const ch of text) {
    if (seen >= codePoints) break;
    units += ch.length;
    seen++;
  }
  return units;
}

/** A UTF-16 offset into `text` as a code point offset. */
export function toCodePoints(text: string, units: number): number {
  let at = 0;
  let seen = 0;
  for (const ch of text) {
    if (at >= units) break;
    at += ch.length;
    seen++;
  }
  return seen;
}

// --- encoding ---------------------------------------------------------------------------------
// A bound is a number, or the string JSON writes in its place: two types on purpose.
// eslint-disable-next-line sonarjs/function-return-type
function number(n: number | null): Json {
  if (n === null) return null;
  if (Number.isNaN(n)) return "nan";
  if (n === Infinity) return "inf";
  if (n === -Infinity) return "-inf";
  return n;
}

function unnumber(n: Json): number | null {
  if (n === null) return null;
  if (n === "nan") return NaN;
  if (n === "inf") return Infinity;
  if (n === "-inf") return -Infinity;
  return n as number;
}

function encodeRange(r: NumRange): Json {
  return { lo: number(r.lo), hi: number(r.hi), loStrict: r.loStrict, hiStrict: r.hiStrict };
}

export function encodeExpr(expr: Expr): Json {
  switch (expr.kind) {
    case "term": {
      return {
        kind: "term",
        field: expr.field,
        values: [...expr.values],
        ranges: expr.ranges.map((r) => encodeRange(r)),
        negated: expr.negated,
        absent: expr.absent,
        via: [...expr.via],
      };
    }
    case "and":
    case "or": {
      return { kind: expr.kind, parts: expr.parts.map((p) => encodeExpr(p)) };
    }
    case "not": {
      return { kind: "not", inner: encodeExpr(expr.inner) };
    }
  }
}

type JsonObject = Readonly<Record<string, Json>>;

function obj(data: Json | undefined): JsonObject {
  if (data === null || data === undefined || typeof data !== "object" || Array.isArray(data)) {
    throw new TypeError(`expected an object, got ${JSON.stringify(data)}`);
  }
  return data;
}

function list(data: Json | undefined): Json[] {
  if (!Array.isArray(data)) throw new TypeError(`expected a list, got ${JSON.stringify(data)}`);
  return data;
}

function str(data: Json | undefined): string {
  if (typeof data !== "string") throw new TypeError(`expected a string, got ${JSON.stringify(data)}`);
  return data;
}

function int(data: Json | undefined): number {
  if (typeof data !== "number") throw new TypeError(`expected a number, got ${JSON.stringify(data)}`);
  return data;
}

function strings(data: Json | undefined): string[] {
  return list(data).map((v) => str(v));
}

export function decodeExpr(data: Json): Expr {
  const o = obj(data);
  switch (o["kind"]) {
    case "term": {
      return {
        kind: "term",
        field: str(o["field"]),
        values: strings(o["values"]),
        ranges: list(o["ranges"]).map((raw) => {
          const r = obj(raw);
          return {
            lo: unnumber(r["lo"] ?? null),
            hi: unnumber(r["hi"] ?? null),
            loStrict: r["loStrict"] === true,
            hiStrict: r["hiStrict"] === true,
          };
        }),
        negated: o["negated"] === true,
        absent: o["absent"] === true,
        via: strings(o["via"]),
      };
    }
    case "and":
    case "or": {
      return { kind: o["kind"], parts: list(o["parts"]).map((p) => decodeExpr(p)) };
    }
    default: {
      return { kind: "not", inner: decodeExpr(o["inner"] ?? null) };
    }
  }
}

function encodeDiagnostic(source: string, d: Diagnostic): Json {
  return {
    fault: d.fault,
    text: d.text,
    start: toCodePoints(source, d.start),
    end: toCodePoints(source, d.end),
    reason: d.reason,
    message: describeDiagnostic(d),
  };
}

function encodeSuggestion(source: string, s: Suggestion): Json {
  return {
    insert: s.insert,
    label: s.label,
    detail: s.detail,
    start: toCodePoints(source, s.start),
    end: toCodePoints(source, s.end),
    kind: s.kind,
    applied: apply(source, s),
  };
}

// --- the operations ---------------------------------------------------------------------------
function nameOf(c: Case): SchemaName {
  const name = str(c["schema"]);
  const known = SCHEMA_NAMES.find((n) => n === name);
  if (known === undefined) throw new TypeError(`no schema ${name}`);
  return known;
}

// The harness runs one operation over three row types; the library's generics cannot see that
// a schema and its rows came from the same name, so the pairing is asserted here, once.
function schema(c: Case): Schema<unknown> {
  return schemaOf(nameOf(c)) as Schema<unknown>;
}

function parsed(c: Case): Query<unknown> {
  return parse(str(c["source"]), schema(c));
}

function among(c: Case): readonly string[] | undefined {
  const raw = c["among"];
  return raw === undefined || raw === null ? undefined : strings(raw);
}

function amongOptions(c: Case): { readonly among?: readonly string[] } {
  const values = among(c);
  return values === undefined ? {} : { among: values };
}

/** Every code point in the block folded alone, as a digest; surrogates and the reference's
 * unassigned code points skipped (see `_fold_block` in ops.py). */
function foldBlock(c: Case): Json {
  const skip = list(c["unassigned"] ?? []).map((r) => list(r).map((n) => int(n)));
  const digest = createHash("sha256");
  for (let cp = int(c["start"]); cp < int(c["end"]); cp++) {
    const surrogate = cp >= 0xD8_00 && cp <= 0xDF_FF;
    if (surrogate || skip.some(([a = 0, b = -1]) => a <= cp && cp <= b)) continue;
    digest.update(`${fold(String.fromCodePoint(cp))}\n`, "utf8");
  }
  return digest.digest("hex");
}

function parseOp(c: Case): Json {
  const source = str(c["source"]);
  const s = schema(c);
  const query = parse(source, s, { emptyAsText: c["emptyAsText"] === true });
  return {
    expr: encodeExpr(query.expr),
    diagnostics: query.diagnostics.map((d) => encodeDiagnostic(source, d)),
    notice: query.notice,
    rendered: render(query.expr, s),
    text: query.text,
    unknownFields: [...query.unknownFields],
    isEmpty: query.isEmpty,
  };
}

function suggestOp(c: Case): Json {
  const source = str(c["source"]);
  const name = nameOf(c);
  const fields = c["fields"];
  const found = suggest(
    source,
    toUnits(source, int(c["cursor"])),
    schema(c),
    c["vocab"] === false ? null : vocabularyOf(name),
    {
      limit: typeof c["limit"] === "number" ? c["limit"] : 8,
      fields: fields === undefined || fields === null ? null : strings(fields),
    },
  );
  return found.map((s) => encodeSuggestion(source, s));
}

function vocabularyOp(c: Case): Json {
  const vocab = vocabularyOf(nameOf(c));
  return {
    entries: [...vocab.entries].map(([k, v]) => [k, v.map((e) => [e.value, e.uses])]),
    keys: vocab.keys.map((e) => [e.value, e.uses]),
  };
}

const OPS: Readonly<Record<string, (c: Case) => Json>> = {
  fold: (c) => fold(str(c["text"])),
  fold_block: foldBlock,
  word_prefixed: (c) => wordPrefixed(str(c["value"]), fold(str(c["needle"]))),
  lex: (c) => {
    const source = str(c["source"]);
    return lex(source).map((t) => ({
      runs: t.body.runs.map(([text, quoted]) => [text, quoted]),
      start: toCodePoints(source, t.start),
      end: toCodePoints(source, t.end),
    }));
  },
  active_span: (c) => {
    const source = str(c["source"]);
    const [a, b] = activeSpan(source, toUnits(source, int(c["cursor"])));
    return [toCodePoints(source, a), toCodePoints(source, b)];
  },
  parse: parseOp,
  match: (c) => {
    const query = parsed(c);
    const kept: number[] = [];
    const rows = rowsOf(nameOf(c));
    for (const [i, row] of rows.entries()) if (query.matches(row)) kept.push(i);
    return kept;
  },
  render: (c) => render(decodeExpr(c["expr"] ?? null), schema(c)),
  quote: (c) => quote(str(c["value"]), typeof c["extra"] === "string" ? c["extra"] : ""),
  suggest: suggestOp,
  rank: (c) =>
    rankValues(
      schema(c),
      str(c["field"]),
      vocabularyOf(nameOf(c)),
      str(c["needle"]),
      typeof c["limit"] === "number" ? c["limit"] : 8,
    ).map(([e, detail]) => [e.value, e.uses, detail]),
  vocabulary: vocabularyOp,
  completions: (c) =>
    schema(c)
      .completions(str(c["field"]), vocabularyOf(nameOf(c)))
      .map(([e, detail]) => [e.value, e.uses, detail]),
  pinned: (c) => pinned(parsed(c), str(c["field"]), among(c)) ?? null,
  with_term: (c) => {
    const pin = decodeExpr(c["term"] ?? null);
    if (pin.kind !== "term") throw new TypeError("with_term needs a term");
    return withTerm(parsed(c), pin satisfies Term, amongOptions(c));
  },
  without: (c) => without(parsed(c), str(c["field"]), amongOptions(c)),
  open_groups: (c) => openGroups(str(c["source"])),
};

/** This implementation's answer to one case. */
export function run(c: Case): Json {
  const op = OPS[c.op];
  if (op === undefined) throw new Error(`no operation ${c.op}`);
  return op(c);
}

/** Equality of two JSON answers: numbers by value (so `-0` is `0`, as Python's `==` has it). */
export function sameJson(a: Json | undefined, b: Json | undefined): boolean {
  if (a === b) return true;
  if (Array.isArray(a)) return Array.isArray(b) && a.length === b.length && a.every((v, i) => sameJson(v, b[i]));
  if (a === null || b === null || typeof a !== "object" || typeof b !== "object" || Array.isArray(b)) return false;
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every((k) => sameJson(a[k], b[k]));
}
