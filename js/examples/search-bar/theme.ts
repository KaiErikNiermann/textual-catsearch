/**
 * The light/dark toggle: follows the system until the viewer picks, then remembers the pick.
 *
 * The theme is `data-theme` on the root, which the tokens read (`color-scheme`, so every
 * `light-dark()` colour follows). A stored pick is applied before first paint by the inline
 * script in index.html, which reads the same key; this module takes over once loaded.
 */

export type Theme = "light" | "dark";

/** Where a pick is remembered. index.html's inline script reads the same key. */
export const STORAGE_KEY = "catsearch-theme";

const DARK = globalThis.matchMedia("(prefers-color-scheme: dark)");

// Storage may be absent or throw (a private window, blocked site data): the toggle still works
// for the page's lifetime, it just is not remembered.
function stored(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

function remember(theme: Theme): void {
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Not remembered; see `stored`.
  }
}

/** The theme on screen: the viewer's pick, else the system's. */
export function current(): Theme {
  const picked = document.documentElement.dataset["theme"];
  if (picked === "light" || picked === "dark") return picked;
  return DARK.matches ? "dark" : "light";
}

const SVG = "http://www.w3.org/2000/svg";

/** Lucide's `sun` and `moon`, as path data: the page's only two icons. */
const ICONS: Readonly<Record<Theme, readonly string[]>> = {
  light: [
    "M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8Z",
    "M12 2v2",
    "M12 20v2",
    "m4.93 4.93 1.41 1.41",
    "m17.66 17.66 1.41 1.41",
    "M2 12h2",
    "M20 12h2",
    "m6.34 17.66-1.41 1.41",
    "m19.07 4.93-1.41 1.41",
  ],
  dark: ["M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"],
};

function icon(theme: Theme): SVGSVGElement {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("icon");
  const paths = theme === "dark" ? ICONS.dark : ICONS.light;
  for (const d of paths) {
    const path = document.createElementNS(SVG, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

/** Draw `button` as the switch to the theme not on screen: its glyph, name and tooltip. */
function label(button: HTMLButtonElement): void {
  const next: Theme = current() === "dark" ? "light" : "dark";
  const words = `Switch to ${next} theme`;
  button.setAttribute("aria-label", words);
  button.title = words;
  button.dataset["next"] = next;
  button.replaceChildren(icon(next));
}

/** Wire the toggle: apply any stored pick, follow the system until one is made. */
export function themeToggle(button: HTMLButtonElement): void {
  const picked = stored();
  if (picked !== null) document.documentElement.dataset["theme"] = picked;
  label(button);
  button.addEventListener("click", () => {
    const next: Theme = current() === "dark" ? "light" : "dark";
    document.documentElement.dataset["theme"] = next;
    remember(next);
    label(button);
  });
  // With no pick made, the page follows the system, and so must the button's glyph.
  DARK.addEventListener("change", () => {
    label(button);
  });
}
