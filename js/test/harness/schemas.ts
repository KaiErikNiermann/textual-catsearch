/**
 * The spec's three schemas over the rows in `spec/rows`: the twin of
 * `tests/conformance/schemas.py`, which states why each exists. Keep the two in step.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import {
  Schema,
  Vocabulary,
  customField,
  enumField,
  flagField,
  fold,
  numberField,
  relation,
  textField,
  vocabEntry,
} from "../../src/index.ts";
import type { Field } from "../../src/index.ts";
import { digitValue, rpartition, strip } from "../../src/unicode.ts";

export const SPEC = fileURLToPath(new URL("../../../spec/", import.meta.url));

export type SchemaName = "catalog" | "units" | "dynamic";
export const SCHEMA_NAMES: readonly SchemaName[] = ["catalog", "units", "dynamic"];

function load(name: SchemaName): unknown {
  return JSON.parse(readFileSync(`${SPEC}rows/${name}.json`, "utf8"));
}

// --- catalog (tests/catalog.py) -----------------------------------------------------------
export interface Work {
  readonly title: string;
  readonly aliases: readonly string[];
  readonly kind: string;
  readonly years: readonly number[];
  readonly season: number | null;
  readonly genres: readonly string[];
  readonly themes: readonly string[];
  readonly cast: readonly string[];
  readonly director: readonly string[];
  readonly state: string;
  readonly bucket: string;
  readonly freshness: string;
  readonly blockers: readonly string[];
  readonly early_access: boolean;
  readonly platforms: readonly (readonly [string, readonly string[]])[];
  readonly sequel_of: readonly Work[];
  readonly prequel_of: readonly Work[];
}

const DEFAULT_WORK: Work = {
  title: "Reacher: Season 3",
  aliases: [],
  kind: "tv",
  years: [],
  season: null,
  genres: [],
  themes: [],
  cast: [],
  director: [],
  state: "want",
  bucket: "available",
  freshness: "fresh",
  blockers: [],
  early_access: false,
  platforms: [],
  sequel_of: [],
  prequel_of: [],
};

export function work(data: Partial<Work>): Work {
  return {
    ...DEFAULT_WORK,
    ...data,
    sequel_of: (data.sequel_of ?? []).map((w) => work(w)),
    prequel_of: (data.prequel_of ?? []).map((w) => work(w)),
  };
}

export const KINDS = ["movie", "tv", "game"] as const;
export const STATES = ["want", "watching", "watched", "dropped"] as const;
export const BUCKETS = ["available", "upcoming", "watched", "shelved"] as const;

const KIND_ALIASES: ReadonlyMap<string, string> = new Map([
  ["film", "movie"],
  ["films", "movie"],
  ["show", "tv"],
  ["tv-show", "tv"],
  ["series", "tv"],
]);

function canonicalKind(value: string): string {
  const key = strip(value).toLowerCase();
  return KIND_ALIASES.get(key) ?? key;
}

function onPlatform(w: Work, value: string): boolean {
  const [name, , market] = value.includes("@") ? rpartition(value, "@") : [value, false, ""];
  return w.platforms.some(
    ([service, markets]) => fold(service).includes(fold(name)) && (!market || markets.includes(market.toUpperCase())),
  );
}

const bucket =
  (name: string) =>
  (w: Work): boolean =>
    w.bucket === name;

export const FLAGS: ReadonlyMap<string, (w: Work) => boolean> = new Map([
  ...BUCKETS.map((b) => [b, bucket(b)] as const),
  ["blocked", (w: Work) => w.blockers.length > 0],
  ["dated", (w: Work) => w.years.length > 0],
  ["tba", (w: Work) => w.years.length === 0],
  ["fresh", (w: Work) => w.freshness === "fresh"],
  ["aging", (w: Work) => w.freshness === "aging"],
  ["stale", (w: Work) => w.freshness === "stale"],
  ["early-access", (w: Work) => w.early_access],
]);

export const CATALOG = new Schema<Work>(
  [
    textField({ name: "name", get: (w) => [w.title, ...w.aliases], aliases: ["title"], complete: false }),
    enumField({ name: "kind", get: (w) => w.kind, choices: KINDS, normalize: canonicalKind }),
    numberField({ name: "year", get: (w) => w.years }),
    numberField({ name: "season", get: (w) => w.season }),
    textField({ name: "tag", get: (w) => [...w.genres, ...w.themes] }),
    textField({ name: "genre", get: (w) => w.genres }),
    textField({ name: "theme", get: (w) => w.themes }),
    textField({ name: "cast", get: (w) => w.cast, aliases: ["actors", "actor"] }),
    textField({ name: "director", get: (w) => w.director }),
    textField({ name: "person", get: (w) => [...w.director, ...w.cast] }),
    enumField({ name: "state", get: (w) => w.state, choices: STATES }),
    flagField({ name: "is", flags: FLAGS, detail: "flag" }),
    customField({
      name: "platform",
      test: onPlatform,
      aliases: ["on"],
      unquoted: "@",
      empty: (w) => w.platforms.length === 0,
    }),
  ],
  {
    bare: "name",
    relations: [
      relation({ name: "sequel-of", follow: (w) => w.sequel_of, aliases: ["sequel-to"] }),
      relation({ name: "prequel-of", follow: (w) => w.prequel_of, aliases: ["prequel-to"] }),
    ],
  },
);

// --- units (tests/test_units.py) ----------------------------------------------------------
export interface Job {
  readonly name: string;
  readonly took: number;
  readonly year: number;
}

const UNIT_SCALE: ReadonlyMap<string, number> = new Map([
  ["", 1],
  ["s", 1],
  ["m", 60],
  ["h", 3600],
]);
// One optional fraction after the digits: linear, whatever the input.
// eslint-disable-next-line security/detect-unsafe-regex
const QUANTITY = /^(\p{Nd}+(?:\.\p{Nd}+)?)([smh]?)$/u;

/** `seconds` from tests/test_units.py: Python's `\d` and `float` read any script's digits. */
export function seconds(text: string): number | null {
  const m = QUANTITY.exec(text);
  if (m === null) return null;
  const digits = [...(m[1] ?? "")].map((c) => (c === "." ? "." : String(digitValue(c.codePointAt(0) ?? 0))));
  return Number(digits.join("")) * (UNIT_SCALE.get(m[2] ?? "") ?? 1);
}

