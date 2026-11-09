/** How two strings are compared: one spelling per name, however it was typed. */

import { PLAIN_ASCII, casefold, isAlnum, isCombining, isInvisible } from "./unicode.ts";

const CACHE_SIZE = 16_384;
const cache = new Map<string, string>();

/**
 * The form two names are compared in: one spelling per name, however it was typed.
 *
 * Drop what is invisible (format and control characters, line and paragraph separators),
 * decompose (NFKD), drop the combining marks, recompose (NFC), casefold. So `Café` typed on
 * macOS finds `Café` pasted from the web, `ｃａｆｅ` from an IME finds `cafe`, `STRASSE` finds
 * `Straße`, and `cafe` finds `Café`. Scripts are deliberately not folded: a Cyrillic `А` stays
 * apart from a Latin `A`.
 *
 * Cached, because a snapshot's names repeat and the same haystack is folded every keystroke.
 */
export function fold(text: string): string {
  const hit = cache.get(text);
  if (hit !== undefined) return hit;
  const folded = PLAIN_ASCII.test(text) ? text.toLowerCase() : foldSlow(text);
  if (cache.size >= CACHE_SIZE) cache.clear();
  cache.set(text, folded);
  return folded;
}

function foldSlow(text: string): string {
  let visible = "";
  for (const ch of text) if (!isInvisible(ch.codePointAt(0) ?? 0)) visible += ch;
  let bare = "";
  for (const ch of visible.normalize("NFKD")) if (!isCombining(ch.codePointAt(0) ?? 0)) bare += ch;
  return casefold(bare.normalize("NFC"));
}

/** The words of a folded value: runs of letters and digits (Python's `[\W_]+` splits). */
function words(text: string): string[] {
  const out: string[] = [];
  let word = "";
  for (const ch of text) {
    if (isAlnum(ch.codePointAt(0) ?? 0)) word += ch;
    else if (word) {
      out.push(word);
      word = "";
    }
  }
  if (word) out.push(word);
  return out;
}

/**
 * Does `value` begin with `needle`, at its start or at the start of one of its words?
 *
 * `needle` is expected folded already. Prefix rather than substring, so typing narrows
 * monotonically; word starts count, so `cast:rit` finds *Alan Ritchson*.
 */
export function wordPrefixed(value: string, needle: string): boolean {
  const low = fold(value);
  return low.startsWith(needle) || words(low).some((w) => w.startsWith(needle));
}
