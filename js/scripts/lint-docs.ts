/**
 * Lint the docs' own front end: the stylesheets (`../docs/_static/css`) with the same CSS rules as
 * the example, and the two page scripts (`../docs/_static/*.js`) with ESLint's and unicorn's
 * recommended rules. The vendored ninja-keys bundle is not ours to lint.
 *
 * ESLint ignores files outside the directory its config lives in, and the docs live beside `js/`,
 * not in it; the API takes the docs directory as its base instead. One difference from the
 * example: no `css/use-layers`, since Furo's stylesheet is unlayered and an unlayered rule beats
 * every layered one (docs/_static/css/tokens.css says more). And two type selectors are allowed:
 * Furo styles tables as `table.docutils th`, and an override has to match that specificity.
 */

import css from "@eslint/css";
import js from "@eslint/js";
import { ESLint } from "eslint";
import globals from "globals";
import path from "node:path";
import unicorn from "eslint-plugin-unicorn";
import { cssRules } from "../eslint.config.ts";

const docs = path.resolve(import.meta.dirname, "../../docs");

const eslint = new ESLint({
  cwd: docs,
  fix: process.argv.includes("--fix"),
  overrideConfigFile: true,
  overrideConfig: [
    { ignores: ["_build/**", "_static/vendor/**"] },
    {
      files: ["_static/*.js"],
      ...js.configs.recommended,
      languageOptions: { globals: globals.browser, sourceType: "module" },
    },
    { files: ["_static/*.js"], ...unicorn.configs.recommended },
    {
      // The house style of eslint.config.ts: JSDoc with leading asterisks, one-line block comments,
      // and short names (`doc`) where the scope is a few lines.
      files: ["_static/*.js"],
      rules: {
        "unicorn/no-asterisk-prefix-in-documentation-comments": "off",
        "unicorn/single-line-block-comment-style": "off",
        "unicorn/name-replacements": "off",
        "unicorn/prevent-abbreviations": "off",
      },
    },
    { files: ["_static/css/*.css"], language: "css/css", plugins: { css }, rules: { ...cssRules, "css/selector-complexity": ["error", { maxCompounds: 2, maxTypes: 2 }] } },
  ],
});

const results = await eslint.lintFiles(["_static/css/*.css", "_static/*.js"]);
await ESLint.outputFixes(results);
const formatter = await eslint.loadFormatter("stylish");
const report = await formatter.format(results);
if (report) process.stdout.write(report);
if (results.length === 0) throw new Error(`nothing to lint under ${docs}/_static`);
process.exitCode = results.some((r) => r.errorCount > 0) ? 1 : 0;
