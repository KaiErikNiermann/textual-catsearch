/**
 * The field vocabulary a query language is built from: declared once, read by everything.
 *
 * Describe your rows as a `Schema`: a list of fields, each saying what it is called, how its
 * values are read off a row, and how they compare. Parsing, matching, rendering and completion
 * all read that one declaration.
 *
 * ```ts
 * const schema = new Schema<Book>(
 *   [
 *     textField({ name: "title", get: (b) => b.title, aliases: ["name"], complete: false }),
 *     textField({ name: "author", get: (b) => b.authors }),
 *     enumField({ name: "format", get: (b) => b.format, choices: ["hardcover", "ebook"] }),
 *     numberField({ name: "year", get: (b) => b.year }),
 *     flagField({ name: "is", flags: { read: (b) => b.read, owned: (b) => b.owned } }),
 *   ],
 *   { bare: "title" },
 * );
 * ```
 */

import { fold } from "./text.ts";
import { compareCodePoints, strip } from "./unicode.ts";

/** What a string accessor may hand back: one value, several, or nothing. */
export type Strings = string | Iterable<string> | null | undefined;

/** What a numeric accessor may hand back: one value, several, or nothing. */
export type Numbers = number | Iterable<number> | null | undefined;

/** A number field's reader for values with units: a number, a half-open span, or `null`. */
export type Unit = (text: string) => number | readonly [number, number] | null | undefined;

/** An accessor's answer as non-empty strings. A lone string is one value, not characters. */
export function stringsOf(value: Strings): string[] {
  if (value === null || value === undefined) return [];
  if (typeof value === "string") return value ? [value] : [];
  return [...value].filter((v) => v.length > 0);
}

/** An accessor's answer as numbers. */
export function numbersOf(value: Numbers): number[] {
  if (value === null || value === undefined) return [];
  if (typeof value === "number") return [value];
  return [...value];
}

// --- completion vocabulary ---------------------------------------------------------------
/** One completable value, with how many rows use it (drives ranking). */
export interface VocabEntry {
  readonly value: string;
  readonly uses: number;
}

export function vocabEntry(value: string, uses = 0): VocabEntry {
  return { value, uses };
}

/** `[value, detail]` pairs a field completes to. */
export type Completions = readonly (readonly [VocabEntry, string])[];

/** Completable values per field, keyed by canonical field name. */
export class Vocabulary {
  readonly entries: ReadonlyMap<string, readonly VocabEntry[]>;
  /** For a `dynamic` schema: the data's keys, offered as field names after the declared ones. */
  readonly keys: readonly VocabEntry[];

  constructor(
    entries: ReadonlyMap<string, readonly VocabEntry[]> | Readonly<Record<string, readonly VocabEntry[]>> = new Map(),
    keys: readonly VocabEntry[] = [],
  ) {
    this.entries = entries instanceof Map ? entries : new Map(Object.entries(entries));
    this.keys = keys;
  }

  of(field: string): readonly VocabEntry[] {
    return this.entries.get(field) ?? [];
  }

  /** Both vocabularies; where both name a field, `other`'s entries follow this one's. */
  merged(other: Vocabulary): Vocabulary {
    const names = new Set([...this.entries.keys(), ...other.entries.keys()]);
    const entries = new Map<string, readonly VocabEntry[]>();
    for (const k of names) entries.set(k, distinct([...this.of(k), ...other.of(k)]));
    return new Vocabulary(entries, distinctKeys([...this.keys, ...other.keys]));
  }
}

/** One entry per key as written: keys keep their case. */
function distinctKeys(entries: Iterable<VocabEntry>): VocabEntry[] {
  const seen = new Map<string, VocabEntry>();
  for (const e of entries) if (!seen.has(e.value)) seen.set(e.value, e);
  return [...seen.values()];
}

/** One entry per folded spelling; the first one wins. */
export function distinct(entries: Iterable<VocabEntry>): VocabEntry[] {
  const seen = new Map<string, VocabEntry>();
  for (const e of entries) {
    const key = fold(e.value);
    if (!seen.has(key)) seen.set(key, e);
  }
  return [...seen.values()];
}

