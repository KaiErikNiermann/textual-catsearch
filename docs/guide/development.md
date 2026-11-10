# Developer guide

How the repository is laid out, how to run the checks, and what to update when behaviour changes.

## Layout

| path | what |
| --- | --- |
| `src/textual_catsearch/` | the Python package, and the reference implementation of the language |
| `src/textual_catsearch/widgets/` | the Textual widgets: `SearchBar`, `CompletingInput`, `TextInput`, `Cycle` |
| `tests/` | the Python suite: unit and property tests, the conformance generator, the differential test |
| `js/src/` | the TypeScript port, module for module (`lexer`, `parser`, `evaluate`, `render`, `complete`, `transform`) |
| `js/test/`, `js/e2e/`, `js/bench/` | vitest and fast-check tests, Playwright tests of the example, tinybench benchmarks |
| `js/examples/search-bar/` | the web demo: Vite, Tailwind v4, plain TypeScript |
| `spec/` | the shared spec both implementations are tested against (its [README](https://github.com/KaiErikNiermann/textual-catsearch/blob/master/spec/README.md) has the details) |
| `docs/` | this site: Sphinx, Furo, MyST |
| `scripts/checks.sh` | the full gate, run by the pre-push hook |

## Setup

You need Python 3.13+, Poetry, Node 22.18+ and pnpm.

```sh
poetry install --with docs
pnpm -C js install
pnpm -C js exec playwright install chromium firefox webkit   # for the e2e tests
```

## Checks

`scripts/checks.sh` runs everything the pre-push hook and CI run. The parts:

```sh
# Python
poetry run ruff check . && poetry run ruff format --check .
poetry run pyright                           # strict
poetry run radon cc -n D -s src              # nothing above grade C may print
CATSEARCH_REQUIRE_NODE=1 poetry run pytest   # includes the conformance and differential tests

# TypeScript
pnpm -C js lint          # ESLint (strict type-checked, sonarjs, unicorn, security), CSS lint, stylelint
pnpm -C js typecheck     # tsc strict
pnpm -C js test          # spec fixtures, fast-check properties, API tests
pnpm -C js size          # fails above 15 kB gzipped
pnpm -C js e2e           # the demo in Chromium, Firefox, WebKit, a Pixel and an iPhone

# Docs
make -C docs html        # Sphinx with warnings as errors, then the demo into _build/html/search-bar/
```

The conformance and differential tests run the TypeScript port with Node, which strips the types itself, so they need no build. With `CATSEARCH_REQUIRE_NODE=1` a missing `node` fails the suite instead of skipping those tests.

WebKit's Linux build needs Ubuntu's libraries. Where it does not run (Arch, say), `js/scripts/e2e-webkit-docker.sh` runs the WebKit projects in Playwright's Docker image.

## Changing behaviour

The Python package is the reference. A change to what the language answers goes in this order:

1. Change `src/textual_catsearch/` and its tests.
2. Regenerate the spec: `poetry run python -m conformance.generate` from `tests/` (and `python -m conformance.unicode_tables` if the Unicode handling changed).
3. Run `pnpm -C js test`: every case the port now gets wrong shows up as a failing fixture. Fix `js/src/` until it passes.
4. Run the differential test with a bigger budget for anything subtle: `CATSEARCH_DIFF_EXAMPLES=20000 poetry run pytest tests/test_differential.py`.

A new public name goes in `__all__` (Python) or `js/src/index.ts` (TypeScript), and on the matching [API page](../reference/python.md). `tests/test_docs.py` fails when a public name is missing from its page.

## Docs

```sh
make -C docs html          # build into docs/_build/html, demo included
make -C docs serve         # the same, served on http://localhost:8000
```

The site is Furo with a thin layer of its own: `docs/_static/css/` (tokens first, then adjustments to Furo's elements, then the site's components; every literal is a token in `tokens.css`), the sidebar brand in `docs/_templates/sidebar/brand.html`, and a Ctrl+K command palette whose index `docs/_ext/command_palette.py` writes at the end of each build. The demo page embeds the built example from the same origin, and `docs/_static/demo-embed.js` sizes the frame to its content and passes the docs' theme into it.

The usage guide includes the README's sections between the `docs:guide` markers, so the README stays the one copy of that text.

Pushing to `master` deploys the site to GitHub Pages (`.github/workflows/pages.yml`).

## Releases

Pushing a `v*` tag runs `.github/workflows/release.yml`: the full gate on the tagged commit, a check that the tag matches the version in `pyproject.toml`, then the distributions attached to a GitHub release. Publishing to PyPI is wired but skips until a trusted publisher is set up.
