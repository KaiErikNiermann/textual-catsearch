"""Sphinx configuration for the textual-catsearch documentation.

Furo with the same chrome as the LangCheck docs: a split sidebar brand, a Ctrl+K command palette
(``_ext/command_palette.py`` writes its index) and a small layer of token-driven CSS. The web
example is built by Vite into ``_build/html/search-bar/`` after Sphinx runs (``make html``, and the
Pages workflow); the demo page embeds it from there.
"""

import sys
import tomllib
from pathlib import Path

DOCS = Path(__file__).parent
ROOT = DOCS.parent

# The command palette extension, and the package itself for autodoc.
sys.path[:0] = [str(DOCS / "_ext"), str(ROOT / "src")]

with (ROOT / "pyproject.toml").open("rb") as pyproject:
    _project = tomllib.load(pyproject)["project"]

project = "textual-catsearch"
author = "Kai Niermann"
copyright = f"2026, {author}"
release = _project["version"]

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx_copybutton",
    "sphinx_design",
    "command_palette",
]

myst_enable_extensions = ["colon_fence", "deflist", "fieldlist"]
# Anchors for h1-h3, so in-page `](#section)` links resolve.
myst_heading_anchors = 3

autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_typehints_format = "short"
autodoc_default_options = {"members": True}
# Short names in signatures: everything is importable from the package root.
add_module_names = False
# The widgets subclass Textual's; their inherited API is Textual's to document.
autodoc_inherit_docstrings = False
napoleon_google_docstring = True
napoleon_numpy_docstring = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "textual": ("https://textual.textualize.io/", None),
}
# Textual's site publishes no objects.inv; a miss is a plain name, not a build failure.
intersphinx_disabled_reftypes = ["*"]
nitpicky = False

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
source_suffix = {".md": "markdown", ".rst": "restructuredtext"}

html_theme = "furo"
html_title = project
html_static_path = ["_static"]
# Order is cascade order: tokens first, then Furo's own elements, then this site's components.
html_css_files = ["css/tokens.css", "css/furo.css", "css/components.css"]
# The palette is an ES module: it imports the vendored ninja-keys bundle and reads the index the
# command_palette extension writes. The demo script sizes and themes the embedded example.
html_js_files = [
    ("command-palette.js", {"type": "module"}),
    ("demo-embed.js", {"type": "module"}),
]

_fonts = '"IBM Plex Sans", "Inter", system-ui, -apple-system, "Segoe UI", sans-serif'
_mono = '"JetBrains Mono", "IBM Plex Mono", ui-monospace, monospace'
_shared = {"font-stack": _fonts, "font-stack--headings": _fonts, "font-stack--monospace": _mono}
# Furo's own tokens: set here, Furo writes them into its theme blocks, so they follow its toggle.
html_theme_options = {
    "navigation_with_keys": True,
    "source_repository": "https://github.com/KaiErikNiermann/textual-catsearch/",
    "source_branch": "master",
    "source_directory": "docs/",
    "light_css_variables": {
        **_shared,
        "color-brand-primary": "#4752c4",
        "color-brand-content": "#4752c4",
    },
    "dark_css_variables": {
        **_shared,
        "color-brand-primary": "#8b93f8",
        "color-brand-content": "#8b93f8",
    },
}

html_sidebars = {
    "**": [
        "sidebar/brand.html",
        "sidebar/search.html",
        "sidebar/scroll-start.html",
        "sidebar/navigation.html",
        "sidebar/scroll-end.html",
        "sidebar/variant-selector.html",
    ],
}

repo_url = "https://github.com/KaiErikNiermann/textual-catsearch"

# Project links for the sidebar brand row (_templates/sidebar/brand.html) and the palette.
html_context = {
    "repo_url": repo_url,
    "release_url": f"{repo_url}/releases",
    "issues_url": f"{repo_url}/issues",
}
