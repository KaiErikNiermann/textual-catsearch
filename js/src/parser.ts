/**
 * Parsing: a query string into a tree, against a schema. Total: it reports, never refuses.
 *
 * ```text
 * reacher kind:tv cast:"Alan Ritchson" year:2026
 * "the odyssey" -tag:comedy is:upcoming
 * (kind:tv OR kind:movie) -(tag:horror year:<2000)
 * ```
 *
 * A bare (or quoted) word is a term on the schema's bare field; everything else is
 * `field:value`. Terms are AND-ed, comma-separated values within one term are OR-ed, a leading
 * `-` negates, `OR` alternates, brackets group, and `field:none` asks for rows with nothing
 * under that field.
 */

import { Guarded, QUOTE, isWordChar, lex } from "./lexer.ts";
import type { Token } from "./lexer.ts";
import { Fault, MAX_GROUPS, NOTHING, OR_WORDS, Query, diagnostic } from "./query.ts";
import type { Diagnostic } from "./query.ts";
import { unquoted } from "./schema.ts";
import type { Field, Schema, Unit } from "./schema.ts";
import { and, neg, numRange, or, term } from "./tree.ts";
import type { Expr, NumRange, Term } from "./tree.ts";
import { SPACE_CLASS, WORD_CLASS, casefold, countChar, partition, pyInt, strip } from "./unicode.ts";

// --- numbers ----------------------------------------------------------------------------------
type Num = number | bigint;
type Span = readonly [Num, Num];
type Read = (text: string) => Span;

/** A value that does not read as a number: Python's `ValueError`, kept apart from real errors. */
class Unreadable extends Error {}

function toNumber(n: Num): number {
  return typeof n === "bigint" ? Number(n) : n;
}

function isSpan(n: Span): boolean {
  return n[1] > n[0];
}

/** `2026` / `2020..2026` / `>=2026` / `<2030` as a window, or `null` if it does not read.
 * A unit may read a value as the half-open span it stands for (`14:30` is the whole minute). */
export function parseRange(value: string, unit: Unit | null = null): NumRange | null {
  const v = strip(value);
  const read = reader(unit);
  let n: Span;
  try {
    const compared = comparison(v, read, unit === null);
    if (compared !== null) return compared;
    if (v.includes("..")) {
      const [lo, , hi] = partition(v, "..");
      const start = strip(lo) ? read(lo) : null;
      const stop = strip(hi) ? read(hi) : null;
      return numRange({
        lo: start === null ? null : toNumber(start[0]),
        hi: stop === null ? null : toNumber(stop[1]),
        hiStrict: stop !== null && isSpan(stop),
      });
    }
    n = read(v);
  } catch (error) {
    if (error instanceof Unreadable) return null;
    throw error;
  }
  return numRange({ lo: toNumber(n[0]), hi: toNumber(n[1]), hiStrict: isSpan(n) });
}

const COMPARISONS = [
  [">=", false],
  ["<=", false],
  [">", true],
  ["<", true],
] as const;

/** `>=n`, `<=n`, `>n`, `<n` as a window; `null` if `v` is not a comparison. */
function comparison(v: string, read: Read, integral: boolean): NumRange | null {
  const found = COMPARISONS.find(([op]) => v.startsWith(op));
  if (found === undefined) return null;
  const [op, strict] = found;
  return compared(read(v.slice(op.length)), op.startsWith("<"), strict, integral);
}

/** The window one comparison against `n` stands for. */
function compared(n: Span, upper: boolean, strict: boolean, integral: boolean): NumRange {
  const [lo, hi] = n;
  if (strict && integral && typeof lo === "bigint") {
    // Integers: `> n` is `>= n + 1`, computed exactly before it becomes a double.
    return numRange(upper ? { hi: Number(lo - 1n) } : { lo: Number(lo + 1n) });
  }
  if (isSpan(n)) {
    // The span's edges: after all of it, before any of it.
    return numRange(upper ? { hi: toNumber(strict ? lo : hi), hiStrict: true } : { lo: toNumber(strict ? hi : lo) });
  }
  return numRange(upper ? { hi: toNumber(lo), hiStrict: strict } : { lo: toNumber(lo), loStrict: strict });
}

