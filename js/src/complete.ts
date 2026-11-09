/** Completion: what the token under the caret could become, a field name or a value for one. */

import { QUOTE, activeSpan, separated } from "./lexer.ts";
import { openGroups } from "./parser.ts";
import { quote } from "./render.ts";
import { Vocabulary, unquoted } from "./schema.ts";
import type { Completions, Schema, VocabEntry } from "./schema.ts";
import { fold, wordPrefixed } from "./text.ts";
import { compareCodePoints, countChar, partition, rpartition, rstripChars, strip, stripChars, lstripChars } from "./unicode.ts";

/**
 * One completion; splice it with `apply`. A `field` suggestion turns a bare word into
 * `field:` (or a relation into `relation.`), a `value` suggestion fills in what follows the
 * colon. Only a value completion is worth previewing: it narrows the results rather than
 * emptying them.
 */
export interface Suggestion {
  readonly insert: string;
  readonly label: string;
  readonly detail: string;
  readonly start: number;
  readonly end: number;
  readonly kind: "field" | "value";
}

/** `source` with `suggestion` spliced over the token it was derived from. */
export function apply(source: string, suggestion: Suggestion): string {
  return source.slice(0, suggestion.start) + suggestion.insert + source.slice(suggestion.end);
}

/** The completable `[value, detail]` pairs for one field, best match first. */
export function rankValues<Row>(
  schema: Schema<Row>,
  field: string,
  vocab: Vocabulary,
  needle: string,
  limit = 8,
): Completions {
  const folded = fold(needle);
  const pool = schema.completions(field, vocab);
  let hits = pool.filter(([e]) => wordPrefixed(e.value, folded));
  // Nothing starts with it, so fall back to anywhere in the value.
  if (hits.length === 0) hits = pool.filter(([e]) => fold(e.value).includes(folded));
  return hits.toSorted(([a], [b]) => byRank(a, b, folded)).slice(0, limit);
}

/** Whole-value prefix first, then the most used, then alphabetical. */
function byRank(a: VocabEntry, b: VocabEntry, needle: string): number {
  const pa = fold(a.value).startsWith(needle) ? 0 : 1;
  const pb = fold(b.value).startsWith(needle) ? 0 : 1;
  return pa - pb || b.uses - a.uses || compareCodePoints(a.value, b.value);
}

/** Where a completion splices, and what it carries back in unchanged: the bracket and sign
 * before the token (`prefix`), the path already walked (`stem`), and the caret. */
interface Slot {
  readonly start: number;
  readonly end: number;
  readonly prefix: string;
  readonly stem: string;
  readonly caret: number;
}

export interface SuggestOptions {
  readonly limit?: number;
  /** Which field and relation names are offered (default: all). Values are unaffected. */
  readonly fields?: Iterable<string> | null;
}

/** Completions for the token under the cursor: field names, then values for that field. */
export function suggest<Row>(
  source: string,
  cursor: number,
  schema: Schema<Row>,
  vocab: Vocabulary | null = null,
  options: SuggestOptions = {},
): Suggestion[] {
  const limit = options.limit ?? 8;
  const known = vocab ?? new Vocabulary();
  const [start, spanEnd] = activeSpan(source, cursor);
  const end = spanEnd - closers(source, start, spanEnd);
  const token = source.slice(start, end);
  const body = lstripChars(token, "(");
  const negated = body.startsWith("-") || body.startsWith("!");
  const [head, sep, value] = partition(negated ? body.slice(1) : body, ":");
  const [walked, , tail] = rpartition(head, ".");
  const prefix = token.slice(0, token.length - body.length + (negated ? 1 : 0));
  if (walked !== "" && walked.split(".").some((piece) => schema.relation(piece) === undefined)) {
    // A dotted key that is not a path is one of the data's keys, if the schema takes those.
    const at = { start, end, prefix, stem: "", caret: cursor };
    return dotted(schema, head, sep, value, known, at, limit);
  }
  const at = { start, end, prefix, stem: head.slice(0, head.length - tail.length), caret: cursor };
  if (!sep) {
    const fields = options.fields ?? null;
    const offered = fields === null ? schema.names : new Set(fields);
    const declared = fieldNames(schema, tail, offered, at, limit);
    return [...declared, ...keyNames(schema, tail, known, at, limit - declared.length)];
  }
  const spec = schema.field(tail);
  return spec === undefined ? [] : fieldValues(schema, spec.name, value, known, at, limit);
}

