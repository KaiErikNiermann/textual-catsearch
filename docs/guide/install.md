# Install

## Python

Neither package is on a registry yet; install from the repository.

```sh
poetry add git+https://github.com/KaiErikNiermann/textual-catsearch.git
# or
pip install "textual-catsearch @ git+https://github.com/KaiErikNiermann/textual-catsearch.git"
```

Requires Python 3.13 or newer. The one dependency is Textual 8, and only the widgets import it: a program that parses and evaluates queries without a terminal (a CLI, a web backend) never loads Textual.

## TypeScript

The TypeScript port lives in `js/` and has no runtime dependencies. Build it, then depend on it by path:

```sh
git clone https://github.com/KaiErikNiermann/textual-catsearch.git
pnpm -C textual-catsearch/js install
pnpm -C textual-catsearch/js build      # writes js/dist/

pnpm add ./textual-catsearch/js         # from your project
```

It is an ES module with type declarations and targets Node 22.18 or newer and current browsers (Chrome, Firefox, Safari).
