/**
 * Python's string semantics, where the port depends on them and JavaScript's differ.
 *
 * The Python package is the reference, and a query has to mean the same thing in both. JS's
 * `trim` and `\s` disagree with `str.isspace` (U+FEFF is space to JS, U+001C to Python),
 * JS has no full case folding and no combining class, and `int()` reads any script's decimal
 * digits. The tables come from Python's `unicodedata` (see `unicode-data.ts`), so none of this
 * depends on the Unicode version the engine ships.
 *
 * Offsets everywhere in the port are UTF-16 code units, which is what the DOM hands out
 * (`selectionStart`). Every operation here is safe on them: whitespace, quotes and the
 * grammar's punctuation are all in the BMP, so nothing splits a surrogate pair.
 */

import { ALNUM, CASEFOLD, CASEFOLD_MULTI, COMBINING, DIGITS, INVISIBLE, SPACE } from "./unicode-data.ts";

/** Packed ranges (see `tests/conformance/unicode_tables.py`) as a sorted flat array. */
function unpack(packed: string): Uint32Array {
  const parts = packed.split(",");
  const out = new Uint32Array(parts.length);
  let last = 0;
  for (let i = 0; i < parts.length; i += 2) {
    const start = last + Number.parseInt(parts[i] ?? "0", 36);
    const end = start + Number.parseInt(parts[i + 1] ?? "0", 36);
    out[i] = start;
    out[i + 1] = end;
    last = end;
  }
  return out;
}

/** Index of the range holding `cp`, or -1. Binary search over inclusive pairs. */
function rangeOf(ranges: Uint32Array, cp: number): number {
  let lo = 0;
  let hi = ranges.length / 2 - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >>> 1;
    const start = ranges[mid * 2] ?? 0;
    const end = ranges[mid * 2 + 1] ?? 0;
    if (cp < start) hi = mid - 1;
    else if (cp > end) lo = mid + 1;
    else return mid;
  }
  return -1;
}

const SPACES = unpack(SPACE);
const COMBININGS = unpack(COMBINING);
const INVISIBLES = unpack(INVISIBLE);
const ALNUMS = unpack(ALNUM);
const DIGIT_RUNS = unpack(DIGITS);
const FOLDS = unpackFolds(CASEFOLD);
const MULTI_FOLDS: ReadonlyMap<string, string> = new Map(Object.entries(CASEFOLD_MULTI));

/** The case-fold runs (see `_casefold` in `tests/conformance/unicode_tables.py`) as a map. */
function unpackFolds(packed: string): ReadonlyMap<number, number> {
  const out = new Map<number, number>();
  let last = 0;
  for (const run of packed.split(";")) {
    const [gap = "0", count = "0", stride = "1", delta = "0"] = run.split(",", 4);
    const start = last + Number.parseInt(gap, 36);
    const n = Number.parseInt(count, 36);
    const step = Number.parseInt(stride, 36);
    const shift = Number.parseInt(delta, 36);
    for (let i = 0; i < n; i++) out.set(start + i * step, start + i * step + shift);
    last = start + (n - 1) * step;
  }
  return out;
}

function charClass(ranges: Uint32Array): string {
  let out = "";
  for (let i = 0; i < ranges.length; i += 2) {
    out += String.raw`\u{${(ranges[i] ?? 0).toString(16)}}-\u{${(ranges[i + 1] ?? 0).toString(16)}}`;
  }
  return out;
}

/** Python's `\s` and `\w` as the bodies of a `u`-flag character class. */
export const SPACE_CLASS = charClass(SPACES);
export const WORD_CLASS = `${charClass(ALNUMS)}_`;

/** `ch.isspace()` for one code unit (every whitespace character is in the BMP). */
export function isSpace(ch: string): boolean {
  if (ch.length !== 1) return false;
  const cp = ch.charCodeAt(0);
  // ASCII by hand (\t..\r, the four information separators, space): most text is ASCII.
  return cp < 0x80 ? (cp >= 0x09 && cp <= 0x0D) || (cp >= 0x1C && cp <= 0x20) : rangeOf(SPACES, cp) >= 0;
}

/** `str.isalnum()` for one code point. */
export function isAlnum(cp: number): boolean {
  return rangeOf(ALNUMS, cp) >= 0;
}

/** The value of a decimal digit in any script (`unicodedata.decimal`), or -1. */
export function digitValue(cp: number): number {
  const at = rangeOf(DIGIT_RUNS, cp);
  return at < 0 ? -1 : (cp - (DIGIT_RUNS[at * 2] ?? 0)) % 10;
}

export function isCombining(cp: number): boolean {
  return rangeOf(COMBININGS, cp) >= 0;
}

