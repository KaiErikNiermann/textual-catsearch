/**
 * Discord-style category search: declare your fields, get a query language over them
 * (`author:"le guin" year:1960..1980 -is:read`), filtering, rendering back to text, and
 * completion of field names and values.
 *
 * The TypeScript port of the `textual-catsearch` Python package, held to the same answers by
 * the shared spec under `spec/`. Offsets are UTF-16 code units, as the DOM counts them.
 */

export { apply, rankValues, suggest } from "./complete.ts";
export type { Suggestion, SuggestOptions } from "./complete.ts";
export { holds } from "./evaluate.ts";
export { Guarded, QUOTE, activeSpan, lex, separated } from "./lexer.ts";
export type { Run, Token } from "./lexer.ts";
export { openGroups, parse, parseRange } from "./parser.ts";
export type { ParseOptions } from "./parser.ts";
export { Fault, MAX_GROUPS, NOTHING, OR_WORDS, Query, WORDING, describe, diagnostic, noticeOf } from "./query.ts";
export type { Diagnostic } from "./query.ts";
export { quote, render } from "./render.ts";
export {
  DYNAMIC_KEYS,
  Schema,
  Vocabulary,
  customField,
  detailOf,
  enumField,
  flagField,
  numberField,
  numbersOf,
  relation,
  stringsOf,
  textField,
  unquoted,
  vocabEntry,
} from "./schema.ts";
export type {
  Completions,
  CustomField,
  EnumField,
  Field,
  FlagField,
  NumberField,
  Numbers,
  Relation,
  SchemaOptions,
  Strings,
  TextField,
  Unit,
  VocabEntry,
} from "./schema.ts";
export { fold, wordPrefixed } from "./text.ts";
export { pinned, withTerm, without } from "./transform.ts";
export type { AmongOptions } from "./transform.ts";
export { and, exprEquals, neg, not, numRange, or, rangeContains, term } from "./tree.ts";
export type { And, Expr, Not, NumRange, Or, Term } from "./tree.ts";
