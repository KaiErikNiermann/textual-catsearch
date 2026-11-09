/**
 * Lexing: a query string into tokens that remember which characters were quoted.
 *
 * Only `"` quotes: an apostrophe is always a literal (`Don't Look Up`). An unterminated quote
 * is the normal state while typing, not an error, and every token keeps its span so completion
 * can splice by offset.
 */

import { isSpace, lstrip, lstripChars, rstrip, rstripChars } from "./unicode.ts";

export const QUOTE = '"';

/** What an unquoted value may be spelled with; everything else belongs to the grammar. */
const WORD_CHARS = /^[A-Za-z0-9_-]$/u;

export function isWordChar(ch: string): boolean {
  return WORD_CHARS.test(ch);
}

/** One run of a token's text, and whether it was written inside quotes. */
export type Run = readonly [text: string, quoted: boolean];

/**
 * Text that remembers which of its characters were written inside quotes.
 *
 * Every place that looks for a separator looks only at the free runs, so a comma, colon or
 * bracket inside quotes is just a character.
 */
export class Guarded {
  static readonly EMPTY = new Guarded([]);

  readonly runs: readonly Run[];

  constructor(runs: readonly Run[]) {
    this.runs = runs;
  }

  get text(): string {
    return this.runs.map(([text]) => text).join("");
  }

  /** Is any text here at all (Python's `__bool__`)? */
  get nonEmpty(): boolean {
    return this.runs.some(([text]) => text.length > 0);
  }

  /** Was none of this written inside quotes? */
  get bare(): boolean {
    return this.runs.every(([, quoted]) => !quoted);
  }

  /** Is this exactly `word`, written without quotes? `"OR"` is a title, `OR` is not. */
  isFree(word: string): boolean {
    return this.bare && this.text === word;
  }

  /** Leading and trailing whitespace dropped: a value is never meant to be padded. */
  strip(): Guarded {
    const runs = [...this.runs];
    while (runs.length > 0) {
      const [text, quoted] = runs[0] ?? ["", false];
      const kept = lstrip(text);
      if (kept) {
        runs[0] = [kept, quoted];
        break;
      }
      runs.shift();
    }
    while (runs.length > 0) {
      const [text, quoted] = runs.at(-1) ?? ["", false];
      const kept = rstrip(text);
      if (kept) {
        runs[runs.length - 1] = [kept, quoted];
        break;
      }
      runs.pop();
    }
    return new Guarded(runs);
  }

  /** Unquoted `opening` off the front and `closing` off the back, with counts of each. */
  peel(opening: string, closing: string): readonly [lead: number, rest: Guarded, trail: number] {
    const runs = [...this.runs];
    let lead = 0;
    while (runs.length > 0 && runs[0]?.[1] === false) {
      const text = runs[0][0];
      const kept = lstripChars(text, opening);
      lead += text.length - kept.length;
      if (kept) {
        runs[0] = [kept, false];
        break;
      }
      runs.shift();
    }
    let trail = 0;
    while (runs.length > 0 && runs.at(-1)?.[1] === false) {
      const text = runs.at(-1)?.[0] ?? "";
      const kept = rstripChars(text, closing);
      trail += text.length - kept.length;
      if (kept) {
        runs[runs.length - 1] = [kept, false];
        break;
      }
      runs.pop();
    }
    return [lead, new Guarded(runs), trail];
  }

  /** Only the characters written outside quotes: what the value grammar governs. */
  freeText(): string {
    return this.runs
      .filter(([, quoted]) => !quoted)
      .map(([text]) => text)
      .join("");
  }

  /** An unquoted leading `-` or `!` taken off, if there is one and something follows. */
  sign(): readonly [negated: boolean, rest: Guarded] {
    const first = this.runs[0];
    if (first === undefined || first[1] || !(first[0].startsWith("-") || first[0].startsWith("!"))) {
      return [false, this];
    }
    const rest = new Guarded([[first[0].slice(1), false], ...this.runs.slice(1)]);
    return rest.text ? [true, rest] : [false, this];
  }

