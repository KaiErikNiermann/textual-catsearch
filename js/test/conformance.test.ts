/**
 * The golden fixtures: every case in `spec/fixtures`, answered as the Python reference did.
 *
 * The fixtures are written by `tests/conformance/generate.py` from the Python package; a
 * failure here is the port disagreeing with the reference on that exact input.
 */

import { readFileSync, readdirSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { run, sameJson } from "./harness/ops.ts";
import type { Case, Json } from "./harness/ops.ts";
import { SPEC } from "./harness/schemas.ts";

interface Fixture {
  readonly case: Case;
  readonly expect: Json;
}

const DIR = `${SPEC}fixtures/`;
const FILES = readdirSync(DIR).filter((f) => f.endsWith(".jsonl")).toSorted((a, b) => a.localeCompare(b));

describe.each(FILES)("%s", (file) => {
  const fixtures = readFileSync(DIR + file, "utf8")
    .split("\n")
    .filter((line) => line.length > 0)
    .map((line) => JSON.parse(line) as Fixture);

  it(`answers all ${fixtures.length} cases as the Python reference does`, () => {
    const wrong: { case: Case; expected: Json; got: Json | string }[] = [];
    for (const fixture of fixtures) {
      let got: Json | string;
      try {
        got = run(fixture.case);
      } catch (error) {
        got = `threw: ${String(error)}`;
      }
      if (!sameJson(got, fixture.expect)) wrong.push({ case: fixture.case, expected: fixture.expect, got });
    }
    // The first few disagreements, whole: a count alone says nothing about what to fix.
    expect(wrong.slice(0, 5)).toEqual([]);
    expect(wrong).toHaveLength(0);
  });
});
