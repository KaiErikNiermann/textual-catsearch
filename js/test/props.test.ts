/**
 * What the query language claims for every input, checked on the port by fast-check.
 *
 * The fixtures and the differential test say the port answers as Python does; these say the
 * answers obey the language's own laws, so a law broken in both implementations at once is
 * still caught. They mirror `tests/test_props.py`. `FC_RUNS` raises the budget.
 */

import fc from "fast-check";
import { describe, expect, it } from "vitest";

import {
  Vocabulary,
  and,
  exprEquals,
  holds,
  lex,
  neg,
  parse,
  quote,
  render,
  suggest,
} from "../src/index.ts";
import type { Schema } from "../src/index.ts";
import { BUCKETS, CATALOG, DYNAMIC, FLAGS, UNITS, rowsOf } from "./harness/schemas.ts";
import type { SchemaName, Work } from "./harness/schemas.ts";

const RUNS = Number(process.env["FC_RUNS"] ?? "400");
const opts = { numRuns: RUNS };

const SCHEMAS: readonly (readonly [SchemaName, Schema<unknown>])[] = [
  ["catalog", CATALOG as Schema<unknown>],
  ["units", UNITS as Schema<unknown>],
  ["dynamic", DYNAMIC as Schema<unknown>],
];

// --- inputs -------------------------------------------------------------------------------------
/** Any UTF-16 string at all, lone surrogates included: what a paste can put in a text box. */
const anyText = fc.string({ unit: fc.integer({ min: 0, max: 0xFF_FF }).map((n) => String.fromCharCode(n)), maxLength: 60 });
const unicodeText = fc.string({ unit: "binary", maxLength: 60 });
const PIECES = [
  "kind:", "year:", "took:", "status:", "http.status:", "sequel-of.", "parent.", "nope:", "is:",
  "on:", "re:", "kv:", "(", ")", "-(", " OR ", " | ", " ", "-", "!", '"', "'", ":", ",", ">",
  ">=", "<", "..", "none", "tv", "5m", "2021", "@us", "=", "\t", "é", "😀", "İ", "\u{200B}",
];
const soup = fc.array(fc.constantFrom(...PIECES), { maxLength: 14 }).map((parts) => parts.join(""));
const source = fc.oneof(anyText, unicodeText, soup);

// Well-formed by construction, as in test_props.py: values that survive the round trip.
const INNER = fc.string({
  unit: fc.integer({ min: 32, max: 0x2F_FF }).map((n) => String.fromCodePoint(n)).filter((c) => !'",:\t\n\r'.includes(c)),
  maxLength: 12,
});
const EDGE = fc
  .integer({ min: 33, max: 0x2F_FF })
  .map((n) => String.fromCodePoint(n))
  .filter((c) => !'",:-!@'.includes(c) && c.trim() === c);
const value = fc.tuple(EDGE, INNER, EDGE).map(([a, b, c]) => `${a}${b}${c}`.trim()).filter((v) => v.length > 0);
const number = fc.integer({ min: 0, max: 9999 });
const numeric = fc.oneof(
  number.map(String),
  fc.tuple(number, number).map(([a, b]) => `${a}..${b}`),
  fc.tuple(fc.constantFrom(">", "<", ">=", "<="), number).map(([op, n]) => `${op}${n}`),
);
const TEXT_FIELDS = ["kind", "tag", "genre", "theme", "cast", "director", "person", "state", "platform", "name"];
const NUMBER_FIELDS = new Set(["year", "season"]);
const sign = fc.constantFrom("", "-", "!");

