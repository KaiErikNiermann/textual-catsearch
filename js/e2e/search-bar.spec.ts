/**
 * The example search bar does what its page says: field keys drawn as code chips, a key and its
 * completed value drawn as one chip, a dropdown that narrows as you type, Tab to take and walk on
 * a keyboard, a tap to take on a phone, and results that follow the query. Every assertion is
 * web-first (it retries), so nothing waits on a timer.
 */

import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";

const TOTAL = 22;

function bar(page: Page): Locator {
  return page.getByRole("combobox", { name: "Search" });
}

function options(page: Page): Locator {
  return page.getByRole("listbox", { name: "Completions" }).getByRole("option");
}

/** The labels on offer, in order: each option's first span. */
function labels(page: Page): Locator {
  return options(page).locator(".option-label");
}

function toggle(page: Page): Locator {
  return page.getByRole("button", { name: /Switch to (light|dark) theme/u });
}

async function background(page: Page): Promise<string> {
  return page.locator("body").evaluate((el) => getComputedStyle(el).backgroundColor);
}

async function typeQuery(page: Page, text: string): Promise<void> {
  await bar(page).click();
  await page.keyboard.type(text);
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("#count")).toHaveText(`${TOTAL} of ${TOTAL}`);
});

test.describe("everywhere", () => {
  test("draws a known field key as a monospace code chip and leaves the rest as text", async ({ page }) => {
    await typeQuery(page, "kind:movie nope:x dune");
    await expect(bar(page)).toHaveText("kind:movie nope:x dune");
    const chips = bar(page).locator(".token-key");
    await expect(chips).toHaveText(["kind:"]);
    await expect(chips.first()).toHaveCSS("font-family", /mono/iu);
    // The key's value is complete, so key and value share one chip with its own background.
    const terms = bar(page).locator(".token-term");
    await expect(terms).toHaveText(["kind:movie"]);
    const chipBackground = await terms.first().evaluate((el) => getComputedStyle(el).backgroundColor);
    const barBackground = await bar(page).evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(chipBackground).not.toBe(barBackground);
    await expect(page.locator("#notice")).toHaveText("nope: not a field — searched as text");
  });

  test("draws keys reached through a path, negated keys and the OR operator", async ({ page }) => {
    await typeQuery(page, "(kind:tv OR -genre:drama)");
    await expect(bar(page).locator(".token-key")).toHaveText(["kind:", "genre:"]);
    await expect(bar(page).locator(".token-operator")).toHaveText(["OR"]);
  });

  test("attaches a value to its key once the clause is done, as one chip", async ({ page }) => {
    await typeQuery(page, "kind:mov");
    // Still being typed: the key is a chip, the value plain text after it.
    await expect(bar(page).locator(".token-key")).toHaveText(["kind:"]);
    await expect(bar(page).locator(".token-term")).toHaveCount(0);
    await page.keyboard.type("ie ");
    await expect(bar(page).locator(".token-term")).toHaveText(["kind:movie"]);
    await expect(bar(page).locator(".token-term .token-key")).toHaveText(["kind:"]);
    // The caret stays after the space, so typing goes on outside the chip.
    await page.keyboard.type("dune");
    await expect(bar(page)).toHaveText("kind:movie dune");
    await expect(bar(page).locator(".token-term")).toHaveText(["kind:movie"]);
  });

  test("keeps a value the parser rejects apart from its key", async ({ page }) => {
    await typeQuery(page, "year:abc ");
    await expect(bar(page).locator(".token-key")).toHaveText(["year:"]);
    await expect(bar(page).locator(".token-term")).toHaveCount(0);
  });

  test("attaches values inside groups, leaving the brackets and OR outside", async ({ page }) => {
    await typeQuery(page, "(kind:tv OR kind:game) ");
    await expect(bar(page).locator(".token-term")).toHaveText(["kind:tv", "kind:game"]);
    await expect(bar(page).locator(".token-operator")).toHaveText(["OR"]);
    await expect(bar(page)).toHaveText("(kind:tv OR kind:game) ");
  });

  test("leaving the bar attaches the clause last typed", async ({ page }) => {
    await typeQuery(page, "genre:drama");
    await expect(bar(page).locator(".token-term")).toHaveCount(0);
    await page.locator(".title").click();
    await expect(bar(page).locator(".token-term")).toHaveText(["genre:drama"]);
  });

  test("narrows the dropdown as you type", async ({ page }) => {
    await typeQuery(page, "k");
    await expect(labels(page)).toHaveText(["kind:"]);
    await page.keyboard.type("ind:");
    // Most used first: 10 movies, 7 shows, 5 games.
    await expect(labels(page)).toHaveText(["movie", "tv", "game"]);
    await page.keyboard.type("g");
    await expect(labels(page)).toHaveText(["game"]);
    await page.keyboard.type("zz");
    await expect(options(page)).toHaveCount(0);
    await expect(page.getByRole("listbox", { name: "Completions" })).toBeHidden();
  });

  test("filters the results as you type", async ({ page }) => {
    await typeQuery(page, "kind:game");
    await expect(page.locator("#count")).toHaveText(`5 of ${TOTAL}`);
    await expect(page.locator(".result")).toHaveCount(5);
    await page.keyboard.type(" year:>2019");
    await expect(page.locator(".result-name")).toHaveText(["Hades", "Elden Ring"]);
  });

  test("an example query fills the bar and runs", async ({ page }) => {
    await page.getByRole("button", { name: "genre:sci-fi -is:watched" }).click();
    await expect(bar(page)).toHaveText("genre:sci-fi -is:watched");
    await expect(page.locator(".result-name")).toHaveText(["Dune: Part Two", "Everything Everywhere All at Once", "Dark", "Outer Wilds"]);
  });

  test("a pasted line break becomes a space", async ({ page }) => {
    await bar(page).click();
    // Firefox empties a script-built DataTransfer, so the event carries its data directly:
    // what is under test is the bar's handling of a paste, not the engine's clipboard.
    await bar(page).evaluate((el) => {
      const event = new ClipboardEvent("paste", { bubbles: true, cancelable: true });
      Object.defineProperty(event, "clipboardData", { value: { getData: () => "kind:tv\ndark" } });
      el.dispatchEvent(event);
    });
    await expect(bar(page)).toHaveText("kind:tv dark");
    await expect(page.locator(".result-name")).toHaveText(["Dark"]);
  });

  test("the page never scrolls sideways, and the dropdown stays on screen", async ({ page }) => {
    await typeQuery(page, "cast:");
    await expect(options(page).first()).toBeVisible();
    const width = page.viewportSize()?.width ?? 0;
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    const box = await page.getByRole("listbox", { name: "Completions" }).boundingBox();
    expect(box).not.toBeNull();
    expect((box?.x ?? -1) >= 0 && (box?.x ?? 0) + (box?.width ?? 0) <= width).toBe(true);
  });
});