/** `int`, or the field's unit parser, as a span (a number is the span of itself). */
function reader(unit: Unit | null): Read {
  if (unit === null) {
    return (text) => {
      const n = pyInt(text);
      if (n === undefined) throw new Unreadable(text);
      return [n, n];
    };
  }
  return (text) => {
    const got = unit(strip(text));
    if (got === null || got === undefined) throw new Unreadable(text);
    if (typeof got === "number") return [got, got];
    const [lo, hi] = got;
    // A span has to be one: NaN, or an end before its start, is no quantity.
    if (Number.isNaN(lo) || Number.isNaN(hi) || lo > hi) throw new Unreadable(text);
    return [lo, hi];
  };
}

// --- quotes ------------------------------------------------------------------------------------
// A whole value wrapped in apostrophes, and nothing else: `author:'Ursula Le Guin'`.
// Built from Python's whitespace and word tables (unicode-data.ts), never from input.
// eslint-disable-next-line security/detect-non-literal-regexp
const SINGLE_QUOTED_VALUE = new RegExp(
  String.raw`(?<![^${SPACE_CLASS}])([A-Za-z][${WORD_CLASS}.\-]*):'([^'"]*)'(?=[${SPACE_CLASS}]|$)`,
  "gu",
);

/** `field:'value'` rewritten to `field:"value"` before lexing, outside double quotes only. */
function normalizeQuotes(source: string): string {
  let counted = 0;
  let quotes = 0;
  return source.replaceAll(SINGLE_QUOTED_VALUE, (whole: string, key: string, value: string, at: number) => {
    quotes += countChar(source, QUOTE, counted, at);
    counted = at + whole.length;
    return quotes % 2 ? whole : `${key}:"${value}"`;
  });
}

// --- parse ---------------------------------------------------------------------------------------
export interface ParseOptions {
  /** An empty value degrades to literal text instead of being dropped: for strings that name
   * something (a new entry typed into an add box) rather than filter. */
  readonly emptyAsText?: boolean;
}

/** Parse a query string. Never throws on any input: malformed input degrades. */
export function parse<Row>(source: string, schema: Schema<Row>, options: ParseOptions = {}): Query<Row> {
  const normalized = normalizeQuotes(source);
  const [items, stray] = itemsOf(lex(normalized));
  const reader = new Reader(items, schema, options.emptyAsText ?? false);
  const expr = reader.group(false);
  const faults = [...stray, ...reader.faults].map((d) => narrowed(d, normalized));
  if (countChar(normalized, QUOTE) % 2) {
    faults.push(diagnostic(Fault.UNCLOSED_QUOTE, QUOTE, normalized.lastIndexOf(QUOTE), normalized.length));
  }
  return new Query(schema, expr, faults);
}

/** `str.find(sub, start, end)`. */
function find(text: string, sub: string, start: number, end: number): number {
  const at = text.indexOf(sub, start);
  return at !== -1 && at + sub.length <= end ? at : -1;
}

/** `str.rfind(sub, start, end)`. */
function rfind(text: string, sub: string, start: number, end: number): number {
  if (end - sub.length < start) return -1;
  const at = text.lastIndexOf(sub, end - sub.length);
  return at >= start ? at : -1;
}

/** The diagnostic's span cut from its whole token down to the fragment it names. */
function narrowed(d: Diagnostic, source: string): Diagnostic {
  if (!d.text) return d;
  const value = find(source, ":", d.start, d.end) + 1 || d.start;
  if (d.fault === Fault.RESERVED) {
    const hits: number[] = [];
    for (let i = value; i < d.end; i++) if (d.text.includes(source.charAt(i))) hits.push(i);
    const [first] = hits;
    const last = hits.at(-1);
    return first === undefined || last === undefined ? d : { ...d, start: first, end: last + 1 };
  }
  // A surplus `)` is the last one in its token; anything else, the first match, and a
  // value's fault is looked for in the value rather than its key.
  let at: number;
  if (d.fault === Fault.STRAY_CLOSE) {
    at = rfind(source, d.text, d.start, d.end);
  } else {
    const from = d.fault === Fault.INVALID_VALUE ? value : d.start;
    at = find(source, d.text, from, d.end);
  }
  return at < 0 ? d : { ...d, start: at, end: at + d.text.length };
}