/** One entry per folded value, counted once per row carrying it, most used first. */
function tally(perRow: Iterable<readonly string[]>): VocabEntry[] {
  const uses = new Map<string, number>();
  const spelling = new Map<string, string>();
  for (const values of perRow) {
    const folded = new Map<string, string>();
    for (const v of values) folded.set(fold(v), v); // the last spelling in a row, as a dict would
    for (const [key, value] of folded) {
      uses.set(key, (uses.get(key) ?? 0) + 1);
      if (!spelling.has(key)) spelling.set(key, value);
    }
  }
  return [...uses]
    .toSorted(([ka, a], [kb, b]) => b - a || compareCodePoints(ka, kb))
    .map(([key, n]) => vocabEntry(spelling.get(key) ?? key, n));
}

// --- fields --------------------------------------------------------------------------------
interface Named {
  readonly name: string;
  readonly aliases: readonly string[];
  /** What completion calls this field's values; defaults to the name. */
  readonly detail: string;
}

/** Case- and accent-insensitive substring match against the strings `get` returns. */
export interface TextField<Row> extends Named {
  readonly kind: "text";
  readonly get: (row: Row) => Strings;
  readonly choices: readonly string[];
  readonly complete: boolean;
}

/** Case- and accent-insensitive equality. `normalize` maps the query's values (synonyms). */
export interface EnumField<Row> extends Named {
  readonly kind: "enum";
  readonly get: (row: Row) => Strings;
  readonly choices: readonly string[];
  readonly complete: boolean;
  readonly normalize: ((value: string) => string) | null;
}

/** Range containment: `2026`, `2020..2026`, `..2026`, `>=2026`, `<2030`; `parse` reads units. */
export interface NumberField<Row> extends Named {
  readonly kind: "number";
  readonly get: (row: Row) => Numbers;
  readonly parse: Unit | null;
  /** Punctuation `parse` reads beyond the range operators (`:` for a time of day). */
  readonly unquoted: string;
}

/** Named predicates: `is:read` holds when `flags.read(row)` does. */
export interface FlagField<Row> extends Named {
  readonly kind: "flag";
  readonly flags: ReadonlyMap<string, (row: Row) => boolean>;
}

/** The escape hatch: `test(row, value)` decides, one query value at a time. */
export interface CustomField<Row> extends Named {
  readonly kind: "custom";
  readonly test: (row: Row, value: string) => boolean;
  readonly choices: readonly string[];
  /** Answers `field:none`; without it `field:none` matches nothing. */
  readonly empty: ((row: Row) => boolean) | null;
  readonly unquoted: string;
  /** Why a value cannot be used (an `invalid-value` diagnostic), or `null` when it can. */
  readonly check: ((value: string) => string | null | undefined) | null;
  /** The values are conditions that must all hold, rather than alternatives. */
  readonly every: boolean;
}

export type Field<Row> = TextField<Row> | EnumField<Row> | NumberField<Row> | FlagField<Row> | CustomField<Row>;

/** An edge a query may follow before asking: `parent.year:<2020`. */
export interface Relation<Row> extends Named {
  readonly kind: "relation";
  readonly follow: (row: Row) => Iterable<Row>;
}

type Options<T, Required extends keyof T> = Pick<T, Required> & Partial<Omit<T, Required | "kind">>;

export function textField<Row>(spec: Options<TextField<Row>, "name" | "get">): TextField<Row> {
  return { kind: "text", aliases: [], detail: "", choices: [], complete: true, ...spec };
}

export function enumField<Row>(spec: Options<EnumField<Row>, "name" | "get">): EnumField<Row> {
  return { kind: "enum", aliases: [], detail: "", choices: [], complete: true, normalize: null, ...spec };
}

export function numberField<Row>(spec: Options<NumberField<Row>, "name" | "get">): NumberField<Row> {
  return { kind: "number", aliases: [], detail: "", parse: null, unquoted: "", ...spec };
}

