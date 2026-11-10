# Demo

A search bar over a small media catalogue, built on the TypeScript package. Type words to search titles, or a field and a value: `kind:`, `year:`, `genre:`, `cast:`, `is:`. Known field keys turn into code chips as you type.

- On a keyboard, Tab takes the highlighted completion and Tab again walks to the next (Shift+Tab back); arrows and Enter pick; Escape closes the list.
- On a phone, tap a completion.
- Try a range (`year:2015..2020`), a negation (`-is:watched`), alternatives (`genre:drama,comedy`) or a group (`(kind:tv OR kind:game) is:favourite`).

```{raw} html
<iframe class="cs-demo" src="search-bar/index.html" title="catsearch search bar demo"></iframe>
<p class="cs-demo-fallback">Open the demo <a href="search-bar/index.html">on its own page</a>.</p>
```

The source is [`js/examples/search-bar`](https://github.com/KaiErikNiermann/textual-catsearch/tree/master/js/examples/search-bar): `search-bar.ts` is the bar (a `contenteditable` that draws chips, and the completion list), `main.ts` the catalogue and its schema. It follows the docs' light or dark theme here; on its own page it has a toggle of its own.

To run it locally:

```sh
pnpm -C js install
pnpm -C js example        # dev server on http://localhost:5173
```
