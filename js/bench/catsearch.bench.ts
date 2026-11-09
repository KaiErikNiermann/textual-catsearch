/**
 * What one keystroke costs: parsing, filtering, completion and folding at realistic sizes.
 *
 * Run with `pnpm bench` (tinybench, plain Node). The bar re-parses, re-filters and
 * re-completes on every keystroke, so the number that matters is the whole keystroke over the
 * rows on screen, not any one call.
 */

import { Bench } from "tinybench";

import { fold, parse, render, suggest } from "../src/index.ts";
import { CATALOG, work } from "../test/harness/schemas.ts";
import type { Work } from "../test/harness/schemas.ts";

const NAMES = ["Alan Ritchson", "Zendaya", "Timothée Chalamet", "悠木碧", "Сергей Бодров", "Diego Luna", "Adam Scott"];
const GENRES = ["action", "crime", "Sci-Fi", "drama", "comedy", "horror", "thriller", "mystery", "epic"];
const KINDS = ["movie", "tv", "game"];
const BUCKETS = ["available", "upcoming", "watched", "shelved"];

/** A deterministic catalogue of `n` works (a linear congruential sequence, not Math.random). */
function catalogue(n: number): Work[] {
  let seed = 12_345;
  const next = (k: number): number => {
    seed = (seed * 1_103_515_245 + 12_345) % 2_147_483_648;
    return seed % k;
  };
  const pick = <T>(xs: readonly T[]): T => xs[next(xs.length)] as T;
  return Array.from({ length: n }, (_, i) =>
    work({
      title: `${pick(["The", "A", "Return of", "Café", "Straße"])} ${pick(GENRES)} ${i}`,
      kind: pick(KINDS),
      years: [1950 + next(80)],
      genres: [pick(GENRES), pick(GENRES)],
      cast: [pick(NAMES), pick(NAMES)],
      bucket: pick(BUCKETS),
      platforms: next(3) === 0 ? [] : [[pick(["Netflix", "Max", "Steam"]), ["US", "DE"]]],
    }),
  );
}

const ROWS = catalogue(10_000);
const VOCAB = CATALOG.vocabulary(ROWS);
const SHORT = 'kind:tv cast:"alan rit" year:>2000';
const LONG = Array.from({ length: 6 }, (_, i) => `(kind:tv OR kind:movie) -tag:horror${i} year:${1990 + i}..2030 cast:"a, b" on:netflix@us`).join(" ");

const QUERY = parse(SHORT, CATALOG);
const ASCII = Array.from({ length: 500_000 }, (_, i) => `The Left Hand of Darkness ${i}`);
const UNICODE = Array.from({ length: 500_000 }, (_, i) => `Ｃａｆé Straße İstanbul 薬屋 ${i}`);
/** A thunk handing out `items` in turn, so every call folds a string not yet cached. */
function cycling(items: readonly string[]): () => string {
  let i = 0;
  return () => items[i++ % items.length] ?? "";
}
const nextAscii = cycling(ASCII);
const nextUnicode = cycling(UNICODE);

const suite = new Bench({ time: 500, warmupTime: 100 })
  .add("parse: short query", () => parse(SHORT, CATALOG))
  .add("parse: long query (36 clauses, groups)", () => parse(LONG, CATALOG))
  .add("render: short query", () => render(QUERY.expr, CATALOG))
  .add("10k rows: filter", () => QUERY.filter(ROWS))
  .add("10k rows: bare text search", () => parse("return 12", CATALOG).filter(ROWS))
  .add("10k rows: keystroke (parse + filter + suggest)", () => [
    parse(SHORT, CATALOG).filter(ROWS),
    suggest(SHORT, SHORT.length - 10, CATALOG, VOCAB),
  ])
  .add("10k rows: vocabulary", () => CATALOG.vocabulary(ROWS))
  .add("suggest: a value", () => suggest("cast:ti", 7, CATALOG, VOCAB))
  .add("suggest: a field", () => suggest("ca", 2, CATALOG, VOCAB))
  .add("fold: ascii, uncached", () => fold(nextAscii()))
  .add("fold: non-ascii, uncached", () => fold(nextUnicode()));

await suite.run();
console.table(suite.table());