export function flagField<Row>(
  spec: Omit<Options<FlagField<Row>, "name">, "flags"> & {
    readonly flags: ReadonlyMap<string, (row: Row) => boolean> | Readonly<Record<string, (row: Row) => boolean>>;
  },
): FlagField<Row> {
  const flags = spec.flags instanceof Map ? spec.flags : new Map(Object.entries(spec.flags));
  return { kind: "flag", aliases: [], detail: "", ...spec, flags };
}

export function customField<Row>(spec: Options<CustomField<Row>, "name" | "test">): CustomField<Row> {
  return {
    kind: "custom",
    aliases: [],
    detail: "",
    choices: [],
    empty: null,
    unquoted: "",
    check: null,
    every: false,
    ...spec,
  };
}

export function relation<Row>(spec: Options<Relation<Row>, "name" | "follow">): Relation<Row> {
  return { kind: "relation", aliases: [], detail: "", ...spec };
}

// The operators a number field reads, and so the characters its values may carry unquoted.
const NUMERIC_OPERATORS = "<>=.";

/** Punctuation this field's values may carry without quotes, beyond `[A-Za-z0-9_-]`. */
export function unquoted<Row>(field: Field<Row>): string {
  switch (field.kind) {
    case "number": {
      return NUMERIC_OPERATORS + field.unquoted;
    }
    case "custom": {
      return field.unquoted;
    }
    default: {
      return "";
    }
  }
}

/** What completion calls a field's values. */
export function detailOf<Row>(field: Field<Row> | Relation<Row>): string {
  return field.detail || field.name;
}

// --- the schema ------------------------------------------------------------------------------
// A field name: lowercase, no `.` (the path separator), no `:`, no leading `-` (negation).
const NAME = /^[a-z0-9_][a-z0-9_-]*$/u;
// A dynamic key is typed as written in the data: it keeps its case and may have dots.
const KEY = /^\w[\w.-]*$/u; // ASCII: `\w` is ASCII-only without the `i` flag
/** How many keys' answers from `dynamic` are kept. */
export const DYNAMIC_KEYS = 4096;

export interface SchemaOptions<Row> {
  /** The field bare words search: a `TextField` or a `CustomField`. */
  readonly bare: string;
  readonly relations?: Iterable<Relation<Row>>;
  /** A field for a key no declared field claims (`http.status`), or `null` to decline it. */
  readonly dynamic?: ((key: string) => Field<Row> | null | undefined) | null;
}

/**
 * Every field and relation a query may name, and which field bare words search.
 *
 * Construction throws on any name claimed twice: two fields sharing a name would silently
 * shadow one another, and an alias shadowing a field would make the field unreachable.
 */
export class Schema<Row> {
  readonly #aliases = new Map<string, string>();
  readonly #dynamic: ((key: string) => Field<Row> | null | undefined) | null;
  readonly #made = new Map<string, Field<Row> | null>();
  readonly #fields = new Map<string, Field<Row>>();
  readonly #relations = new Map<string, Relation<Row>>();
  readonly bare: string;

  constructor(fields: Iterable<Field<Row>>, options: SchemaOptions<Row>) {
    this.#dynamic = options.dynamic ?? null;
    const declared: (Field<Row> | Relation<Row>)[] = [...fields, ...(options.relations ?? [])];
    for (const spec of declared) this.#claim(spec);
    for (const spec of declared) for (const alias of spec.aliases) this.#alias(alias, spec.name);
    const found = this.#fields.get(options.bare);
    if (found?.kind !== "text" && found?.kind !== "custom") {
      throw new Error(`bare field '${options.bare}' must name a TextField or CustomField here`);
    }
    this.bare = options.bare;
  }