test.describe("the theme toggle", () => {
  test("follows the system until a theme is picked", async ({ page }) => {
    await expect(page.locator("html")).not.toHaveAttribute("data-theme");
    await expect(toggle(page)).toHaveAccessibleName("Switch to dark theme");
    const light = await background(page);
    await page.emulateMedia({ colorScheme: "dark" });
    await expect(toggle(page)).toHaveAccessibleName("Switch to light theme");
    await expect.poll(() => background(page)).not.toBe(light);
  });

  test("switches, flips its own glyph and name, and is remembered", async ({ page }) => {
    const light = await background(page);
    await toggle(page).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await expect(toggle(page)).toHaveAccessibleName("Switch to light theme");
    await expect(toggle(page)).toHaveAttribute("title", "Switch to light theme");
    await expect.poll(() => background(page)).not.toBe(light);
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await toggle(page).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect.poll(() => background(page)).toBe(light);
  });

  test("a pick outranks the system", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await toggle(page).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.reload();
    await expect(toggle(page)).toHaveAccessibleName("Switch to dark theme");
  });

  test("a remembered theme applies before the page's scripts load, so nothing flashes", async ({ page }) => {
    await toggle(page).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    // With the module blocked, only the inline script in <head> can have set it.
    await page.route("**/assets/*.js", (route) => route.abort());
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  });

  test("sits beside the title without touching it, at any width", async ({ page }) => {
    const title = await page.getByRole("heading", { name: "Search the catalogue" }).boundingBox();
    const button = await toggle(page).boundingBox();
    expect(title !== null && button !== null).toBe(true);
    if (title === null || button === null) return;
    expect(title.x + title.width).toBeLessThanOrEqual(button.x);
    expect(button.x + button.width).toBeLessThanOrEqual(page.viewportSize()?.width ?? 0);
  });
});

