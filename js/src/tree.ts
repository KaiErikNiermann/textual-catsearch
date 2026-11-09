/** The parsed shape of a query: clauses, conjunction, alternation and negation. */

/**
 * A numeric window; an open end is `null` (`year:>=2026`).
 *
 * Inclusive, unless a bound is marked strict. Integer fields never need that (`>2020` is
 * `>=2021`), but a field with a unit parser reads real quantities, where `took:>5m` must keep
 * 300.5 seconds.
 */
export interface NumRange {
  readonly lo: number | null;
  readonly hi: number | null;
  readonly loStrict: boolean;
  readonly hiStrict: boolean;
}

/** One clause. `values` are OR-ed; `negated` inverts the whole term. */
export interface Term {
  readonly kind: "term";
  readonly field: string;
  readonly values: readonly string[];
  readonly ranges: readonly NumRange[];
  readonly negated: boolean;
  /** `field:none`: the row has nothing under this field. OR-ed with the values. */
  readonly absent: boolean;
  /** Relations to follow before asking: `parent.year:<2020` is `via: ["parent"]`. */
  readonly via: readonly string[];
}

/** Every part holds. The shape of a whole query; an empty one matches everything. */
export interface And {
  readonly kind: "and";
  readonly parts: readonly Expr[];
}

/** Any part holds. Binds tighter than juxtaposition, so `a OR b c` is `(a OR b) and c`. */
export interface Or {
  readonly kind: "or";
  readonly parts: readonly Expr[];
}

/** The inner expression does not hold. Only ever wraps a group: a negated clause is a
 * `Term` with `negated` set, which `neg` is the one place to decide. */
export interface Not {
  readonly kind: "not";
  readonly inner: Expr;
}

export type Expr = Term | And | Or | Not;

export function numRange(range: Partial<NumRange> = {}): NumRange {
  return {
    lo: range.lo ?? null,
    hi: range.hi ?? null,
    loStrict: range.loStrict ?? false,
    hiStrict: range.hiStrict ?? false,
  };
}

/** Is `n` in the window? Never for NaN. */
export function rangeContains(range: NumRange, n: number): boolean {
  if (Number.isNaN(n)) return false;
  const { lo, hi } = range;
  const above = lo === null || (range.loStrict ? n > lo : n >= lo);
  const below = hi === null || (range.hiStrict ? n < hi : n <= hi);
  return above && below;
}

export function term(field: string, rest: Partial<Omit<Term, "kind" | "field">> = {}): Term {
  return {
    kind: "term",
    field,
    values: rest.values ?? [],
    ranges: rest.ranges ?? [],
    negated: rest.negated ?? false,
    absent: rest.absent ?? false,
    via: rest.via ?? [],
  };
}

export function and(parts: readonly Expr[] = []): And {
  return { kind: "and", parts };
}

export function or(parts: readonly Expr[] = []): Or {
  return { kind: "or", parts };
}

export function not(inner: Expr): Not {
  return { kind: "not", inner };
}

/** `expr`, negated, in normal form. */
export function neg(expr: Expr): Expr {
  switch (expr.kind) {
    case "term": {
      return { ...expr, negated: !expr.negated };
    }
    case "not": {
      return expr.inner;
    }
    default: {
      return not(expr);
    }
  }
}

function sameStrings(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

function sameRange(a: NumRange, b: NumRange): boolean {
  return a.lo === b.lo && a.hi === b.hi && a.loStrict === b.loStrict && a.hiStrict === b.hiStrict;
}

function sameParts(a: readonly Expr[], b: readonly Expr[]): boolean {
  return a.length === b.length && a.every((p, i) => {
    const q = b[i];
    return q !== undefined && exprEquals(p, q);
  });
}

/** Structural equality: what Python's dataclass `==` is for the tree. */
export function exprEquals(a: Expr, b: Expr): boolean {
  switch (a.kind) {
    case "term": {
      return (
        b.kind === "term" &&
        a.field === b.field &&
        a.negated === b.negated &&
        a.absent === b.absent &&
        sameStrings(a.values, b.values) &&
        sameStrings(a.via, b.via) &&
        a.ranges.length === b.ranges.length &&
        a.ranges.every((r, i) => {
          const s = b.ranges[i];
          return s !== undefined && sameRange(r, s);
        })
      );
    }
    case "not": {
      return b.kind === "not" && exprEquals(a.inner, b.inner);
    }
    case "and":
    case "or": {
      return b.kind === a.kind && sameParts(a.parts, b.parts);
    }
  }
}