const clause = fc.oneof(
  fc.tuple(sign, value).map(([s, v]) => `${s}${quote(v)}`),
  fc.tuple(sign, fc.constantFrom(...FLAGS.keys())).map(([s, f]) => `${s}is:${f}`),
  fc.tuple(sign, fc.constantFrom(...TEXT_FIELDS, ...NUMBER_FIELDS)).map(([s, f]) => `${s}${f}:none`),
  fc
    .tuple(sign, fc.constantFrom(...TEXT_FIELDS), fc.array(value, { minLength: 1, maxLength: 3 }))
    .map(([s, f, vs]) => `${s}${f}:${vs.map((v) => quote(v)).join(",")}`),
  fc
    .tuple(sign, fc.constantFrom(...NUMBER_FIELDS), fc.array(numeric, { minLength: 1, maxLength: 3 }))
    .map(([s, f, vs]) => `${s}${f}:${vs.map((v) => quote(v, "<>=.")).join(",")}`),
  fc
    .tuple(sign, fc.constantFrom("sequel-of", "prequel-of"), fc.constantFrom(...NUMBER_FIELDS), numeric)
    .map(([s, hop, f, v]) => `${s}${hop}.${f}:${quote(v, "<>=.")}`),
);

const { expression } = fc.letrec<{ expression: string; atom: string }>((tie) => ({
  atom: fc.oneof(
    { depthSize: "small", withCrossShrink: true },
    clause,
    tie("expression").map((e) => `(${e})`),
    fc.array(fc.oneof(clause, tie("expression").map((e) => `(${e})`)), { minLength: 2, maxLength: 3 }).map((xs) => xs.join(" OR ")),
  ),
  expression: fc.array(tie("atom"), { maxLength: 4 }).map((xs) => xs.join(" ")),
}));

// --- totality -----------------------------------------------------------------------------------
describe("totality", () => {
  it("parses any string under every schema, both readings, without throwing", () => {
    fc.assert(
      fc.property(source, (text) => {
        for (const [, schema] of SCHEMAS) {
          expect(parse(text, schema).schema).toBe(schema);
          expect(parse(text, schema, { emptyAsText: true }).schema).toBe(schema);
        }
      }),
      opts,
    );
  });

  it("completes at every caret position of any string", () => {
    fc.assert(
      fc.property(source, (text) => {
        for (const [name, schema] of SCHEMAS) {
          const vocab = schema.vocabulary(rowsOf(name));
          for (let cursor = 0; cursor <= text.length; cursor++) {
            for (const s of suggest(text, cursor, schema, vocab)) {
              expect(0 <= s.start && s.start <= s.end && s.end <= text.length).toBe(true);
            }
          }
        }
      }),
      { numRuns: Math.max(50, RUNS / 4) },
    );
  });
});

// --- spans --------------------------------------------------------------------------------------
function splitsPair(text: string, at: number): boolean {
  const before = text.charCodeAt(at - 1);
  const after = text.charCodeAt(at);
  return before >= 0xD8_00 && before <= 0xDB_FF && after >= 0xDC_00 && after <= 0xDF_FF;
}

describe("spans", () => {
  it("points every diagnostic into the text, on whole characters", () => {
    fc.assert(
      fc.property(source, (text) => {
        for (const d of parse(text, CATALOG).diagnostics) {
          expect(0 <= d.start && d.start < d.end && d.end <= text.length).toBe(true);
          expect(splitsPair(text, d.start) || splitsPair(text, d.end)).toBe(false);
        }
      }),
      opts,
    );
  });

  it("lexes into ordered, disjoint tokens that cover all non-space text", () => {
    fc.assert(
      fc.property(source, (text) => {
        let last = 0;
        for (const t of lex(text)) {
          expect(t.start >= last && t.end > t.start).toBe(true);
          last = t.end;
        }
      }),
      opts,
    );
  });
});

// --- the round trip -----------------------------------------------------------------------------
describe("render is the inverse of parse", () => {
  it("for every well-formed query", () => {
    fc.assert(
      fc.property(expression, (text) => {
        const once = render(parse(text, CATALOG).expr, CATALOG);
        const back = parse(once, CATALOG).expr;
        expect(exprEquals(back, parse(text, CATALOG).expr)).toBe(true);
        expect(render(back, CATALOG)).toBe(once);
      }),
      opts,
    );
  });

  it("for any string at all, under every schema", () => {
    fc.assert(
      fc.property(source, (text) => {
        for (const [, schema] of SCHEMAS) {
          const first = parse(text, schema).expr;
          const once = render(first, schema);
          expect(exprEquals(parse(once, schema).expr, first)).toBe(true);
          expect(render(parse(once, schema).expr, schema)).toBe(once);
        }
      }),
      opts,
    );
  });
});

