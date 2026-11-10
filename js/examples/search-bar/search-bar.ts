/**
 * A Discord-style search bar over `catsearch`: field keys drawn as code chips while you type, a
 * key and its value drawn as one chip once the value is complete (`kind:movie`), a dropdown of completions that narrows as you type, and the result count and parser notices
 * under it.
 *
 * One dropdown serves both kinds of input. With a keyboard, Tab takes the highlighted
 * completion and Tab again walks to the next one in place (Shift+Tab walks back), as the
 * Textual widget does; arrows move the highlight, Enter takes it, Escape closes. With a finger,
 * tapping an option takes it. Either way the caret lands after what was filled in.
 */

import { apply, lex, parse, suggest } from "../../src/index.ts";
import type { Query, Schema, Suggestion, Vocabulary } from "../../src/index.ts";

export interface SearchBarOptions<Row> {
  readonly editor: HTMLElement;
  readonly listbox: HTMLElement;
  readonly schema: Schema<Row>;
  readonly vocabulary: Vocabulary;
  /** Called with the parsed query after every edit. */
  readonly onQuery: (query: Query<Row>) => void;
  readonly limit?: number;
}

/** A run of Tab presses: the text before the first one, its completions, and which is taken. */
interface Walk {
  readonly base: string;
  readonly options: readonly Suggestion[];
  index: number;
}

/** Where a key ends in a token's text: after the first unquoted `:`, or -1 for a bare word. */
function keyEnd(text: string): number {
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text.charAt(i);
    if (ch === '"') quoted = !quoted;
    else if (ch === ":" && !quoted) return i + 1;
  }
  return -1;
}

/** How many grouping and negation characters lead a token: `(`, `-(`, `-`, `!`. */
function leading(text: string): number {
  let i = 0;
  while (i < text.length && "(-!".includes(text.charAt(i))) i++;
  return i;
}

/**
 * One run of the text to draw. A `term` is a key with a value attached (`kind:movie`), drawn as one
 * chip as Discord draws `from: user`; `key` is the length of its key part (`kind:`).
 */
type Piece =
  | { readonly text: string; readonly kind: "plain" | "key" | "operator" }
  | { readonly text: string; readonly kind: "term"; readonly key: number };

/** Trailing `)`s that close groups: the lexer keeps them on the token, but they are not value. */
function closers(value: string): number {
  let n = 0;
  while (n < value.length && value.charAt(value.length - 1 - n) === ")") n++;
  return n;
}

/**
 * The text cut into pieces to draw. A recognised `field:` (or `relation.field:`) key is a `key`,
 * `OR` is an `operator`, everything else is plain. A key the schema does not know is left plain,
 * which is how the parser reads it too: as text.
 *
 * A key whose value is attached becomes a `term`: the value is not empty, the parser found
 * nothing wrong with the clause, and the clause is not being typed. `editing` is the caret while
 * the person types (a clause the caret is in or at the end of is still open), or `null` when no
 * clause is open: after a completion is taken, or once the bar loses focus.
 */
export function pieces<Row>(text: string, schema: Schema<Row>, editing: number | null = null): Piece[] {
  const faults = parse(text, schema).diagnostics;
  const out: Piece[] = [];
  let at = 0;
  const plain = (to: number): void => {
    if (to > at) out.push({ text: text.slice(at, to), kind: "plain" });
    at = to;
  };
  for (const token of lex(text)) {
    const raw = text.slice(token.start, token.end);
    plain(token.start);
    if (raw === "OR" || raw === "|") {
      out.push({ text: raw, kind: "operator" });
      at = token.end;
      continue;
    }
    const lead = leading(raw);
    const end = keyEnd(raw);
    if (end <= lead || !isKey(raw.slice(lead, end), schema)) continue;
    plain(token.start + lead);
    const valueEnd = token.end - closers(raw.slice(end));
    const open = editing !== null && token.start <= editing && editing <= token.end;
    const faulty = faults.some((d) => d.start < token.end && token.start < d.end);
    const key = end - lead;
    if (!(open || faulty) && valueEnd > token.start + end) {
      out.push({ text: text.slice(at, valueEnd), kind: "term", key });
      at = valueEnd;
    } else {
      out.push({ text: text.slice(at, at + key), kind: "key" });
      at += key;
    }
  }
  plain(text.length);
  return out;
}