export function isInvisible(cp: number): boolean {
  return rangeOf(INVISIBLES, cp) >= 0;
}

/** `str.casefold()`, from Python's tables: never the engine's own case mapping. */
export function casefold(text: string): string {
  if (PLAIN_ASCII.test(text)) return text.toLowerCase();
  let out = "";
  for (const ch of text) {
    const cp = ch.codePointAt(0) ?? 0;
    const single = FOLDS.get(cp);
    out += single === undefined ? (MULTI_FOLDS.get(ch) ?? ch) : String.fromCodePoint(single);
  }
  return out;
}

/** ASCII with no control characters: the fast path for `fold` and `casefold`. */
export const PLAIN_ASCII = /^[ -~]*$/u;

/** `str.strip()` with no argument: Python's whitespace, not JS's. */
export function strip(text: string): string {
  let start = 0;
  let end = text.length;
  while (start < end && isSpace(text.charAt(start))) start++;
  while (end > start && isSpace(text.charAt(end - 1))) end--;
  return start === 0 && end === text.length ? text : text.slice(start, end);
}

export function lstrip(text: string): string {
  let start = 0;
  while (start < text.length && isSpace(text.charAt(start))) start++;
  return text.slice(start);
}

export function rstrip(text: string): string {
  let end = text.length;
  while (end > 0 && isSpace(text.charAt(end - 1))) end--;
  return text.slice(0, end);
}

/** `str.lstrip(chars)`: every leading character that is one of `chars`. */
export function lstripChars(text: string, chars: string): string {
  let start = 0;
  while (start < text.length && chars.includes(text.charAt(start))) start++;
  return text.slice(start);
}

/** `str.rstrip(chars)`. */
export function rstripChars(text: string, chars: string): string {
  let end = text.length;
  while (end > 0 && chars.includes(text.charAt(end - 1))) end--;
  return text.slice(0, end);
}

/** `str.strip(chars)`. */
export function stripChars(text: string, chars: string): string {
  return rstripChars(lstripChars(text, chars), chars);
}

/** `str.partition(sep)`: head, whether `sep` was found, tail. */
export function partition(text: string, sep: string): readonly [string, boolean, string] {
  const at = text.indexOf(sep);
  return at === -1 ? [text, false, ""] : [text.slice(0, at), true, text.slice(at + sep.length)];
}

/** `str.rpartition(sep)`: head, whether `sep` was found, tail. */
export function rpartition(text: string, sep: string): readonly [string, boolean, string] {
  const at = text.lastIndexOf(sep);
  return at === -1 ? ["", false, text] : [text.slice(0, at), true, text.slice(at + sep.length)];
}

/** `str.count(sub)` for a one-character `sub`, over `[start, end)`. */
export function countChar(text: string, ch: string, start = 0, end = text.length): number {
  let n = 0;
  for (let i = start; i < end; i++) if (text.charAt(i) === ch) n++;
  return n;
}

/** Python's `str` ordering: by code point, where JS's `<` compares UTF-16 code units. */
export function compareCodePoints(a: string, b: string): number {
  if (a === b) return 0;
  const left = a[Symbol.iterator]();
  const right = b[Symbol.iterator]();
  for (;;) {
    const x = left.next();
    const y = right.next();
    if (x.done === true) return y.done === true ? 0 : -1;
    if (y.done === true) return 1;
    const cx = x.value.codePointAt(0) ?? 0;
    const cy = y.value.codePointAt(0) ?? 0;
    if (cx !== cy) return cx < cy ? -1 : 1;
  }
}

// Python refuses to read an integer longer than this (`sys.get_int_max_str_digits()`), and a
// value it refuses is a value that is not a number: the port has to refuse it too.
const MAX_INT_DIGITS = 4300;
// Not catastrophic: each `_` must sit between digits, so no two repetitions share a match.
// eslint-disable-next-line security/detect-unsafe-regex
const INTEGER = /^[+-]?\p{Nd}+(?:_\p{Nd}+)*$/u;

/** `int(text)` in base 10: any script's digits, `_` between them, Python's whitespace around.
 * `undefined` where Python raises `ValueError`. */
export function pyInt(text: string): bigint | undefined {
  const body = strip(text);
  if (!INTEGER.test(body)) return undefined;
  let digits = "";
  for (const ch of body) {
    if (ch === "_") continue;
    if (ch === "+" || ch === "-") {
      digits += ch;
      continue;
    }
    const value = digitValue(ch.codePointAt(0) ?? 0);
    if (value < 0) return undefined; // \p{Nd} of a newer Unicode than the tables know
    digits += String(value);
  }
  const count = digits.replace(/^[+-]/u, "").length;
  return count > MAX_INT_DIGITS ? undefined : BigInt(digits);
}