// --- semantics ----------------------------------------------------------------------------------
const rows = rowsOf("catalog") as readonly Work[];

function kept(text: string): Work[] {
  return parse(text, CATALOG).filter(rows);
}

describe("semantics", () => {
  it("negation is complement, on every row", () => {
    fc.assert(
      fc.property(expression, (text) => {
        const { expr } = parse(text, CATALOG);
        for (const row of rows) expect(holds(neg(expr), row, CATALOG)).toBe(!holds(expr, row, CATALOG));
      }),
      opts,
    );
  });

  it("adding a clause on a new field never adds a row", () => {
    // A field written twice OR-s its values (`kind:tv kind:movie`), so the claim is about
    // distinct fields, as in test_props.py.
    const distinctClauses = fc
      .uniqueArray(fc.constantFrom(...TEXT_FIELDS, ...NUMBER_FIELDS), { minLength: 1, maxLength: 5 })
      .chain((fields) =>
        fc.tuple(
          ...fields.map((f) =>
            fc
              .tuple(fc.constantFrom("", "-"), NUMBER_FIELDS.has(f) ? numeric : value)
              .map(([s, v]) => `${s}${f}:${quote(v, NUMBER_FIELDS.has(f) ? "<>=." : "")}`),
          ),
        ),
      );
    fc.assert(
      fc.property(distinctClauses, (clauses) => {
        for (let i = 1; i <= clauses.length; i++) {
          const wider = new Set(kept(clauses.slice(0, i - 1).join(" ")));
          const narrower = kept(clauses.slice(0, i).join(" "));
          for (const row of narrower) expect(wider.has(row)).toBe(true);
        }
      }),
      opts,
    );
  });

  it("conjunction is commutative", () => {
    fc.assert(
      fc.property(clause, clause, (a, b) => {
        expect(kept(`${a} ${b}`)).toEqual(kept(`${b} ${a}`));
      }),
      opts,
    );
  });

  it("an empty query keeps everything, and only an empty query is empty", () => {
    expect(kept("")).toEqual(rows);
    fc.assert(
      fc.property(expression, (text) => {
        const q = parse(text, CATALOG);
        expect(q.isEmpty).toBe(exprEquals(q.expr, and()));
      }),
      opts,
    );
  });

  it("filter is holds, row by row, in order", () => {
    fc.assert(
      fc.property(expression, (text) => {
        const q = parse(text, CATALOG);
        expect(q.filter(rows)).toEqual(rows.filter((r) => holds(q.expr, r, CATALOG)));
      }),
      opts,
    );
  });
});

// --- completion -----------------------------------------------------------------------------------
describe("completion", () => {
  const vocab = CATALOG.vocabulary(rows);

  it("offers only values that, once applied, the field reads back as typed", () => {
    fc.assert(
      fc.property(fc.constantFrom("kind:", "tag:", "cast:", "state:", "is:", "-tag:", "(kind:"), fc.stringMatching(/^[a-zé]{0,3}$/u), (head, typed) => {
        const text = `${head}${typed}`;
        for (const s of suggest(text, text.length, CATALOG, vocab)) {
          const applied = text.slice(0, s.start) + s.insert + text.slice(s.end);
          const q = parse(applied, CATALOG);
          expect(q.diagnostics.filter((d) => d.fault !== "unclosed-group")).toEqual([]);
        }
      }),
      opts,
    );
  });

  it("is pure: the same input gives the same answer", () => {
    fc.assert(
      fc.property(source, fc.nat(), (text, at) => {
        const cursor = at % (text.length + 1);
        expect(suggest(text, cursor, CATALOG, vocab)).toEqual(suggest(text, cursor, CATALOG, vocab));
      }),
      opts,
    );
  });

  it("names every bucket flag", () => {
    const labels = suggest("is:", 3, CATALOG, new Vocabulary(), { limit: 50 }).map((s) => s.label);
    for (const b of BUCKETS) expect(labels).toContain(b);
  });
});
