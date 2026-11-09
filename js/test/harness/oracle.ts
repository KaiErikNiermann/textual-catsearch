/**
 * The TypeScript port as a process: one JSON case per line on stdin, one answer per line on
 * stdout, `{"ok": answer}` or `{"error": message}`. The Python differential test keeps one of
 * these running and asks it every case Hypothesis generates (`tests/test_differential.py`).
 *
 * Run with `node test/harness/oracle.ts`: Node strips the types itself, so no build step
 * stands between an edit to `src/` and the next differential run.
 */

import { createInterface } from "node:readline";

import { run } from "./ops.ts";
import type { Case } from "./ops.ts";

const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });

for await (const line of lines) {
  let answer: string;
  try {
    answer = JSON.stringify({ ok: run(JSON.parse(line) as Case) });
  } catch (error) {
    answer = JSON.stringify({ error: error instanceof Error ? (error.stack ?? error.message) : String(error) });
  }
  process.stdout.write(`${answer}\n`);
}
