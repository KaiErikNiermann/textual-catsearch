#!/usr/bin/env bash
# The WebKit e2e projects in Playwright's own Ubuntu image, for hosts its WebKit build does not
# run on (Arch: it wants Ubuntu's libicu74 and libxml2). Same checkout, same node_modules.
set -euo pipefail
cd "$(dirname "$0")/.."
version="$(node -p 'require("@playwright/test/package.json").version')"
exec docker run --rm --ipc=host --init \
    --user "$(id -u):$(id -g)" -e HOME=/tmp -e CI=1 \
    -v "$PWD:/work" -w /work \
    "mcr.microsoft.com/playwright:v${version}-noble" \
    bash -c 'npm install --silent --prefix /tmp/pnpm pnpm@10 && PATH=/tmp/pnpm/node_modules/.bin:$PATH pnpm exec playwright test --project webkit --project phone-webkit "$@"' -- "$@"