  #claim(spec: Field<Row> | Relation<Row>): void {
    if (!NAME.test(spec.name)) throw new Error(`field name '${spec.name}' must match ${NAME.source}`);
    if (this.#fields.has(spec.name) || this.#relations.has(spec.name)) {
      throw new Error(`field name claimed twice: '${spec.name}'`);
    }
    if (spec.kind === "relation") this.#relations.set(spec.name, spec);
    else this.#fields.set(spec.name, spec);
  }

  #alias(alias: string, name: string): void {
    if (!NAME.test(alias)) throw new Error(`alias '${alias}' must match ${NAME.source}`);
    if (this.#fields.has(alias) || this.#relations.has(alias)) {
      throw new Error(`alias '${alias}' shadows the field of the same name`);
    }
    if (this.#aliases.has(alias)) throw new Error(`alias claimed twice: '${alias}'`);
    this.#aliases.set(alias, name);
  }

  /** Every field, by canonical name, in declaration order. */
  get fields(): ReadonlyMap<string, Field<Row>> {
    return this.#fields;
  }

  /** Every relation, by canonical name, in declaration order. */
  get relations(): ReadonlyMap<string, Relation<Row>> {
    return this.#relations;
  }

  /** Every canonical field and relation name. */
  get names(): ReadonlySet<string> {
    return new Set([...this.fields.keys(), ...this.relations.keys()]);
  }

  /** The name an alias stands for. Idempotent on a real name; lowercases everything. */
  canonical(name: string): string {
    const lowered = strip(name).toLowerCase();
    return this.#aliases.get(lowered) ?? lowered;
  }

  /** The field a name or alias refers to: a declared one first, then one `dynamic` makes. */
  field(name: string): Field<Row> | undefined {
    return this.declared(name) ?? this.dynamicField(name);
  }

  /** The declared field a name or alias refers to. */
  declared(name: string): Field<Row> | undefined {
    // A canonical name is its own canonical form, and no alias may shadow a field, so the
    // direct hit is the answer `canonical` would reach; matching asks this once per row.
    return this.fields.get(name) ?? this.fields.get(this.canonical(name));
  }

  get isDynamic(): boolean {
    return this.#dynamic !== null;
  }

  /** The field `dynamic` makes for a key nothing declared claims, asked once per key. */
  dynamicField(key: string): Field<Row> | undefined {
    const typed = strip(key);
    if (this.#dynamic === null || !KEY.test(typed) || this.declared(typed) !== undefined) return undefined;
    if (this.#made.has(typed)) {
      const made = this.#made.get(typed) ?? null;
      // Refresh its place: the table keeps the most recently used keys.
      this.#made.delete(typed);
      this.#made.set(typed, made);
      return made ?? undefined;
    }
    const made = this.#dynamic(typed) ?? null;
    if (made !== null && made.name !== typed) {
      throw new Error(`dynamic field for '${typed}' is named '${made.name}', not the key`);
    }
    if (this.#made.size >= DYNAMIC_KEYS) {
      const oldest = this.#made.keys().next();
      if (oldest.done !== true) this.#made.delete(oldest.value);
    }
    this.#made.set(typed, made);
    return made ?? undefined;
  }

  /** The relation a name or alias refers to. */
  relation(name: string): Relation<Row> | undefined {
    return this.relations.get(this.canonical(name));
  }

  /** Every completable value on these rows, per field, most used first. */
  vocabulary(rows: Iterable<Row>): Vocabulary {
    const seen = [...rows];
    const entries = new Map<string, readonly VocabEntry[]>();
    for (const f of this.fields.values()) {
      if ((f.kind === "text" || f.kind === "enum") && f.complete) {
        entries.set(f.name, tally(seen.map((row) => stringsOf(f.get(row)))));
      }
    }
    return new Vocabulary(entries);
  }

  /** What a field completes to, given a vocabulary: its values, then its fixed choices. */
  completions(name: string, vocab: Vocabulary): Completions {
    const spec = this.field(name);
    if (spec === undefined) return [];
    const detail = detailOf(spec);
    let pool: readonly VocabEntry[];
    switch (spec.kind) {
      case "flag": {
        pool = [...spec.flags.keys()].map((v) => vocabEntry(v));
        break;
      }
      case "number": {
        pool = vocab.of(spec.name);
        break;
      }
      default: {
        pool = distinct([...vocab.of(spec.name), ...spec.choices.map((v) => vocabEntry(v))]);
      }
    }
    return pool.map((entry) => [entry, detail] as const);
  }
}
