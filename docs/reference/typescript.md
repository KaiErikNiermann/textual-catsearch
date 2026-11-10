# TypeScript API

Everything below is exported from the package root (`import { parse } from "catsearch"`). Each name does what the [Python](python.md) name beside it does, so the Python reference is the longer description; this page gives the TypeScript shapes. Names are camelCase, field constructors take one options object, and offsets are UTF-16 code units.

## Parsing and matching

| export | Python | shape |
| --- | --- | --- |
| `parse` | `parse` | `parse(source, schema, options?: ParseOptions): Query<Row>`; never throws |
| `ParseOptions` | `empty_as_text=` | `{ emptyAsText? }`: an empty value stays literal text instead of being dropped (for text that names something, not a filter) |
| `Query` | `Query` | `.expr`, `.diagnostics`, `.matches(row)`, `.filter(rows)`, `.terms`, `.first(field)`, `.unknownFields`, `.notice`, `.isEmpty`, `.text` |
| `Diagnostic` | `Diagnostic` | `{ fault, text, start, end, reason }`, offsets in UTF-16 code units |
| `diagnostic` | `Diagnostic(...)` | builds a `Diagnostic` |
| `Fault` | `Fault` | the diagnostic kinds, as a frozen object of string constants and the union type of its values |
| `WORDING`, `describe`, `noticeOf` | `WORDING`, `Diagnostic.render`, `Query.notice` | how a diagnostic, or a list of them, reads in a status line |
| `holds` | `holds` | `holds(expr, row, schema): boolean` |
| `openGroups` | (internal) | how many brackets are open at the end of a query |
| `parseRange` | (internal) | a number field's value (`2020..2026`, `>=3`) as a `NumRange`, or `null` |
| `MAX_GROUPS`, `OR_WORDS`, `NOTHING` | same | nesting limit, the words that mean OR (`OR`, `\|`), and `none` |

## Schema and fields

| export | Python | shape |
| --- | --- | --- |
| `Schema` | `Schema` | `new Schema<Row>(fields, { bare, relations?, dynamic? })`; `.fields`, `.relations`, `.names`, `.canonical(name)`, `.field(name)`, `.relation(name)`, `.vocabulary(rows)`, `.completions(field, vocab)`; throws on a name claimed twice |
| `SchemaOptions` | keyword arguments of `Schema` | `{ bare, relations?, dynamic? }` |
| `textField`, `TextField` | `TextField` | `textField({ name, get, aliases?, detail?, choices?, complete? })` |
| `enumField`, `EnumField` | `EnumField` | `enumField({ name, get, choices?, normalize?, ... })` |
| `numberField`, `NumberField` | `NumberField` | `numberField({ name, get, parse?, unquoted?, ... })` |
| `flagField`, `FlagField` | `FlagField` | `flagField({ name, flags: { read: (row) => boolean, ... } })` |
| `customField`, `CustomField` | `CustomField` | `customField({ name, test, empty?, unquoted?, check?, every?, choices? })` |
| `relation`, `Relation` | `Relation` | `relation({ name, follow: (row) => Iterable<Row> })` |
| `Field` | `Field` | the union of the five field types |
| `Strings`, `Numbers`, `stringsOf`, `numbersOf` | accessor results | what a `get` may return (one value, an iterable, or nothing), and its normal form |
| `Unit` | `NumberField.parse` | `(text) => number \| [low, high] \| null` |
| `unquoted`, `detailOf` | `schema.unquoted`, `schema.detail_of` | a field's extra unquoted punctuation, and its completion label |
| `DYNAMIC_KEYS` | `schema.DYNAMIC_KEYS` | how many answers of `dynamic` are kept (4096) |
| `Vocabulary`, `vocabEntry`, `VocabEntry` | `Vocabulary`, `VocabEntry` | `new Vocabulary(entries, keys?)`, `.of(field)`, `.merged(other)`; `vocabEntry(value, uses)` |
| `Completions` | (return type) | `[VocabEntry, detail]` pairs, best first |

## Rendering and text

| export | Python | shape |
| --- | --- | --- |
| `render` | `render` | `render(expr, schema): string`; `parse(render(e))` gives `e` back |
| `quote` | `quote` | `quote(value, extra?)`: a value as query text, quoted when it has to be |
| `QUOTE` | (constant) | `"` |
| `fold` | `fold` | case- and accent-insensitive comparison key |
| `wordPrefixed` | (internal) | whether a word of `value` starts with `needle` |

## Completion

| export | Python | shape |
| --- | --- | --- |
| `suggest` | `suggest` | `suggest(source, cursor, schema, vocab?, { limit?, fields? }): Suggestion[]` |
| `SuggestOptions` | keyword arguments of `suggest` | `{ limit?, fields? }` |
| `Suggestion` | `Suggestion` | `{ insert, label, detail, start, end, kind: "field" \| "value" }` |
| `apply` | `apply` | `apply(source, suggestion): string`, the text with the completion spliced in |
| `rankValues` | `rank_values` | `rankValues(schema, field, vocab, needle, limit?)` |

## Editing queries

| export | Python | shape |
| --- | --- | --- |
| `pinned` | `pinned` | `pinned(query, field, among?)`: the one value the query pins `field` to, if any |
| `withTerm` | `with_term` | `withTerm(query, pin, { among? })`: the query text with the pin's field pinned to its values, every other clause intact |
| `without` | `without` | `without(query, field, { among? })`: the query text with no pin on `field` (an "all" tab), every other clause intact |
| `AmongOptions` | `among=` | `{ among?: Iterable<string> }` |

## Query trees

Trees are plain readonly objects tagged by `kind`, built by functions rather than classes.

| export | Python | shape |
| --- | --- | --- |
| `Expr` | `Expr` | `Term \| And \| Or \| Not` |
| `term`, `Term` | `Term` | `term(field, { values?, ranges?, negated?, absent?, via? })` |
| `and`, `And` / `or`, `Or` / `not`, `Not` | `And`, `Or`, `Not` | `and(parts)`, `or(parts)`, `not(inner)` |
| `numRange`, `NumRange`, `rangeContains` | `NumRange` | `{ lo, hi, loStrict, hiStrict }` (`null` for an open end) and its membership test |
| `neg` | `neg` | an expression negated, in normal form (a negated `Term`, or the inner of a `Not`) |
| `exprEquals` | `==` | structural equality of two trees |

## Lexing

| export | Python | shape |
| --- | --- | --- |
| `lex`, `Token`, `Run` | `lex`, `Token` | `lex(source): Token[]` |
| `activeSpan` | `active_span` | `activeSpan(source, cursor)`: the token under the cursor, as `[start, end]` |
| `separated` | (internal) | split a value on a separator outside quotes, as spans |
| `Guarded` | `lexer.Guarded` | a value as quoted and free runs, so separators inside quotes are plain characters |
