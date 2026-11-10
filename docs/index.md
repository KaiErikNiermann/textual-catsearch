# textual-catsearch

Discord-style category search. You declare the fields your rows have; you get a query language over them, filtering, rendering back to text, and completion of field names and values as you type.

```text
author:"le guin" year:1960..1980 -is:read
(format:ebook OR format:hardcover) genre:sci-fi
follows.title:dune series:none
```

It comes in two forms that answer every query the same way:

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} Python, for Textual apps
:link: guide/quickstart
:link-type: doc

`textual-catsearch`: the query language plus a `SearchBar` widget that previews the leading completion, takes it on Tab and walks the others on Tab again.
:::

:::{grid-item-card} TypeScript, for the web
:link: demo
:link-type: doc

`catsearch`: the same language as a dependency-free package of about 13 kB gzipped. The demo is a search bar built on it, for the keyboard and for touch.
:::

::::

The two are held to the same answers by a shared spec: golden fixtures generated from the Python package, and a differential test that asks both implementations every case Hypothesis generates (see the [developer guide](guide/development.md)).

- [Install](guide/install.md) either package, then follow the [quickstart](guide/quickstart.md).
- Try the language in the [demo](demo.md).
- Read the [usage guide](guide/usage.md) for the full syntax and the field kinds.
- Look names up in the [Python](reference/python.md) and [TypeScript](reference/typescript.md) API references.

```{toctree}
:hidden:
:maxdepth: 2
:caption: Getting started

guide/install
guide/quickstart
demo
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Guide

guide/usage
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Reference

reference/python
reference/typescript
```

```{toctree}
:hidden:
:maxdepth: 2
:caption: Development

guide/development
```
