/**
 * Editing a query as a tree: pin a category, read which one is pinned.
 *
 * Category tabs ("all / unread / read") are sugar over the query language rather than separate
 * view state: one source of truth for what is on screen, and pressing a tab teaches the syntax
 * by showing it in the bar.
 */

import type { Query } from "./query.ts";
import { render } from "./render.ts";
import { fold } from "./text.ts";
import { and } from "./tree.ts";
import type { Expr, Term } from "./tree.ts";

function topLevel(expr: Expr): readonly Expr[] {
  return expr.kind === "and" ? expr.parts : [expr];
}

/** Is a value one of the categories (any value at all when `among` is not given)? Compared as
 * matching compares, so `category:cafe` lights the *Café* tab. */
function category(among: Iterable<string> | undefined): (value: string) => boolean {
  if (among === undefined) return () => true;
  const folded = new Set([...among].map((v) => fold(v)));
  return (value) => folded.has(fold(value));
}

/** A positive clause asking about `field` of this row, not of one a path reaches. */
function here(t: Term, field: string): boolean {
  return t.field === field && !t.negated && t.via.length === 0;
}

/** The value the query pins `field` to, or `undefined`. Only the conjunctive core counts. */
export function pinned<Row>(query: Query<Row>, field: string, among?: Iterable<string>): string | undefined {
  const isCategory = category(among);
  for (const part of topLevel(query.expr)) {
    if (!(part.kind === "term" && here(part, field))) {
      continue;
    }

    const found = part.values.find((v) => isCategory(v));
    if (found !== undefined) return found;
  }
  return undefined;
}

export interface AmongOptions {
  /** Restrict to these values (the tabs); other values in the same clause ride along. */
  readonly among?: Iterable<string>;
}

/** The query rewritten so `pin` pins its field, every other clause left intact. Source text. */
export function withTerm<Row>(query: Query<Row>, pin: Term, options: AmongOptions = {}): string {
  const isCategory = category(options.among);
  const others: string[] = [];
  const kept: Expr[] = [];
  for (const part of topLevel(query.expr)) {
    if (part.kind === "term" && here(part, pin.field) && part.values.some((v) => isCategory(v))) {
      others.push(...part.values.filter((v) => !isCategory(v)));
    } else {
      kept.push(part);
    }
  }
  const values = [...new Set([...pin.values, ...others])];
  return render(and([{ ...pin, values }, ...kept]), query.schema);
}

/** The query with no pin on `field` (the "all" tab), every other clause left intact. */
export function without<Row>(query: Query<Row>, field: string, options: AmongOptions = {}): string {
  const isCategory = category(options.among);
  const kept: Expr[] = [];
  for (const part of topLevel(query.expr)) {
    if (part.kind === "term" && here(part, field)) {
      const rest = part.values.filter((v) => !isCategory(v));
      if (rest.length > 0 || part.absent) kept.push({ ...part, values: rest });
      continue;
    }
    kept.push(part);
  }
  return render(and(kept), query.schema);
}
