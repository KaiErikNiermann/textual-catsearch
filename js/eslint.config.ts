import css from "@eslint/css";
import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import security from "eslint-plugin-security";
import sonarjs from "eslint-plugin-sonarjs";
import unicorn from "eslint-plugin-unicorn";
import { tailwind4 } from "tailwind-csstree";
import tseslint from "typescript-eslint";

export default defineConfig([
  // unicode-data.ts is generated from Python (tests/conformance/unicode_tables.py).
  globalIgnores(["src/unicode-data.ts", "dist/", "node_modules/", ".scratch/", "test-results/", "playwright-report/", "examples/**/dist/"]),
  {
    files: ["**/*.ts"],
    extends: [
      js.configs.recommended,
      tseslint.configs.strictTypeChecked,
      tseslint.configs.stylisticTypeChecked,
      sonarjs.configs.recommended,
      unicorn.configs.recommended,
      security.configs.recommended,
    ],
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    rules: {
      // Names that mirror the Python reference (`rpartition`, `lstrip`, `cp`) are the point:
      // the port is read side by side with it.
      "unicorn/prevent-abbreviations": "off",
      "unicorn/name-replacements": "off",
      "unicorn/consistent-boolean-name": "off",
      // UTF-16 code units and code points are both deliberate here: offsets are UTF-16 (the
      // DOM's), while Python iterates code points, and `[...text]` is that iteration.
      "unicorn/prefer-code-point": "off",
      "@typescript-eslint/no-misused-spread": "off",
      // JSDoc house style: leading asterisks, and one-line block comments.
      "unicorn/no-asterisk-prefix-in-documentation-comments": "off",
      "unicorn/single-line-block-comment-style": "off",
      // `null` is a value the API speaks: a declined dynamic key, an open range end.
      "unicorn/no-null": "off",
      // Loops with indices are how the lexer walks UTF-16 code units.
      "unicorn/no-for-loop": "off",
      // `switch` over the closed `kind` union, with exhaustiveness checked by the compiler.
      "unicorn/prefer-switch": "off",
      "unicorn/no-array-reduce": "off",
      "@typescript-eslint/switch-exhaustiveness-check": ["error", { considerDefaultExhaustiveForUnions: true }],
      // Iterator helpers (`.keys().toArray()`) are Baseline only since 2025; a spread works in
      // every engine the library supports.
      "unicorn/prefer-iterator-to-array": "off",
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
    },
  },
  {
    // The harness, the tests and the tools read JSON whose shape the code checks as it goes.
    files: ["test/**/*.ts", "bench/**/*.ts", "scripts/**/*.ts", "e2e/**/*.ts"],
    rules: {
      "security/detect-non-literal-fs-filename": "off",
      "security/detect-object-injection": "off",
      "sonarjs/no-nested-functions": "off",
      "unicorn/no-process-exit": "off",
      // `page.evaluate` bodies run in the page, where `document` and friends are the globals.
      "unicorn/isolated-functions": ["error", { overrideGlobals: { document: "readonly", window: "readonly", getComputedStyle: "readonly", ClipboardEvent: "readonly" } }],
      // fast-check arbitraries are built by nesting combinators; that is the library's idiom.
      "unicorn/max-nested-calls": "off",
    },
  },
  {
    files: ["src/**/*.ts"],
    rules: {
      // Every bracketed index in src is into a typed array or string at a computed offset.
      "security/detect-object-injection": "off",
    },
  },
  {
    files: ["examples/**/*.css"],
    language: "css/css",
    plugins: { css },
    extends: ["css/recommended"],
    languageOptions: { customSyntax: tailwind4 },
    rules: {
      "css/use-baseline": ["error", { available: "newly" }],
      "css/no-important": "error",
      "css/prefer-logical-properties": "error",
      // Each file wraps itself in its layer (so each can be checked alone); imports carry none.
      "css/use-layers": ["error", { requireImportLayers: false }],
      "css/selector-complexity": ["error", { maxCompounds: 2, maxTypes: 1 }],
      "css/relative-font-units": ["error", { allowUnits: ["rem", "em"] }],
      "css/font-family-fallbacks": "error",
      // Tokens are defined in tokens.css and used everywhere else: unknown to a per-file check.
      "css/no-invalid-properties": ["error", { allowUnknownVariables: true }],
    },
  },
]);