// --- the token stream ----------------------------------------------------------------------------
type Sym = "clause" | "open" | "close" | "or";

interface Item {
  readonly sym: Sym;
  readonly token: Token;
  /** The clause, brackets peeled off. */
  readonly body: Guarded;
  /** Set on the `(` of a negated group. */
  readonly negated: boolean;
}

function item(sym: Sym, token: Token, body: Guarded = Guarded.EMPTY, negated = false): Item {
  return { sym, token, body, negated };
}

/** Every group a token opens (each flagged if a `-` opened it), the rest, and its closers. */
function opens(body: Guarded): readonly [boolean[], Guarded, number] {
  const [, peeled, closes] = body.peel("", ")");
  let rest = peeled;
  const flags: boolean[] = [];
  for (;;) {
    const [negated, signed] = rest.sign();
    const [lead, inner] = (negated ? signed : rest).peel("(", "");
    if (!lead) return [flags, rest, closes];
    // Only the outermost of a run carries the sign: `-((a` is a negated group around one.
    flags.push(negated, ...Array.from({ length: lead - 1 }, () => false));
    rest = inner;
  }
}

/** Brackets and `OR` separated out of the whitespace tokens. A `)` is only a closer while a
 * group is open, which keeps `title:(2021)` a literal value. */
function itemsOf(tokens: readonly Token[]): readonly [Item[], Diagnostic[]] {
  const out: Item[] = [];
  const stray: Diagnostic[] = [];
  let depth = 0;
  for (const token of tokens) {
    const opened = opens(token.body);
    let [flags, body] = opened;
    const closes = opened[2];
    if (depth + flags.length > MAX_GROUPS) {
      // Read the innermost surplus brackets as part of the value rather than refusing.
      const keep = Math.max(0, MAX_GROUPS - depth);
      body = new Guarded([["(".repeat(flags.length - keep), false], ...body.runs]);
      flags = flags.slice(0, keep);
      stray.push(diagnostic(Fault.TOO_NESTED, "(", token.start, token.end));
    }
    for (const negated of flags) out.push(item("open", token, Guarded.EMPTY, negated));
    depth += flags.length;
    const taken = Math.min(closes, depth);
    if (closes > taken) {
      // A surplus `)` stays part of the value (a title may end in one), and is reported.
      stray.push(diagnostic(Fault.STRAY_CLOSE, ")", token.start, token.end));
      body = body.append(")".repeat(closes - taken));
    }
    if ([...OR_WORDS].some((word) => body.isFree(word))) out.push(item("or", token, body));
    else if (body.nonEmpty) out.push(item("clause", token, body));
    for (let i = 0; i < taken; i++) out.push(item("close", token));
    depth -= taken;
  }
  return [out, stray];
}

/** How many groups are still open at the end of `source`, counted as `parse` counts them. */
export function openGroups(source: string): number {
  const [items] = itemsOf(lex(normalizeQuotes(source)));
  let open = 0;
  for (const it of items) {
    if (it.sym === "open") open++;
    else if (it.sym === "close") open--;
  }
  return open;
}

// --- reading the stream ----------------------------------------------------------------------
/** Recursive descent: `group -> or+`, `or -> unary ("OR" unary)*`, `unary -> "-"? (group | clause)`. */
class Reader<Row> {
  #pos = 0;
  readonly #items: readonly Item[];
  readonly #schema: Schema<Row>;
  readonly #emptyAsText: boolean;
  readonly faults: Diagnostic[] = [];

  constructor(items: readonly Item[], schema: Schema<Row>, emptyAsText: boolean) {
    this.#items = items;
    this.#schema = schema;
    this.#emptyAsText = emptyAsText;
  }

