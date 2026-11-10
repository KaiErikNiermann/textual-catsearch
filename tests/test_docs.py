"""The API reference pages list every public name, in both languages.

The Python page is autodoc directives and the TypeScript page a hand-written table, so neither
notices a name added to the package; these tests do.
"""

import re
from pathlib import Path

import textual_catsearch

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# `.. autofunction:: parse`, `.. autoclass:: Query`, `.. autodata:: NOTHING`.
_AUTODOC = re.compile(r"^\.\. auto(?:function|class|data):: (\w+)", re.MULTILINE)
# `export { a, b } from`, `export type { C } from`, across lines.
_EXPORTS = re.compile(r"export\s+(?:type\s+)?\{([^}]*)\}", re.DOTALL)


def documented_python() -> set[str]:
    return set(_AUTODOC.findall((DOCS / "reference" / "python.md").read_text(encoding="utf-8")))


def exported_typescript() -> set[str]:
    source = (ROOT / "js" / "src" / "index.ts").read_text(encoding="utf-8")
    return {
        name.strip()
        for group in _EXPORTS.findall(source)
        for name in group.split(",")
        if name.strip()
    }


def test_every_python_name_has_an_entry() -> None:
    missing = set(textual_catsearch.__all__) - documented_python()
    assert missing == set(), f"add to docs/reference/python.md: {sorted(missing)}"


def test_python_page_names_only_public_names() -> None:
    stale = documented_python() - set(textual_catsearch.__all__)
    assert stale == set(), f"not in __all__ any more: {sorted(stale)}"


def test_every_typescript_export_has_an_entry() -> None:
    page = (DOCS / "reference" / "typescript.md").read_text(encoding="utf-8")
    exports = exported_typescript()
    assert len(exports) > 50, "the export pattern no longer matches js/src/index.ts"
    missing = {name for name in exports if f"`{name}`" not in page}
    assert missing == set(), f"add to docs/reference/typescript.md: {sorted(missing)}"
