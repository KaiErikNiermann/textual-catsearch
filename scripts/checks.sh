#!/usr/bin/env bash
# The pre-push gate: run by the global pre-push dispatcher, and by hand before a release.
# Lint, format, strict types, complexity, duplication, then the suite.
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

echo "▶ pytest"
poetry run pytest
