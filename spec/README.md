# The shared spec

The query language has two implementations: the Python package in `src/textual_catsearch` (the reference) and the TypeScript package in `js/`. This directory is how they are held to the same answers.

## What is here

- `rows/`: the rows the spec's three schemas search, as JSON. `catalog` has every field kind, aliases, a normaliser and relations; `units` has number fields with a unit parser; `dynamic` has undeclared and dotted keys, a value check, an `every` field and a relation.
- `fixtures/*.jsonl`: one `{"case": ..., "expect": ...}` per line. A case names an operation and its arguments; `expect` is what the Python package answered. About 20,000 cases: every string literal in the Python test suite, a curated list of edge cases, and a seeded random walk over each schema's grammar, run through parsing, matching, completion, rendering, the tab transforms, quoting, ranking and `fold` over every assigned code point.
- `fixtures/meta.json`: the Python and Unicode versions the fixtures were written with.

Both sides implement the same dispatcher over these cases, `tests/conformance/ops.py` and `js/test/harness/ops.ts`, over the same three schemas, `tests/conformance/schemas.py` and `js/test/harness/schemas.ts`. Keep each pair in step.

## The checks

| check | where | what it holds |
| --- | --- | --- |
| fixtures are current | `tests/test_conformance.py` | the files are exactly what the Python package answers today, and `js/src/unicode-data.ts` is exactly what this interpreter's `unicodedata` gives |
| the port matches the fixtures | `js/test/conformance.test.ts` | the TypeScript package gives the recorded answer to every case |
| differential fuzzing | `tests/test_differential.py` | Hypothesis generates cases, a running `js/test/harness/oracle.ts` and the Python package answer each one, and the answers must be equal; a disagreement shrinks to the smallest case that shows it |
| the language's own laws | `js/test/props.test.ts`, `tests/test_props.py` | totality, `parse(render(e)) == e`, spans on whole characters, negation as complement, clauses that only narrow |

## Changing behaviour

Change the Python package, then regenerate from `tests/`:

```sh
poetry run python -m conformance.generate        # spec/fixtures
poetry run python -m conformance.unicode_tables  # js/src/unicode-data.ts
```

The TypeScript suite then shows every case the port has to follow. The fixtures are written under one Unicode version (`meta.json`), and `test_conformance` skips under another, since an older interpreter folds newer characters differently.

For a long fuzzing run: `CATSEARCH_DIFF_EXAMPLES=20000 poetry run pytest tests/test_differential.py` and `FC_RUNS=20000 pnpm -C js test`.

## Where the two may differ, by design

- Offsets. Python counts code points; TypeScript counts UTF-16 code units, which is what the DOM hands out. The harness converts at the edge, so the spec is in code points.
- Characters the reference's Unicode has not assigned. Normalisation in TypeScript is the engine's (`String.prototype.normalize`), whose Unicode may be newer than Python's: Node 26 ships Unicode 17, Python 3.14 ships 16. A character assigned since (U+A7F1, say) may fold differently; the spec covers assigned characters only. Case folding, combining classes, whitespace, letters and digits all come from Python's tables, so they do not drift.
- Integers past 2^53. Python compares an integer bound exactly; TypeScript holds it as a double. `year:>9007199254740993` gives the same bound in both (it is computed exactly, then rounded), but a row value that differs from it only past the 53rd bit can compare differently.
