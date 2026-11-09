/** Rendering: a tree written back out in the language it was parsed from. */

import { QUOTE } from "./lexer.ts";
import { parse, reserved } from "./parser.ts";
import { NOTHING, OR_WORDS } from "./query.ts";
import { unquoted } from "./schema.ts";
import type { Schema } from "./schema.ts";
import { and, exprEquals } from "./tree.ts";
import type { Expr, Term } from "./tree.ts";
import { casefold, isSpace } from "./unicode.ts";

const SEPARATORS = new Set([",", ":", "(", ")"]);

function signed(value: string): boolean {
  return value.startsWith("-") || value.startsWith("!");
}

/**
 * A field value in quotes unless it is spelled in the language's own alphabet.
 *
 * The alphabet is `[A-Za-z0-9_-]` plus the operators the field declares (`extra`); everything
 * else is quoted, so the grammar can claim more punctuation later without changing what any
 * saved query means. Exported because anything composing a query out of data needs this one
 * answer, not its own guess.
 */
export function quote(value: string, extra = ""): string {
  const plain =
    value.length > 0 &&
    !OR_WORDS.has(value) &&
    casefold(value) !== NOTHING && // else `tag:"none"` would come back as a question
    !signed(value) && // a leading `-` or `!` negates
    !reserved(value, extra);
  return plain ? value : wrapped(value);
}

/** A bare word, quoted only where writing it bare would not read back as one word. */
function loose(value: string): string {
  const unsafe =
    OR_WORDS.has(value) || signed(value) || [...value].some((c) => isSpace(c) || SEPARATORS.has(c) || c === QUOTE);
  return unsafe ? wrapped(value) : value;
}

/** In quotes, with any quote of its own doubled: the one escape the language has. */
function wrapped(value: string): string {
  return `${QUOTE}${value.replaceAll(QUOTE, '""')}${QUOTE}`;
}

// How tightly each node binds, so a child is bracketed exactly when bare would read otherwise.
const LOOSEST = 0;
const CONJUNCTION = 1;
const ALTERNATION = 2;
const ATOM = 3;

/**
 * An expression, written back out in the language it was parsed from.
 *
 * The inverse of `parse`: `parse(render(e))` is `e` for every expression `parse` can produce,
 * which is what lets a query be transformed as a tree rather than string-edited.
 */
export function render<Row>(expr: Expr, schema: Schema<Row>): string {
  return renderAt(expr, LOOSEST, schema);
}

function renderAt<Row>(expr: Expr, floor: number, schema: Schema<Row>): string {
  const [text, binds] = written(expr, schema);
  if (!text) return floor > LOOSEST ? "()" : ""; // `a OR ()` must not lose its group
  return binds < floor ? `(${text})` : text;
}

function written<Row>(expr: Expr, schema: Schema<Row>): readonly [string, number] {
  switch (expr.kind) {
    case "term": {
      return [renderTerm(expr, schema), ATOM];
    }
    case "not": {
      return [`-(${renderAt(expr.inner, LOOSEST, schema)})`, ATOM];
    }
    case "or": {
      return [expr.parts.map((p) => renderAt(p, ATOM, schema)).join(" OR "), ALTERNATION];
    }
    case "and": {
      const parts = expr.parts.map((p) => renderAt(p, ALTERNATION, schema)).filter((r) => r.length > 0);
      return [parts.join(" "), CONJUNCTION];
    }
  }
}

function renderTerm<Row>(t: Term, schema: Schema<Row>): string {
  const sign = t.negated ? "-" : "";
  const spec = schema.field(t.field);
  const extra = spec === undefined ? "" : unquoted(spec);
  // `none` leads, so `tag:horror,none` and `tag:none,horror` write back as one spelling.
  const body = [...(t.absent ? [NOTHING] : []), ...t.values.map((v) => quote(v, extra))].join(",");
  // A path always writes its key out, the bare field included.
  if (t.via.length > 0 || t.field !== schema.bare) return `${sign}${[...t.via, t.field].join(".")}:${body}`;
  const bare = `${sign}${t.values.map((v) => loose(v)).join(",")}`;
  return readsBack(bare, t, schema) ? bare : `${sign}${t.field}:${body}`;
}

/** Would this clause, written without its field name, come back as the same clause? The
 * renderer reads its own output back rather than enumerate the ways bare text can look like
 * syntax (`name:a,b` bare is one value; `name:kind:tv` bare is a kind filter). */
function readsBack<Row>(bare: string, t: Term, schema: Schema<Row>): boolean {
  return exprEquals(parse(bare, schema).expr, and([t]));
}
