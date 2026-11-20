set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

# The repository on GitHub, named so gh never has to guess it.
repo := "KaiErikNiermann/textual-catsearch"

# List recipes
default:
    @just --list

# --- Development setup ---

# Install the Python package with the docs group, and the TypeScript port (frozen lockfile)
install:
    poetry install --with docs
    pnpm -C js install --frozen-lockfile

# Install the browsers the e2e tests drive
install-browsers:
    pnpm -C js exec playwright install chromium firefox webkit

# --- Python ---

# Ruff lint and format check
lint-py:
    poetry run ruff check src tests examples docs
    poetry run ruff format --check src tests examples docs

# Format the Python code and apply Ruff's fixes
fmt-py:
    poetry run ruff check --fix src tests examples docs
    poetry run ruff format src tests examples docs

# Pyright in strict mode
typecheck-py:
    poetry run pyright

# Cyclomatic complexity: grade C is listed, nothing may print at D or worse
complexity:
    poetry run radon cc -n C -s src
    test -z "$(poetry run radon cc -n D src)"

# The Python suite, conformance and differential tests included (needs node)
test-py *args:
    CATSEARCH_REQUIRE_NODE=1 poetry run pytest {{ args }}

# The differential test against the TypeScript port with a bigger Hypothesis budget
test-diff examples="20000":
    CATSEARCH_DIFF_EXAMPLES={{ examples }} CATSEARCH_REQUIRE_NODE=1 poetry run pytest tests/test_differential.py

# --- Spec ---
#
# The Python package is the reference: after a change to what the language answers,
# regenerate the fixtures, then fix js/src/ until `just test-ts` passes.

# Regenerate the golden fixtures in spec/ from the Python reference
spec:
    cd tests && poetry run python -m conformance.generate

# Regenerate the TypeScript port's Unicode tables from Python's unicodedata
spec-unicode:
    cd tests && poetry run python -m conformance.unicode_tables

# --- TypeScript ---

# Compile the port to js/dist/
build-ts:
    pnpm -C js build

# ESLint, stylelint and the docs CSS lint
lint-ts:
    pnpm -C js lint

# tsc in strict mode
typecheck-ts:
    pnpm -C js typecheck

# vitest: spec fixtures, fast-check properties, API tests
test-ts *args:
    pnpm -C js test {{ args }}

# Minified gzip size of the port (fails above its budget)
size:
    pnpm -C js size

# Playwright tests of the demo in Chromium, Firefox and a Chromium phone
e2e *args:
    pnpm -C js e2e --project chromium --project firefox --project phone-chromium {{ args }}

# Every Playwright project, WebKit included (WebKit needs Ubuntu's libraries)
e2e-all *args:
    pnpm -C js e2e {{ args }}

# The WebKit projects in Playwright's Docker image, for hosts where WebKit does not run
e2e-webkit:
    js/scripts/e2e-webkit-docker.sh

# tinybench: parse, filter and suggest over 10k rows
bench:
    pnpm -C js bench

# Serve the search-bar demo with Vite
example:
    pnpm -C js example

# --- Docs ---

# Build the site (Sphinx, warnings are errors) with the demo, into docs/_build/html
docs:
    make -C docs html

# Build the site and serve it on http://localhost:8000
docs-serve:
    make -C docs serve

# --- Combined ---

# Every check the pre-push hook and CI run (scripts/checks.sh)
check:
    scripts/checks.sh

# Copy-paste detection over both implementations
dup:
    jscpd --config .jscpd.json

# Remove build output
clean:
    make -C docs clean
    rm -rf dist js/dist js/examples/search-bar/dist js/test-results js/playwright-report

# --- Versioning ---
#
# The version lives in pyproject.toml and js/package.json, and release.yml fails a tag
# that does not match both. docs/conf.py reads it from pyproject.toml.

# Show the version
version:
    @just _version

# Fail unless pyproject.toml and js/package.json carry the same version
version-check:
    #!/usr/bin/env bash
    set -euo pipefail
    python="$(poetry version --short)"
    js="$(node -p 'require("./js/package.json").version')"
    if [ "$python" != "$js" ]; then
      echo "error: pyproject.toml has $python, js/package.json has $js" >&2
      exit 1
    fi
    echo "$python"

# Commits since the last tag, to write the release notes from
changes:
    @git log --format='%h %s' "$(git describe --tags --abbrev=0)..HEAD"

# Internal: print the version from its source of truth
_version:
    @poetry version --short

# Internal: write the version everywhere it lives
_sync-versions version:
    poetry version "{{ version }}" >/dev/null
    pnpm -C js version "{{ version }}" --no-git-tag-version --allow-same-version >/dev/null
    @echo "Synced every version to {{ version }}"

# Internal: strip an optional leading 'v' and validate X.Y.Z[-pre] (prints it)
_normalize-version version:
    #!/usr/bin/env bash
    set -euo pipefail
    v="{{ version }}"
    v="${v#v}"
    if [[ ! "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
      echo "error: invalid version '{{ version }}', expected X.Y.Z (a leading v is allowed)" >&2
      exit 1
    fi
    printf '%s' "$v"

# Internal: the next version for a bump kind (major | minor | patch)
_bumped kind:
    #!/usr/bin/env bash
    set -euo pipefail
    IFS='.' read -r major minor patch <<< "$(just _version | cut -d- -f1)"
    case "{{ kind }}" in
      major) echo "$((major + 1)).0.0" ;;
      minor) echo "$major.$((minor + 1)).0" ;;
      patch) echo "$major.$minor.$((patch + 1))" ;;
      *) echo "error: bump kind must be major, minor or patch, not '{{ kind }}'" >&2; exit 1 ;;
    esac

