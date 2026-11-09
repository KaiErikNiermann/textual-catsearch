/**
 * The library's cost to a page: the whole public API bundled, minified and compressed.
 *
 * Fails above the budget, so growth is a decision rather than drift. `pnpm size`.
 */

import { gzipSync } from "node:zlib";

import { build } from "esbuild";

const result = await build({
  entryPoints: [new URL("../src/index.ts", import.meta.url).pathname],
  bundle: true,
  minify: true,
  format: "esm",
  target: "es2023",
  write: false,
});
const [file] = result.outputFiles;
if (file === undefined) throw new Error("esbuild wrote nothing");
// Measured at 12.9 kB gzipped (4 kB of it Unicode tables) when this budget was set; the
// headroom is for growth that was chosen, not for drift.
const BUDGET_GZIP = 15_000;
const gzip = gzipSync(file.contents, { level: 9 }).length;
process.stdout.write(`minified ${file.contents.length} B, gzipped ${gzip} B (budget ${BUDGET_GZIP} B)\n`);
if (gzip > BUDGET_GZIP) process.exitCode = 1;