// Desktop projects only (see playwright.config.ts): phones have no Tab key.
test.describe("with a keyboard", { tag: "@keyboard" }, () => {
  test("Tab takes the highlighted completion, Tab again walks, Shift+Tab walks back", async ({ page }) => {
    await typeQuery(page, "kind:");
    await expect(labels(page)).toHaveText(["movie", "tv", "game"]);
    await page.keyboard.press("Tab");
    await expect(bar(page)).toHaveText("kind:movie");
    // A taken value is complete: it attaches at once, with no space typed.
    await expect(bar(page).locator(".token-term")).toHaveText(["kind:movie"]);
    await page.keyboard.press("Tab");
    await expect(bar(page)).toHaveText("kind:tv");
    await expect(options(page).nth(1)).toHaveAttribute("aria-selected", "true");
    await page.keyboard.press("Shift+Tab");
    await expect(bar(page)).toHaveText("kind:movie");
    // Typing ends the walk, with the caret after what was filled in.
    await page.keyboard.type(" dune");
    await expect(bar(page)).toHaveText("kind:movie dune");
    await expect(page.locator(".result-name")).toHaveText(["Dune", "Dune: Part Two"]);
  });

  test("the arrows move the highlight, Enter takes it, Escape closes", async ({ page }) => {
    await typeQuery(page, "kind:");
    await page.keyboard.press("ArrowDown");
    await expect(options(page).nth(1)).toHaveAttribute("aria-selected", "true");
    await expect(bar(page)).toHaveAttribute("aria-activedescendant", "suggestions-1");
    await page.keyboard.press("Enter");
    await expect(bar(page)).toHaveText("kind:tv");
    await page.keyboard.type(" ");
    await expect(options(page).first()).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("listbox", { name: "Completions" })).toBeHidden();
    await expect(bar(page)).toHaveAttribute("aria-expanded", "false");
  });

  test("keeps the caret in place when the bar redraws its chips", async ({ page }) => {
    await typeQuery(page, "dune");
    await page.keyboard.press("Home");
    await page.keyboard.type("kind:movie ");
    await expect(bar(page)).toHaveText("kind:movie dune");
    await expect(bar(page).locator(".token-key")).toHaveText(["kind:"]);
  });

  test("Enter with nothing on offer adds no line", async ({ page }) => {
    await typeQuery(page, "zzz");
    await expect(options(page)).toHaveCount(0);
    await page.keyboard.press("Enter");
    await expect(bar(page)).toHaveText("zzz");
    expect(await bar(page).evaluate((el) => el.querySelectorAll("br, div").length)).toBe(0);
  });
});

// Phone projects only: a tap is the phone's Tab.
test.describe("on a phone", { tag: "@touch" }, () => {
  test("tapping an option fills in the rest of the keyword, then its value", async ({ page }) => {
    await bar(page).tap();
    await page.keyboard.type("ge");
    await expect(labels(page)).toHaveText(["genre:"]);
    await options(page).first().tap();
    await expect(bar(page)).toHaveText("genre:");
    await expect(bar(page)).toBeFocused();
    await expect(labels(page).first()).toHaveText("drama");
    await options(page).filter({ hasText: "sci-fi" }).tap();
    await expect(bar(page)).toHaveText("genre:sci-fi");
    await expect(bar(page).locator(".token-term")).toHaveText(["genre:sci-fi"]);
    await expect(page.locator("#count")).toHaveText(`9 of ${TOTAL}`);
  });

  test("every option is a full-size touch target", async ({ page }) => {
    await bar(page).tap();
    await page.keyboard.type("is:");
    await expect(options(page)).toHaveCount(2);
    // The shortest option, measured in one read so a redraw cannot land between the two.
    const shortest = (): Promise<number> =>
      page
        .getByRole("listbox", { name: "Completions" })
        .evaluate((list) => Math.min(...[...list.querySelectorAll("[role=option]")].map((o) => o.getBoundingClientRect().height)));
    await expect.poll(shortest).toBeGreaterThanOrEqual(44);
  });

  test("the theme toggle is a full-size touch target", async ({ page }) => {
    const box = await page.getByRole("button", { name: /Switch to/u }).boundingBox();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(44);
  });

  test("the bar's text is large enough that focusing it does not zoom the page", async ({ page }) => {
    await expect(bar(page)).toHaveCSS("font-size", "16px");
  });
});