export const UNITS = new Schema<Job>(
  [
    textField({ name: "name", get: (j) => j.name }),
    numberField({ name: "took", get: (j) => j.took, parse: seconds }),
    numberField({ name: "year", get: (j) => j.year }),
  ],
  { bare: "name" },
);

// --- dynamic --------------------------------------------------------------------------------
export interface Line {
  readonly text: string;
  readonly fields: ReadonlyMap<string, string>;
  readonly level: number;
  readonly parent: Line | null;
}

interface LineData {
  readonly text: string;
  readonly fields: Readonly<Record<string, string>>;
  readonly level?: number;
  readonly parent?: LineData | null;
}

function line(data: LineData): Line {
  return {
    text: data.text,
    fields: new Map(Object.entries(data.fields)),
    level: data.level ?? 0,
    parent: data.parent === undefined || data.parent === null ? null : line(data.parent),
  };
}

function kv(key: string): Field<Line> {
  return customField({
    name: key,
    test: (row, value) => {
      const have = row.fields.get(key);
      return have !== undefined && fold(have) === fold(value);
    },
    empty: (row) => !row.fields.has(key),
    detail: "a key",
  });
}

function count(text: string, ch: string): number {
  return [...text].filter((c) => c === ch).length;
}

export const DYNAMIC = new Schema<Line>(
  [
    textField({ name: "text", get: (r) => r.text }),
    numberField({ name: "level", get: (r) => r.level }),
    customField({
      name: "re",
      test: (r, v) => fold(r.text).includes(fold(v)),
      check: (v) => (count(v, "(") === count(v, ")") ? null : "unbalanced brackets"),
      unquoted: "()|*+?",
    }),
    customField({
      name: "kv",
      test: (r, v) => {
        const at = v.indexOf("=");
        return at !== -1 && r.fields.get(v.slice(0, at)) === v.slice(at + 1);
      },
      every: true,
      unquoted: "=/",
    }),
  ],
  {
    bare: "text",
    relations: [relation({ name: "parent", follow: (r) => (r.parent === null ? [] : [r.parent]) })],
    dynamic: (key) => (key === "nope" ? null : kv(key)),
  },
);

// --- by name ----------------------------------------------------------------------------------
type AnySchema = Schema<Work> | Schema<Job> | Schema<Line>;

export function schemaOf(name: SchemaName): AnySchema {
  switch (name) {
    case "catalog": {
      return CATALOG;
    }
    case "units": {
      return UNITS;
    }
    case "dynamic": {
      return DYNAMIC;
    }
  }
}

const ROWS = new Map<SchemaName, readonly unknown[]>();

export function rowsOf(name: SchemaName): readonly unknown[] {
  const cached = ROWS.get(name);
  if (cached !== undefined) return cached;
  const data = load(name) as readonly object[];
  let made: readonly unknown[];
  switch (name) {
    case "catalog": {
      made = data.map((d) => work(d as Partial<Work>));
      break;
    }
    case "units": {
      made = data.map((d) => ({ year: 2020, ...(d as Partial<Job>) }));
      break;
    }
    case "dynamic": {
      made = data.map((d) => line(d as LineData));
      break;
    }
  }
  ROWS.set(name, made);
  return made;
}

const VOCABS = new Map<SchemaName, Vocabulary>();

/** The rows' vocabulary; for `dynamic`, with the data's keys counted per row. */
export function vocabularyOf(name: SchemaName): Vocabulary {
  const cached = VOCABS.get(name);
  if (cached !== undefined) return cached;
  const schema = schemaOf(name) as Schema<unknown>;
  let made = schema.vocabulary(rowsOf(name));
  if (name === "dynamic") {
    const keys = new Map<string, number>();
    for (const row of rowsOf(name) as readonly Line[]) for (const k of row.fields.keys()) keys.set(k, (keys.get(k) ?? 0) + 1);
    made = new Vocabulary(made.entries, [...keys].map(([k, n]) => vocabEntry(k, n)));
  }
  VOCABS.set(name, made);
  return made;
}
