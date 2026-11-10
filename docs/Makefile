# The docs: Sphinx (warnings are errors), then the web demo built into the site at search-bar/,
# where docs/demo.md embeds it from the same origin.

SPHINXBUILD ?= poetry run sphinx-build
BUILDDIR    ?= _build
HTML        := $(BUILDDIR)/html
DEMO        := $(abspath $(HTML))/search-bar

.PHONY: html sphinx demo serve clean

html: sphinx demo

sphinx:
	$(SPHINXBUILD) -W --keep-going -b html . "$(HTML)"

# Relative asset paths (--base ./), so the demo works under the Pages project path.
demo:
	pnpm -C ../js exec vite build examples/search-bar --base ./ --outDir "$(DEMO)" --emptyOutDir

serve: html
	python3 -m http.server --directory "$(HTML)" 8000

clean:
	rm -rf "$(BUILDDIR)"