/** How many of the `)` ending the token close a group: those are grammar, not the value. */
function closers(source: string, start: number, end: number): number {
  const token = source.slice(start, end);
  if (countChar(token, QUOTE) % 2) return 0; // inside an open quote, a bracket is a character
  const body = rstripChars(token, ")");
  return Math.min(token.length - body.length, openGroups(source.slice(0, start) + body));
}

function fieldNames<Row>(
  schema: Schema<Row>,
  head: string,
  offered: ReadonlySet<string>,
  at: Slot,
  limit: number,
): Suggestion[] {
  const needle = stripChars(strip(head), QUOTE).toLowerCase();
  const names = [...offered].filter((n) => n.startsWith(needle) && n !== schema.bare).toSorted(compareCodePoints);
  return names.slice(0, limit).map((name) => nameSuggestion(name, schema.relations.has(name), at));
}

/** The data's own keys a `dynamic` schema takes, after its declared names, most used first. */
function keyNames<Row>(schema: Schema<Row>, head: string, vocab: Vocabulary, at: Slot, limit: number): Suggestion[] {
  if (!schema.isDynamic || limit <= 0) return [];
  const needle = fold(stripChars(strip(head), QUOTE));
  return vocab.keys
    .filter((e) => fold(e.value).startsWith(needle) && schema.declared(e.value) === undefined)
    .toSorted((a, b) => b.uses - a.uses || compareCodePoints(a.value, b.value))
    .slice(0, limit)
    .map((entry) => {
      const written = `${entry.value}:`;
      return {
        insert: `${at.prefix}${written}`,
        label: written,
        detail: entry.uses ? `key · ${entry.uses}` : "key",
        start: at.start,
        end: at.end,
        kind: "field",
      };
    });
}

function dotted<Row>(
  schema: Schema<Row>,
  head: string,
  sep: boolean,
  value: string,
  vocab: Vocabulary,
  at: Slot,
  limit: number,
): Suggestion[] {
  if (!schema.isDynamic) return [];
  if (!sep) return keyNames(schema, head, vocab, at, limit);
  const spec = schema.dynamicField(head);
  return spec === undefined ? [] : fieldValues(schema, spec.name, value, vocab, at, limit);
}

function nameSuggestion(name: string, isRelation: boolean, at: Slot): Suggestion {
  const written = `${at.stem}${name}${isRelation ? "." : ":"}`;
  return {
    insert: `${at.prefix}${written}`,
    label: written,
    detail: isRelation ? "relation" : "field",
    start: at.start,
    end: at.end,
    kind: "field",
  };
}

/**
 * Value completions for the segment of a comma list the caret is in. Only that segment is
 * quoted (quoting the whole list would turn two values into one with a comma in it), and what
 * was typed on either side rides back out as typed.
 */
function fieldValues<Row>(
  schema: Schema<Row>,
  field: string,
  value: string,
  vocab: Vocabulary,
  at: Slot,
  limit: number,
): Suggestion[] {
  const spec = schema.field(field);
  if (spec === undefined) return [];
  const caret = Math.max(0, Math.min(at.caret - (at.end - value.length), value.length));
  const [lo, hi] = separated(value, ",").find(([a, b]) => a <= caret && caret <= b) ?? [0, value.length];
  const lead = value.slice(0, lo);
  const segment = value.slice(lo, hi);
  const rest = value.slice(hi);
  const extra = unquoted(spec);
  return rankValues(schema, field, vocab, needleOf(segment, lead), limit).map(([entry, detail]) => ({
    insert: `${at.prefix}${at.stem}${field}:${lead}${quote(entry.value, extra)}${rest}`,
    label: entry.value,
    detail: entry.uses ? `${detail} · ${entry.uses}` : detail,
    start: at.start,
    end: at.end,
    kind: "value",
  }));
}

/** What a value segment searches for: without quotes, and without the apostrophe opening a
 * shell-shaped `cast:'Ala`. */
function needleOf(segment: string, lead: string): string {
  const needle = stripChars(strip(segment), QUOTE);
  return !lead && segment.startsWith("'") ? lstripChars(needle, "'") : needle;
}
