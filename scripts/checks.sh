#!/usr/bin/env bash
# The pre-push gate: run by the global pre-push dispatcher, and by hand before a release.
# Lint, format, strict types, complexity, duplication, the suite, then the TypeScript port.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "▶ ruff check"
poetry run ruff check src tests examples
echo "▶ ruff format"
poetry run ruff format --check src tests examples
echo "▶ pyright (strict)"
poetry run pyright

# Grade C is flagged, D and worse fail: the C functions are exhaustive dispatches over the
# field kinds and comparison operators, where splitting would only hide the table.
echo "▶ radon"
poetry run radon cc -n C -s src
if [ -n "$(poetry run radon cc -n D src)" ]; then
    echo "✗ functions above complexity grade C" >&2
    exit 1
fi

if command -v jscpd >/dev/null; then
    echo "▶ jscpd"
    jscpd --config .jscpd.json --silent
else
    echo "▷ jscpd not installed, duplication not checked" >&2
fi

# The conformance and differential tests ask the TypeScript port too; without node they would
# skip, so the gate requires it rather than pass on a suite that did not run.
echo "▶ pytest"
CATSEARCH_REQUIRE_NODE=1 poetry run pytest

echo "▶ js: install"
pnpm -C js install --frozen-lockfile --silent
echo "▶ js: lint"
pnpm -C js lint
echo "▶ js: typecheck"
pnpm -C js typecheck
echo "▶ js: tests (spec fixtures, properties, API)"
pnpm -C js test
echo "▶ js: size"
pnpm -C js size
# The principled-css markup rules (Tailwind arbitrary values, !important, breakpoint ladders in
# class attributes): they live in the local skill, so they run where it is installed. Python
# 3.13, since semgrep's ruamel-yaml-clib does not build for a free-threaded 3.14.
rules="$HOME/.claude/skills/principled-css/rules/principled-css.yml"
if [ -f "$rules" ]; then
    echo "▶ semgrep (principled-css)"
    EIO_BACKEND=posix uvx --python 3.13 --from semgrep semgrep --quiet --metrics off --error \
        --config "$rules" js/examples/search-bar
else
    echo "▷ principled-css rules not installed, markup not checked" >&2
fi

# WebKit's Linux build needs Ubuntu's libraries; CI runs it, and
# js/scripts/e2e-webkit-docker.sh runs it here.
echo "▶ js: e2e (Chromium, Firefox, Chromium phone)"
pnpm -C js e2e --project chromium --project firefox --project phone-chromium