/** Does the schema read `key` (`kind:`, `sequel-of.year:`) as a field, not as text? */
function isKey<Row>(key: string, schema: Schema<Row>): boolean {
  const [term] = parse(`${key}x`, schema).terms;
  return term !== undefined && (term.field !== schema.bare || term.via.length > 0);
}

export class SearchBar<Row> {
  readonly #editor: HTMLElement;
  readonly #listbox: HTMLElement;
  readonly #schema: Schema<Row>;
  readonly #vocabulary: Vocabulary;
  readonly #onQuery: (query: Query<Row>) => void;
  readonly #limit: number;
  #options: readonly Suggestion[] = [];
  #active = 0;
  #walk: Walk | null = null;
  #composing = false;
  /** The text and caret the open suggestions were made for. */
  #suggestedFor = "";

  constructor(options: SearchBarOptions<Row>) {
    this.#editor = options.editor;
    this.#listbox = options.listbox;
    this.#schema = options.schema;
    this.#vocabulary = options.vocabulary;
    this.#onQuery = options.onQuery;
    this.#limit = options.limit ?? 8;
    this.#plainTextOnly();
    this.#editor.addEventListener("input", () => {
      this.#walk = null;
      this.#refresh(!this.#composing);
    });
    // A phone keyboard composes whole words; redrawing mid-word would break the composition.
    this.#editor.addEventListener("compositionstart", () => (this.#composing = true));
    this.#editor.addEventListener("compositionend", () => {
      this.#composing = false;
      this.#refresh(true);
    });
    this.#editor.addEventListener("keydown", (event) => {
      this.#key(event);
    });
    this.#editor.addEventListener("focus", () => {
      this.#refresh(false);
    });
    // Leaving the bar accepts what is shown: the clause last typed attaches too.
    this.#editor.addEventListener("blur", () => {
      this.#close();
      if (!this.#composing) this.#draw(this.text, this.text.length);
    });
    // Mouse and touch alike: `pointerdown` with the default prevented keeps focus (and the
    // phone keyboard) in the editor, where `click` would blur it first.
    this.#listbox.addEventListener("pointerdown", (event) => {
      event.preventDefault();
    });
    this.#listbox.addEventListener("click", (event) => {
      const option = (event.target as Element).closest<HTMLElement>("[role=option]");
      const index = Number(option?.dataset["index"] ?? NaN);
      const picked = this.#options.at(index);
      if (picked !== undefined) this.#take(picked);
    });
    // The caret moved without an edit (a click, an arrow, Home): suggest for where it is now.
    // Only if it moved: our own redraws put the caret back and fire this too, late, and
    // answering those would reset a highlight the arrows have just moved.
    document.addEventListener("selectionchange", () => {
      if (document.activeElement !== this.#editor || this.#composing || this.#walk !== null) return;
      if (this.#where() !== this.#suggestedFor) this.#suggest();
    });
    this.#refresh(true);
  }

  #plainTextOnly(): void {
    this.#editor.contentEditable = "plaintext-only";
    // Engines before plaintext-only (Firefox before 136) get rich editing; pastes are taken
    // by hand in both, as plain text on one line, since a pasted newline would break the bar.
    if (this.#editor.contentEditable !== "plaintext-only") this.#editor.contentEditable = "true";
    this.#editor.addEventListener("paste", (event) => {
      event.preventDefault();
      this.#insert(event.clipboardData?.getData("text/plain") ?? "");
    });
    // One line: the query has no newlines, and Enter means "take this completion".
    this.#editor.addEventListener("beforeinput", (event) => {
      if (event.inputType === "insertParagraph" || event.inputType === "insertLineBreak") event.preventDefault();
    });
  }

  /** Plain text in at the caret, on one line, then handled as any edit. */
  #insert(pasted: string): void {
    const selection = document.getSelection();
    if (selection === null || selection.rangeCount === 0) return;
    const range = selection.getRangeAt(0);
    range.deleteContents();
    const node = document.createTextNode(pasted.replaceAll(/\s+/gu, " "));
    range.insertNode(node);
    selection.setBaseAndExtent(node, node.length, node, node.length);
    this.#editor.dispatchEvent(new Event("input", { bubbles: true }));
  }

  #key(event: KeyboardEvent): void {
    if (this.#walk !== null && this.#walking(event)) return;
    // Closed, every key keeps its default: Tab moves focus, Enter is refused by `beforeinput`.
    if (this.#options.length === 0) return;
    switch (event.key) {
      case "Tab": {
        event.preventDefault();
        this.#step(event.shiftKey ? -1 : 1);
        break;
      }
      case "ArrowDown":
      case "ArrowUp": {
        event.preventDefault();
        this.#highlight(this.#active + (event.key === "ArrowDown" ? 1 : -1));
        break;
      }
      case "Enter": {
        event.preventDefault();
        const picked = this.#options.at(this.#active);
        if (picked !== undefined) this.#take(picked);
        break;
      }
      case "Escape": {
        this.#close();
        break;
      }
      default: {
        break;
      }
    }
  }

  /** A key during a Tab walk: Tab and the arrows step, Enter keeps what is filled in, Escape
   * closes, and anything else ends the walk before it acts. True when the key was used. */
  #walking(event: KeyboardEvent): boolean {
    switch (event.key) {
      case "Tab":
      case "ArrowDown":
      case "ArrowUp": {
        event.preventDefault();
        this.#step(event.key === "ArrowUp" || (event.key === "Tab" && event.shiftKey) ? -1 : 1);
        return true;
      }
      case "Enter":
      case "Escape": {
        event.preventDefault();
        this.#walk = null;
        if (event.key === "Enter") this.#suggest();
        else this.#close();
        return true;
      }
      case "Shift": {
        return true;
      }
      default: {
        this.#walk = null;
        return false;
      }
    }
  }

  /** Tab: take the highlighted completion, then walk the same list in place. */
  #step(direction: 1 | -1): void {
    if (this.#walk === null) {
      if (this.#options.length === 0) return;
      // The first Tab takes the highlighted option, the first Shift+Tab the one before it.
      this.#walk = { base: this.text, options: this.#options, index: this.#active - (direction === 1 ? 1 : 0) };
    }
    const walk = this.#walk;
    const n = walk.options.length;
    walk.index = (((walk.index + direction) % n) + n) % n;
    const picked = walk.options[walk.index];
    if (picked === undefined) return;
    const text = apply(walk.base, picked);
    this.#draw(text, picked.start + picked.insert.length);
    this.#announce();
    // The list stays the walk's own, highlighted where it stands, so the next Tab steps on.
    this.#render(walk.options, walk.index);
    if (n === 1) this.#walk = null;
  }

  /** Fill `picked` in. Mid-walk, the walk's options are offsets into the text before it. */
  #take(picked: Suggestion): void {
    const base = this.#walk?.base ?? this.text;
    this.#walk = null;
    this.#draw(apply(base, picked), picked.start + picked.insert.length);
    this.#announce();
    this.#suggest();
  }

  #refresh(redraw: boolean): void {
    if (redraw) this.#draw(this.text, this.#caret(), true);
    this.#announce();
    this.#suggest();
  }

  #announce(): void {
    this.#onQuery(parse(this.text, this.#schema));
  }

  /** The text and caret, as one comparable key. */
  #where(): string {
    return `${this.#caret()}:${this.text}`;
  }

  #suggest(): void {
    this.#suggestedFor = this.#where();
    const focused = document.activeElement === this.#editor;
    this.#render(focused ? suggest(this.text, this.#caret(), this.#schema, this.#vocabulary, { limit: this.#limit }) : [], 0);
  }

  #close(): void {
    this.#render([], 0);
  }

  #highlight(index: number): void {
    const n = this.#options.length;
    if (n === 0) return;
    this.#render(this.#options, ((index % n) + n) % n);
  }

  #render(options: readonly Suggestion[], active: number): void {
    this.#options = options;
    this.#active = active;
    const items = options.map((option, i) => {
      const item = document.createElement("li");
      item.id = `${this.#listbox.id}-${i}`;
      item.role = "option";
      item.dataset["index"] = String(i);
      item.dataset["kind"] = option.kind;
      item.ariaSelected = String(i === active);
      const label = document.createElement("span");
      label.className = "option-label";
      label.textContent = option.label;
      const detail = document.createElement("span");
      detail.className = "option-detail";
      detail.textContent = option.detail;
      item.append(label, detail);
      return item;
    });
    this.#listbox.replaceChildren(...items);
    this.#listbox.hidden = items.length === 0;
    this.#editor.ariaExpanded = String(items.length > 0);
    // The attribute carries a value, which toggleAttribute cannot set.
    // eslint-disable-next-line unicorn/prefer-toggle-attribute
    if (items.length > 0) this.#editor.setAttribute("aria-activedescendant", `${this.#listbox.id}-${active}`);
    else this.#editor.removeAttribute("aria-activedescendant");
  }

  /**
   * Redraw the text as pieces (keys and attached terms as chips) and put the caret back at
   * `caret`. `typing` says the caret is where someone is typing, so the clause there stays open.
   */
  #draw(text: string, caret: number, typing = false): void {
    const nodes = pieces(text, this.#schema, typing ? caret : null).map((piece) => {
      if (piece.kind === "plain") return document.createTextNode(piece.text);
      const span = document.createElement("span");
      if (piece.kind === "term") {
        const key = document.createElement("span");
        key.className = "token-key";
        key.textContent = piece.text.slice(0, piece.key);
        span.className = "token-term";
        span.append(key, piece.text.slice(piece.key));
        return span;
      }
      span.className = piece.kind === "key" ? "token-key" : "token-operator";
      span.textContent = piece.text;
      return span;
    });
    this.#editor.replaceChildren(...nodes);
    if (document.activeElement === this.#editor) this.#place(caret);
  }

  /** The caret as a UTF-16 offset into the text, the unit the library's offsets are in. */
  #caret(): number {
    const selection = document.getSelection();
    if (selection === null || selection.rangeCount === 0) return this.text.length;
    const range = selection.getRangeAt(0);
    if (!this.#editor.contains(range.endContainer)) return this.text.length;
    const before = document.createRange();
    before.selectNodeContents(this.#editor);
    before.setEnd(range.endContainer, range.endOffset);
    return before.toString().length;
  }

  #place(caret: number): void {
    const selection = document.getSelection();
    if (selection === null) return;
    const walker = document.createTreeWalker(this.#editor, NodeFilter.SHOW_TEXT);
    let left = caret;
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
      const length = node.textContent?.length ?? 0;
      if (left <= length) {
        selection.setBaseAndExtent(node, left, node, left);
        return;
      }
      left -= length;
    }
    selection.selectAllChildren(this.#editor);
    selection.collapseToEnd();
  }

  get text(): string {
    return this.#editor.textContent;
  }

  /** Replace the whole text, as a tab or a link would, and put the caret at `caret`. */
  set(text: string, caret = text.length): void {
    this.#draw(text, caret);
    this.#announce();
    this.#suggest();
  }
}
