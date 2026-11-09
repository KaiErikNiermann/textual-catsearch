/**
 * The TypeScript surface itself: what the fixtures cannot show because they only see JSON,
 * such as schema construction errors, the dynamic-key cache, offsets in UTF-16 and typed rows.
 */

import { describe, expect, it } from "vitest";

import {
  Fault,
  Schema,
  Vocabulary,
  apply,
  customField,
  enumField,
  flagField,
  numberField,
  parse,
  pinned,
  render,
  suggest,
  term,
  textField,
  withTerm,
  without,
} from "../src/index.ts";
import type { Field } from "../src/index.ts";

interface Book {
  readonly title: string;
  readonly authors: readonly string[];
  readonly year: number;
  readonly format: string;
  readonly read: boolean;
}

const books = new Schema<Book>(
  [
    textField({ name: "title", get: (b) => b.title, aliases: ["name"], complete: false }),
    textField({ name: "author", get: (b) => b.authors }),
    enumField({ name: "format", get: (b) => b.format, choices: ["hardcover", "ebook"] }),
    numberField({ name: "year", get: (b) => b.year }),
    flagField({ name: "is", flags: { read: (b) => b.read } }),
  ],
  { bare: "title" },
);

const LIBRARY: readonly Book[] = [
  { title: "The Left Hand of Darkness", authors: ["Ursula K. Le Guin"], year: 1969, format: "ebook", read: true },
  { title: "Dune", authors: ["Frank Herbert"], year: 1965, format: "hardcover", read: false },
  { title: "Piranesi", authors: ["Susanna Clarke"], year: 2020, format: "ebook", read: false },
];

const get = (b: Book): string => b.title;

describe("schemas", () => {
  it("refuses a name claimed twice, an alias shadowing a field, and a bad bare field", () => {
    expect(() => new Schema<Book>([textField({ name: "a", get }), textField({ name: "a", get })], { bare: "a" })).toThrow(
      /claimed twice/u,
    );
    expect(
      () => new Schema<Book>([textField({ name: "a", get }), textField({ name: "b", get, aliases: ["a"] })], { bare: "a" }),
    ).toThrow(/shadows/u);
    expect(() => new Schema<Book>([numberField({ name: "y", get: (b) => b.year })], { bare: "y" })).toThrow(/bare field/u);
    expect(() => new Schema<Book>([textField({ name: "Bad", get })], { bare: "Bad" })).toThrow(/must match/u);
  });

  it("asks dynamic once per key and refuses a field misnamed for its key", () => {
    const asked: string[] = [];
    const s = new Schema<Book>([textField({ name: "title", get: (b) => b.title })], {
      bare: "title",
      dynamic: (key): Field<Book> => {
        asked.push(key);
        return customField({ name: key, test: () => true });
      },
    });
    // `-status:3` excludes every row, since this dynamic field's test holds for any value.
    expect(parse("status:1 status:2 -status:3", s).filter(LIBRARY)).toEqual([]);
    parse("status:4", s);
    expect(asked).toEqual(["status"]);
    const wrong = new Schema<Book>([textField({ name: "title", get: (b) => b.title })], {
      bare: "title",
      dynamic: () => customField({ name: "other", test: () => true }),
    });
    expect(() => parse("key:1", wrong)).toThrow(/not the key/u);
  });
});

describe("queries", () => {
  it("filters, renders and reports as the README promises", () => {
    const q = parse('author:"le guin" year:1960..1980 -is:read', books);
    expect(q.filter(LIBRARY)).toEqual([]);
    expect(parse("year:1960..1980 -is:read", books).filter(LIBRARY).map((b) => b.title)).toEqual(["Dune"]);
    expect(render(q.expr, books)).toBe('author:"le guin" year:1960..1980 -is:read');
    expect(parse("format:EBOOK", books).filter(LIBRARY)).toHaveLength(2);
    expect(parse("nope:x", books).diagnostics.map((d) => d.fault)).toEqual([Fault.UNKNOWN_FIELD]);
    expect(parse("year:soon", books).notice).toBe("year:soon: not a number");
  });

  it("counts offsets in UTF-16 code units, as the DOM does", () => {
    const text = "😀 nope:x";
    const [d] = parse(text, books).diagnostics;
    if (d === undefined) throw new Error("expected a diagnostic");
    expect(d.start).toBe(3);
    expect(text.slice(d.start, d.end)).toBe("nope");
    const [s] = suggest("😀 form", 7, books, books.vocabulary(LIBRARY));
    expect(s === undefined ? "" : apply("😀 form", s)).toBe("😀 format:");
  });

  it("pins and unpins a category as tabs do", () => {
    const q = parse("dune is:read", books);
    expect(pinned(q, "is", ["read"])).toBe("read");
    expect(withTerm(q, term("format", { values: ["ebook"] }))).toBe("format:ebook dune is:read");
    expect(without(q, "is")).toBe("dune");
  });

  it("completes values from the rows, most used first", () => {
    const vocab = books.vocabulary(LIBRARY);
    expect(suggest("format:", 7, books, vocab).map((s) => s.label)).toEqual(["ebook", "hardcover"]);
    // With no rows to count, the declared choices rank alphabetically.
    expect(suggest("format:", 7, books, new Vocabulary()).map((s) => s.label)).toEqual(["ebook", "hardcover"]);
  });
});
