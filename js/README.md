# catsearch

[![npm](https://img.shields.io/npm/v/catsearch)](https://www.npmjs.com/package/catsearch)

Discord-style category search for the web. Declare the fields your rows have; get a query language over them, filtering, rendering back to text, and completion of field names and values.

```text
author:"le guin" year:1960..1980 -is:read
(format:ebook OR format:hardcover) genre:sci-fi
```

This is the TypeScript port of the Python package [`textual-catsearch`](https://github.com/KaiErikNiermann/textual-catsearch#readme), with the same language. No dependencies; 12.9 kB minified and gzipped for the whole API. It never throws on input: a half-typed query parses to the closest tree and says what it noticed.

## Quick start

```ts
import { Schema, enumField, flagField, numberField, parse, render, suggest, textField } from "catsearch";

interface Book {
  title: string;
  author: string;
  year: number;
  format: string;
  read: boolean;
}

const schema = new Schema<Book>(
  [
    textField({ name: "title", get: (b) => b.title, complete: false }),
    textField({ name: "author", get: (b) => b.author, aliases: ["by"] }),
    enumField({ name: "format", get: (b) => b.format, choices: ["hardcover", "paperback", "ebook"] }),
    numberField({ name: "year", get: (b) => b.year }),
    flagField({ name: "is", flags: { read: (b) => b.read, unread: (b) => !b.read } }),
  ],
  { bare: "title" }, // which field bare words search
);

const query = parse('by:"le guin" -is:read', schema);
query.filter(books); // the rows it keeps
query.notice; // what the parser noticed, for a status line ("" when nothing)
render(query.expr, schema); // 'author:"le guin" -is:read'
suggest("by:le", 5, schema, schema.vocabulary(books)); // completions for the token under the caret
```

The language, the field kinds (`textField`, `enumField`, `numberField`, `flagField`, `customField`), relations, dynamic fields and the tab transforms (`pinned`, `withTerm`, `without`) are the Python package's; its [README](https://github.com/KaiErikNiermann/textual-catsearch#readme) describes them. The names are camelCase here, and options are objects.

## How it differs from the Python package

- Offsets (`Diagnostic.start`, `Suggestion.start`, the `cursor` you pass to `suggest`) are UTF-16 code units, as the DOM counts them (`selectionStart`, `Range` offsets). Python counts code points.
- Integer bounds are doubles. `year:>9007199254740993` gives the same bound as in Python, but a row value that differs from it only past 2^53 can compare differently.
- Normalisation (NFKD and NFC in `fold`) is the browser's, so a character assigned after Python's Unicode version may fold differently. Case folding, combining marks, whitespace, letters and digits come from tables generated from Python's `unicodedata` and do not depend on the browser.

## The example

[`examples/search-bar`](examples/search-bar) is a search bar over a media catalogue; try it in the [docs](https://kaierikniermann.github.io/textual-catsearch/demo.html). Known field keys are drawn as monospace code chips as you type, and once a value is complete (a space typed after it, a completion taken, or the bar left) the key and its value become one chip, as Discord draws `from: user`. A value the parser rejects (`year:abc`) stays apart from its key. A dropdown of completions narrows as you type: on a keyboard, Tab takes the highlighted one and Tab again walks to the next (Shift+Tab back), arrows and Enter pick, Escape closes; on a phone, tapping an option fills in the rest of the keyword.

```sh
pnpm install
pnpm example          # dev server
pnpm e2e              # Playwright: Chromium, Firefox, WebKit, a Pixel and an iPhone
./scripts/e2e-webkit-docker.sh   # WebKit where its Linux build does not run (Arch)
```

## Checks

| command | what |
| --- | --- |
| `pnpm lint` | ESLint (strict type-checked, sonarjs, unicorn, security; CSS by `@eslint/css`) and stylelint |
| `pnpm typecheck` | `tsc` strict, with `noUncheckedIndexedAccess` and `exactOptionalPropertyTypes` |
| `pnpm test` | the shared spec's fixtures (`../spec`), fast-check properties, API tests; `FC_RUNS` sets the property budget |
| `pnpm bench` | tinybench: a keystroke over 10k rows (parse, filter, suggest) costs about 1.2 ms |
| `pnpm size` | fails above 15 kB gzipped |
| `pnpm e2e` | the example, end to end |

The differential test against the Python package lives on the Python side (`tests/test_differential.py`): it runs `test/harness/oracle.ts` with Node, which strips the types itself.