  /** This, with plain unquoted `text` appended: puts back what was over-peeled. (Python's
   * `then`; renamed, because a `then` method makes any object look like a promise to `await`.) */
  append(text: string): Guarded {
    return text ? new Guarded([...this.runs, [text, false]]) : this;
  }

  /** Split at the first unquoted `sep`. The head names a field, so it is plain text. */
  partition(sep: string): readonly [head: string, found: boolean, rest: Guarded] {
    let head = "";
    for (const [i, [text, quoted]] of this.runs.entries()) {
      const at = quoted ? -1 : text.indexOf(sep);
      if (at >= 0) {
        const rest = new Guarded([[text.slice(at + 1), false], ...this.runs.slice(i + 1)]);
        return [head + text.slice(0, at), true, rest];
      }
      head += text;
    }
    return [this.text, false, Guarded.EMPTY];
  }

  /** Split on every unquoted `sep`: the commas that mean "or", not those in a title. */
  split(sep: string): Guarded[] {
    const out: Run[][] = [[]];
    for (const [text, quoted] of this.runs) {
      if (quoted) {
        out.at(-1)?.push([text, true]);
        continue;
      }
      const [first = "", ...rest] = text.split(sep);
      out.at(-1)?.push([first, false]);
      for (const piece of rest) out.push([[piece, false]]);
    }
    return out.map((runs) => new Guarded(runs));
  }
}

/** One lexed token plus its source span `[start, end)`. */
export interface Token {
  readonly body: Guarded;
  readonly start: number;
  readonly end: number;
}

/** The token's text with its quote characters removed. */
export function tokenText(token: Token): string {
  return token.body.text;
}

/** Split a query into tokens. Never throws. */
export function lex(source: string): Token[] {
  const tokens: Token[] = [];
  const n = source.length;
  let i = 0;
  while (i < n) {
    while (i < n && isSpace(source.charAt(i))) i++;
    if (i >= n) break;
    const start = i;
    const [body, end] = scan(source, i);
    i = end;
    tokens.push({ body, start, end });
  }
  return tokens;
}

/** One token from `i`: its runs of quoted and unquoted text, and where it ended. */
function scan(source: string, from: number): readonly [Guarded, number] {
  const runs: Run[] = [];
  let chars = "";
  let quoted = false;
  let i = from;
  while (i < source.length) {
    const ch = source.charAt(i);
    if (ch === QUOTE) {
      if (quoted && source.charAt(i + 1) === QUOTE) {
        // Doubled inside quotes is the character itself: the language's one escape.
        chars += QUOTE;
        i += 2;
        continue;
      }
      if (chars) {
        runs.push([chars, quoted]);
        chars = "";
      }
      quoted = !quoted;
    } else if (!quoted && isSpace(ch)) {
      break;
    } else {
      chars += ch;
    }
    i++;
  }
  if (chars) runs.push([chars, quoted]);
  return [new Guarded(runs), i];
}

/** The `[start, end)` spans of `text` between its unquoted `sep` characters. */
export function separated(text: string, sep: string): (readonly [number, number])[] {
  const spans: (readonly [number, number])[] = [];
  let start = 0;
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text.charAt(i);
    if (ch === QUOTE) quoted = !quoted;
    else if (ch === sep && !quoted) {
      spans.push([start, i]);
      start = i + 1;
    }
  }
  spans.push([start, text.length]);
  return spans;
}

/** The `[start, end)` span of the token under `cursor` (an empty span on whitespace). */
export function activeSpan(source: string, cursor: number): readonly [number, number] {
  const c = Math.max(0, Math.min(cursor, source.length));
  for (const tok of lex(source)) {
    if (tok.start <= c && c <= tok.end) return [tok.start, tok.end];
  }
  return [c, c];
}