  #at(it: Item, fault: Fault, text: string): void {
    this.faults.push(diagnostic(fault, text, it.token.start, it.token.end));
  }

  /** A juxtaposition of alternatives, up to `)` or the end of the stream. */
  group(closing: boolean, opened?: Item): Expr {
    const parts: Expr[] = [];
    while (this.#pos < this.#items.length) {
      const it = this.#items[this.#pos];
      if (it?.sym === "close") {
        this.#pos++;
        if (closing) return and(merged(parts, this.#schema));
        continue;
      }
      const part = this.alternatives();
      if (part !== null) parts.push(part);
    }
    if (closing) {
      this.faults.push(
        diagnostic(Fault.UNCLOSED_GROUP, "(", opened?.token.start ?? 0, opened?.token.end ?? 0),
      );
    }
    return and(merged(parts, this.#schema));
  }

  /** One or more clauses joined by `OR`. */
  alternatives(): Expr | null {
    const first = this.unary();
    const parts: Expr[] = first === null ? [] : [first];
    for (;;) {
      const marker = this.#items[this.#pos];
      if (marker?.sym !== "or") break;
      this.#pos++;
      const next = this.unary();
      if (next === null) this.#at(marker, Fault.DANGLING_OR, marker.body.text);
      else parts.push(next);
    }
    if (parts.length === 0) return null;
    return parts.length === 1 ? (parts[0] ?? null) : or(parts);
  }

  /** A clause or a bracketed group, either optionally negated. */
  unary(): Expr | null {
    const it = this.#items[this.#pos];
    if (it === undefined) return null;
    if (it.sym === "or") {
      // A leading `OR` has nothing to its left; say so and read it as the word it is.
      this.#at(it, Fault.DANGLING_OR, it.body.text);
      this.#pos++;
      return null;
    }
    if (it.sym === "close") return null;
    this.#pos++;
    if (it.sym === "open") {
      const inner = this.group(true, it);
      return it.negated ? neg(inner) : inner;
    }
    const got = read(it, this.#schema, this.#emptyAsText);
    this.faults.push(...got.faults);
    return got.term;
  }
}

/**
 * Repeated keys folded into one term: OR within a key, AND across keys. Bare text and
 * negated terms are left alone (`a b` means both words, `-tag:a -tag:b` means neither).
 */
function merged<Row>(parts: readonly Expr[], schema: Schema<Row>): Expr[] {
  const at = new Map<string, [number, Term[]]>();
  const out: Expr[] = [];
  for (const part of parts) {
    if (part.kind !== "term" || part.negated || part.field === schema.bare) {
      out.push(part);
      continue;
    }
    const key = JSON.stringify([part.field, part.via]);
    const seen = at.get(key);
    if (seen === undefined) {
      at.set(key, [out.length, [part]]);
      out.push(part);
    } else {
      seen[1].push(part);
    }
  }
  for (const [index, terms] of at.values()) if (terms.length > 1) out[index] = widened(terms, schema);
  return out;
}

/** The first term with the others' values as further alternatives, in the order typed. */
function widened<Row>(terms: readonly Term[], schema: Schema<Row>): Term {
  const [first] = terms;
  if (first === undefined) throw new Error("widened no terms");
  const values = [...new Set(terms.flatMap((t) => t.values))];
  const absent = terms.some((t) => t.absent);
  const spec = schema.field(first.field);
  if (spec === undefined) throw new Error(`merged a term of no field: '${first.field}'`);
  return typedTerm(spec, values, first.negated, absent, first.via);
}

interface ReadClause {
  readonly term: Term | null;
  readonly faults: readonly Diagnostic[];
}

function noticed(token: Token, fault: Fault, text: string): Diagnostic[] {
  return [diagnostic(fault, text, token.start, token.end)];
}

/** One clause item, read as a term. */
function read<Row>(it: Item, schema: Schema<Row>, emptyAsText: boolean): ReadClause {
  const { token } = it;
  const [negated, body] = it.body.sign();
  const [head, sep, value] = body.partition(":");
  const [via, spec] = sep ? stepped(head, schema) : [[], undefined];
  if (spec === undefined) {
    // A colon before something unrecognised is a colonated title ("Andor: Season 2") far more
    // often than a typo'd field, so it degrades to literal text rather than vanishing.
    const found = sep ? noticed(token, Fault.UNKNOWN_FIELD, head) : [];
    return { term: term(schema.bare, { values: [body.text], negated }), faults: found };
  }
  return named(token, spec, value, body.text, schema, emptyAsText, negated, via);
}

function named<Row>(
  token: Token,
  spec: Field<Row>,
  value: Guarded,
  body: string,
  schema: Schema<Row>,
  emptyAsText: boolean,
  negated: boolean,
  via: readonly string[],
): ReadClause {
  const pieces = value
    .split(",")
    .map((p) => p.strip())
    .filter((p) => p.text.length > 0);
  if (pieces.length === 0) {
    // `kind:` mid-typing constrains nothing, unless the string names something.
    const kept = emptyAsText ? term(schema.bare, { values: [body], negated }) : null;
    return { term: kept, faults: noticed(token, Fault.EMPTY_VALUE, body) };
  }
  const absent = pieces.some((p) => saysNothing(p));
  const keptValues = pieces.filter((p) => !saysNothing(p)).map((p) => p.text);
  const made = typedTerm(spec, keptValues, negated, absent, via);
  return { term: made, faults: noticedAbout(token, spec, pieces, made, body) };
}

/**
 * A key read as a path: the relations to follow, and the field to ask at the end. All or
 * nothing; except that a `dynamic` schema is then asked the whole dotted key (`http.status`).
 */
export function stepped<Row>(head: string, schema: Schema<Row>): readonly [string[], Field<Row> | undefined] {
  const walked = head.split(".");
  const tail = walked.pop() ?? "";
  const hops: string[] = [];
  for (const piece of walked) {
    const r = schema.relation(piece);
    if (r !== undefined) hops.push(r.name);
  }
  if (hops.length === walked.length) {
    const spec = schema.field(tail);
    if (spec !== undefined) return [hops, spec];
  }
  if (walked.length > 0) {
    const spec = schema.dynamicField(head);
    if (spec !== undefined) return [[], spec];
  }
  return [[], undefined];
}

/** Is this the bare word `none`, and therefore a question rather than a value? */
function saysNothing(piece: Guarded): boolean {
  return piece.bare && casefold(piece.text) === NOTHING;
}

/** What was worth saying about a clause the parser could otherwise read. */
function noticedAbout<Row>(
  token: Token,
  spec: Field<Row>,
  pieces: readonly Guarded[],
  made: Term,
  body: string,
): Diagnostic[] {
  const found: Diagnostic[] = [];
  const held = claimed(reserved(pieces.map((p) => p.freeText()).join(""), unquoted(spec)));
  if (held) found.push(diagnostic(Fault.RESERVED, held, token.start, token.end));
  const numbers = pieces.filter((p) => !saysNothing(p));
  if (spec.kind === "number" && made.ranges.length < numbers.length) {
    found.push(diagnostic(Fault.NOT_A_NUMBER, body, token.start, token.end));
  }
  if (spec.kind === "custom" && spec.check !== null) {
    for (const v of made.values) {
      const why = spec.check(v);
      if (why !== null && why !== undefined) found.push(diagnostic(Fault.INVALID_VALUE, v, token.start, token.end, why));
    }
  }
  return found;
}

const GRAMMAR_PUNCTUATION = new Set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~");

/** Of the characters a value would be quoted for, the ones worth a warning: ASCII punctuation. */
export function claimed(characters: string): string {
  return [...characters].filter((c) => GRAMMAR_PUNCTUATION.has(c)).join("");
}

/** The characters in `text` an unquoted value may not carry, deduplicated, as they appear. */
export function reserved(text: string, extra: string): string {
  const allowed = new Set(extra);
  return [...new Set([...text].filter((c) => !(c.length === 1 && isWordChar(c)) && !allowed.has(c)))].join("");
}

/** One recognised `field:value` clause. A number field whose value does not read keeps its
 * term with no range, so `year:soon` matches nothing rather than widening the query. */
function typedTerm<Row>(
  spec: Field<Row>,
  values: readonly string[],
  negated: boolean,
  absent = false,
  via: readonly string[] = [],
): Term {
  const ranges: NumRange[] = [];
  if (spec.kind === "number") {
    for (const v of values) {
      const r = parseRange(v, spec.parse);
      if (r !== null) ranges.push(r);
    }
  }
  return term(spec.name, { values, ranges, negated, absent, via });
}