# --- Release ---
#
# Pushing a v* tag runs .github/workflows/release.yml: the gate on the tagged commit, the
# distributions, the GitHub release with its notes from .github/release-notes/<tag>.md, and
# the npm (and, once set up, PyPI) publish. So the notes are committed before the tag:
#   1. write .github/release-notes/vX.Y.Z.md (`just changes` lists the commits) and commit it
#   2. just release patch        (or just release-version X.Y.Z)
#   3. just watch-release

# Bump (major | minor | patch), check, commit, tag and push; release.yml does the rest
release kind="patch":
    #!/usr/bin/env bash
    set -euo pipefail
    just _clean-tree
    just _release "$(just _bumped {{ kind }})"

# Release an exact version (same steps as `release`)
release-version version:
    #!/usr/bin/env bash
    set -euo pipefail
    just _clean-tree
    just _release "$(just _normalize-version {{ version }})"

# Internal: sync, check, commit, tag and push. On a failed check the bump stays in
# place: fix it and re-run `just _release X.Y.Z`, or `git checkout -- .` to drop it.
_release version:
    #!/usr/bin/env bash
    set -euo pipefail
    version="{{ version }}"
    just _notes-ready "$version"
    just _sync-versions "$version"
    just check
    # _clean-tree ran first, so the version sync is the only tracked change.
    git add -u
    git commit -m "chore(release): $version"
    git tag -a "v$version" -m "v$version"
    # One push for both, so the pre-push gate runs once.
    git push origin HEAD "v$version"
    echo "Tagged and pushed v$version. Next: just watch-release"

# Internal: refuse a release whose notes file is missing or not committed
_notes-ready version:
    #!/usr/bin/env bash
    set -euo pipefail
    notes=".github/release-notes/v{{ version }}.md"
    if ! git ls-files --error-unmatch "$notes" >/dev/null 2>&1; then
      echo "error: write and commit $notes first (just changes lists the commits)" >&2
      exit 1
    fi

# Internal: refuse to release from a tree with uncommitted changes
_clean-tree:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
      echo "error: commit or stash your changes first; a release commit holds only the version." >&2
      exit 1
    fi

# Watch a release go out: release.yml for the tag, then npm serving it
watch-release tag="":
    #!/usr/bin/env bash
    set -euo pipefail
    tag="{{ tag }}"
    tag="${tag:-v$(just _version)}"
    version="${tag#v}"
    # The run is found by the tag and its commit, never as "the latest run": a re-pointed
    # tag keeps its older runs in the list.
    sha="$(git rev-parse "$tag^{commit}")"
    run=""
    for _ in $(seq 1 30); do
      run=$(gh run list -R {{ repo }} --workflow release.yml --branch "$tag" --json databaseId,headSha \
        --jq "[.[] | select(.headSha == \"$sha\")][0].databaseId // empty")
      [ -n "$run" ] && break
      sleep 10
    done
    if [ -z "$run" ]; then echo "error: no release.yml run for $tag at $sha after 5 minutes" >&2; exit 1; fi
    gh run watch "$run" -R {{ repo }} --exit-status --interval 30
    # npm can take a while to serve a fresh version; this waits up to 30 minutes.
    for _ in $(seq 1 60); do
      if [ "$(npm view "catsearch@$version" version 2>/dev/null)" = "$version" ]; then
        echo "npm serves catsearch@$version"
        exit 0
      fi
      sleep 30
    done
    echo "error: release.yml passed but npm does not serve catsearch@$version after 30 minutes" >&2
    exit 1

# Move an existing release's tag to HEAD and force-push it, which reruns release.yml
retag version:
    #!/usr/bin/env bash
    set -euo pipefail
    version=$(just _normalize-version "{{ version }}")
    just _clean-tree
    just _notes-ready "$version"
    just version-check | grep -qx "$version" || { echo "error: HEAD is not at version $version" >&2; exit 1; }
    git push origin HEAD
    git tag -f -a "v$version" -m "v$version"
    git push -f origin "v$version"
    echo "Moved v$version to $(git rev-parse --short HEAD). Next: just watch-release v$version"

# --- Publishing ---

# Build the wheel, sdist and npm tarball into dist/ as release.yml does, uploading nothing
dist:
    rm -rf dist
    poetry build
    pnpm -C js build
    cp LICENSE js/LICENSE
    pnpm -C js pack --pack-destination "$PWD/dist"
    rm js/LICENSE
    ls dist

# Show what the npm tarball would contain, writing nothing
publish-dry:
    pnpm -C js build
    pnpm -C js pack --dry-run

# Publish this commit to npm as <version>-ci.<run>.<attempt> under the ci dist-tag
publish-prerelease:
    gh workflow run release.yml -R {{ repo }} --ref master -f npm_prerelease=true
    @echo "Started release.yml with npm_prerelease: gh run list -R {{ repo }} --workflow release.yml"
