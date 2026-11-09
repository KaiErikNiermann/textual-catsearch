/** Evaluation: does a query hold for a row? Pure and in-memory, cheap enough per keystroke. */

import { numbersOf, stringsOf } from "./schema.ts";
import type { Field, Schema } from "./schema.ts";
import { fold } from "./text.ts";
import { rangeContains } from "./tree.ts";
import type { Expr, NumRange, Term } from "./tree.ts";

/** Does an expression hold for this row? Structural recursion over the tree. */
export function holds<Row>(expr: Expr, row: Row, schema: Schema<Row>): boolean {
  switch (expr.kind) {
    case "term": {
      return matchTerm(expr, row, schema) !== expr.negated;
    }
    case "and": {
      return expr.parts.every((p) => holds(p, row, schema));
    }
    case "or": {
      return expr.parts.some((p) => holds(p, row, schema));
    }
    case "not": {
      return !holds(expr.inner, row, schema);
    }
  }
}

/** One clause, before negation. A field the schema does not have answers no, never yes. */
function matchTerm<Row>(term: Term, row: Row, schema: Schema<Row>): boolean {
  const spec = schema.field(term.field);
  if (spec === undefined) return false;
  if (term.via.length > 0) return walked(term.via, row, schema).some((r) => askedHere(term, spec, r));
  return askedHere(term, spec, row);
}

/** `tag:none,horror` asks both: is there nothing here, and is one of these values here. */
function askedHere<Row>(term: Term, spec: Field<Row>, row: Row): boolean {
  return (term.absent && hasNothing(spec, row)) || holdsValue(term, spec, row);
}

/** The rows a path arrives at, one hop per step, deduplicated by identity at every step. */
function walked<Row>(via: readonly string[], row: Row, schema: Schema<Row>): Row[] {
  let here = new Set<Row>([row]);
  for (const step of via) {
    const relation = schema.relations.get(step);
    if (relation === undefined) return [];
    const next = new Set<Row>();
    for (const current of here) for (const found of relation.follow(current)) next.add(found);
    if (next.size === 0) return [];
    here = next;
  }
  return [...here];
}

/** Does any of the clause's values match? Dispatched on the field's kind, exhaustively. */
function holdsValue<Row>(term: Term, spec: Field<Row>, row: Row): boolean {
  switch (spec.kind) {
    case "text": {
      return substring(term.values, stringsOf(spec.get(row)));
    }
    case "enum": {
      const { normalize } = spec;
      return equal(normalize === null ? term.values : term.values.map((v) => normalize(v)), stringsOf(spec.get(row)));
    }
    case "number": {
      return matchNum(term.ranges, numbersOf(spec.get(row)));
    }
    case "flag": {
      const wanted = new Set(term.values.map((v) => fold(v)));
      for (const [name, test] of spec.flags) if (wanted.has(fold(name)) && test(row)) return true;
      return false;
    }
    case "custom": {
      return spec.every
        ? term.values.length > 0 && term.values.every((v) => spec.test(row, v))
        : term.values.some((v) => spec.test(row, v));
    }
  }
}

function substring(needles: readonly string[], haystacks: readonly string[]): boolean {
  const hays = haystacks.map((h) => fold(h));
  return needles.some((n) => {
    const needle = fold(n);
    return hays.some((h) => h.includes(needle));
  });
}

function equal(needles: readonly string[], haystacks: readonly string[]): boolean {
  const hays = new Set(haystacks.map((h) => fold(h)));
  return needles.some((n) => hays.has(fold(n)));
}

function matchNum(ranges: readonly NumRange[], values: readonly number[]): boolean {
  return ranges.some((r) => values.some((n) => rangeContains(r, n)));
}

/** Does this row carry nothing at all under this field? Never for a flag field. */
function hasNothing<Row>(spec: Field<Row>, row: Row): boolean {
  switch (spec.kind) {
    case "text":
    case "enum": {
      return stringsOf(spec.get(row)).length === 0;
    }
    case "number": {
      return numbersOf(spec.get(row)).length === 0;
    }
    case "flag": {
      return false;
    }
    case "custom": {
      return spec.empty?.(row) ?? false;
    }
  }
}
