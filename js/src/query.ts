/** A parsed query, what the parser noticed about it, and running it against rows. */

import { holds } from "./evaluate.ts";
import type { Schema } from "./schema.ts";
import { and, exprEquals } from "./tree.ts";
import type { Expr, Term } from "./tree.ts";

/** How many things a status line says at once before it says "and more". */
const MAX_NOTICES = 2;

/** How deep groups may nest; past it the brackets are read as text. */
export const MAX_GROUPS = 32;

export const OR_WORDS: ReadonlySet<string> = new Set(["OR", "|"]);

/** `tag:none` asks which rows carry no tags at all. `tag:"none"` is the tag. */
export const NOTHING = "none";

/** What a parse noticed but did not refuse. The language never rejects; it reports. */
export const Fault = {
  UNKNOWN_FIELD: "unknown-field",
  EMPTY_VALUE: "empty-value",
  NOT_A_NUMBER: "not-a-number",
  RESERVED: "reserved",
  UNCLOSED_QUOTE: "unclosed-quote",
  UNCLOSED_GROUP: "unclosed-group",
  STRAY_CLOSE: "stray-close",
  TOO_NESTED: "too-nested",
  DANGLING_OR: "dangling-or",
  INVALID_VALUE: "invalid-value",
} as const;

export type Fault = (typeof Fault)[keyof typeof Fault];

/** Something the parser noticed, and where: `[start, end)` in UTF-16 code units. */
export interface Diagnostic {
  readonly fault: Fault;
  /** The offending fragment, as typed. */
  readonly text: string;
  readonly start: number;
  readonly end: number;
  /** Why, in the field's words, where the fault alone does not say. */
  readonly reason: string;
}

export function diagnostic(fault: Fault, text: string, start: number, end: number, reason = ""): Diagnostic {
  return { fault, text, start, end, reason };
}

/** One wording per fault. */
export const WORDING: Readonly<Record<Fault, (d: Diagnostic) => string>> = {
  [Fault.UNKNOWN_FIELD]: (d) => `${d.text}: not a field — searched as text`,
  [Fault.EMPTY_VALUE]: (d) => `${d.text}: nothing to match on`,
  [Fault.NOT_A_NUMBER]: (d) => `${d.text}: not a number`,
  [Fault.RESERVED]: (d) => `${d.text} in a value has to be quoted`,
  [Fault.UNCLOSED_QUOTE]: () => "unclosed quote",
  [Fault.UNCLOSED_GROUP]: () => "unclosed ( — closed for you at the end",
  [Fault.STRAY_CLOSE]: () => "stray ) — ignored",
  [Fault.DANGLING_OR]: (d) => `${d.text} with nothing after it`,
  [Fault.INVALID_VALUE]: (d) => `${d.text}: ${d.reason}`,
  [Fault.TOO_NESTED]: () => `more than ${MAX_GROUPS} nested groups — the rest read as text`,
};

/** A diagnostic in words, for a status line. */
export function describe(d: Diagnostic): string {
  return WORDING[d.fault](d);
}

/** The status-line summary: distinct wordings, the first two, and a count of the rest. */
export function noticeOf(diagnostics: Iterable<Diagnostic>): string {
  const found = [...new Set([...diagnostics].map((d) => describe(d)))];
  if (found.length === 0) return "";
  const shown = found.slice(0, MAX_NOTICES).join(" · ");
  return found.length <= MAX_NOTICES ? shown : `${shown} · +${found.length - MAX_NOTICES}`;
}

/** A parsed query, and the schema it was parsed against: enough to run it. */
export class Query<Row> {
  readonly schema: Schema<Row>;
  readonly expr: Expr;
  readonly diagnostics: readonly Diagnostic[];

  constructor(schema: Schema<Row>, expr: Expr = and(), diagnostics: readonly Diagnostic[] = []) {
    this.schema = schema;
    this.expr = expr;
    this.diagnostics = diagnostics;
  }

  /** Does this query hold for this row? An empty query matches everything. */
  matches(row: Row): boolean {
    return holds(this.expr, row, this.schema);
  }

  /** The rows this query keeps, in the order they came. */
  filter(rows: Iterable<Row>): Row[] {
    const out: Row[] = [];
    for (const r of rows) if (holds(this.expr, r, this.schema)) out.push(r);
    return out;
  }

  /** The clauses in the query's conjunctive core, its top-level `And`. */
  get terms(): readonly Term[] {
    return this.expr.kind === "and" ? this.expr.parts.filter((p): p is Term => p.kind === "term") : [];
  }

  /** The first positive clause in the core asking about this field here (not via a path). */
  first(field: string): Term | undefined {
    return this.terms.find((t) => t.field === field && !t.negated && t.via.length === 0);
  }

  /** The field names the parser did not recognise, in the order typed. */
  get unknownFields(): readonly string[] {
    return [...new Set(this.diagnostics.filter((d) => d.fault === Fault.UNKNOWN_FIELD).map((d) => d.text))];
  }

  /** One line saying what the parser noticed, or empty when it noticed nothing. */
  get notice(): string {
    return noticeOf(this.diagnostics);
  }

  get isEmpty(): boolean {
    return exprEquals(this.expr, and());
  }

  /** The bare words, joined: the free-text part of the query. */
  get text(): string {
    const { bare } = this.schema;
    return this.terms
      .filter((t) => t.field === bare && t.via.length === 0)
      .flatMap((t) => t.values)
      .join(" ");
  }
}
