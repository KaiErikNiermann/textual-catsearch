"""Lexing: a query string into tokens that remember which characters were quoted.

Hand-rolled rather than ``shlex``; see :func:`lex` for why.
"""

from __future__ import annotations

import string
from dataclasses import dataclass
from typing import Final

__all__ = ["QUOTE", "WORD", "Guarded", "Token", "active_span", "lex", "separated"]

QUOTE: Final[str] = '"'

# What an unquoted *value* may be spelled with. Everything else belongs to the grammar — see
# `render.quote` for why the line is drawn wider than today's syntax needs. Bare words are
# exempt: they are free text, not values.
WORD: Final[frozenset[str]] = frozenset(string.ascii_letters + string.digits + "_-")


@dataclass(frozen=True, slots=True)
class Guarded:
    """Text that remembers which of its characters were written inside quotes.

    The lexer used to strip quotes and throw away the fact that they had been there, which
    meant quoting protected nothing: ``"kind:tv"`` was read as a kind filter rather than as a
    title, ``cast:"a, b"`` split into two names at the comma the user had deliberately
    enclosed, and a group could not contain a value ending in ``)``. All four are the same
    bug seen from different angles — a separator inside quotes still separated.

    So a token is runs of text, each flagged with whether it was quoted, and every place that
    looks for a separator looks only at the *free* ones. Runs rather than a per-character
    mask because a token is one to three runs in practice: ``cast:`` and ``Alan Ritchson``.
    """

    runs: tuple[tuple[str, bool], ...] = ()

    @property
    def text(self) -> str:
        return "".join(text for text, _ in self.runs)

    def __bool__(self) -> bool:
        return bool(self.text)

    @property
    def bare(self) -> bool:
        """Was none of this written inside quotes?

        The one question the language asks of a word before letting it mean something other
        than itself. ``"OR"`` is a title, ``OR`` is an operator; ``tag:"none"`` is a tag and
        ``tag:none`` is a question about absence.
        """
        return not any(guarded for _, guarded in self.runs)

    def is_free(self, word: str) -> bool:
        """Is this exactly ``word``, written without quotes? ``"OR"`` is a title, ``OR`` is not."""
        return self.text == word and self.bare

    def strip(self) -> Guarded:
        """Drop leading and trailing whitespace — a value is never meant to be padded."""
        runs = list(self.runs)
        for end in (0, -1):
            while runs:
                text = runs[end][0].lstrip() if end == 0 else runs[end][0].rstrip()
                if text:
                    runs[end] = (text, runs[end][1])
                    break
                runs.pop(end)
        return Guarded(tuple(runs))

    def peel(self, opening: str, closing: str) -> tuple[int, Guarded, int]:
        """Take unquoted ``opening`` off the front and ``closing`` off the back, counting both.

        Quoted brackets stay: ``"Fallout (TV)"`` is a title, and a group closing right after
        it still closes.
        """
        runs = list(self.runs)
        lead = 0
        while runs and not runs[0][1]:
            text = runs[0][0].lstrip(opening)
            lead += len(runs[0][0]) - len(text)
            if text:
                runs[0] = (text, False)
                break
            runs.pop(0)
        trail = 0
        while runs and not runs[-1][1]:
            text = runs[-1][0].rstrip(closing)
            trail += len(runs[-1][0]) - len(text)
            if text:
                runs[-1] = (text, False)
                break
            runs.pop()
        return lead, Guarded(tuple(runs)), trail

    def free_text(self) -> str:
        """Only the characters written *outside* quotes — what the value grammar governs."""
        return "".join(text for text, guarded in self.runs if not guarded)

    def sign(self) -> tuple[bool, Guarded]:
        """Take an unquoted leading ``-`` or ``!`` off, if there is one and something follows."""
        if not self.runs or self.runs[0][1] or self.runs[0][0][:1] not in ("-", "!"):
            return False, self
        rest = Guarded(((self.runs[0][0][1:], False), *self.runs[1:]))
        return (True, rest) if rest.text else (False, self)

    def then(self, text: str) -> Guarded:
        """This, with plain unquoted ``text`` appended — used to put back what was over-peeled."""
        return Guarded((*self.runs, (text, False))) if text else self

    def partition(self, sep: str) -> tuple[str, bool, Guarded]:
        """Split at the first *unquoted* ``sep``. The head names a field, so it is plain text."""
        head: list[str] = []
        for i, (text, guarded) in enumerate(self.runs):
            if not guarded and (at := text.find(sep)) >= 0:
                return (
                    "".join([*head, text[:at]]),
                    True,
                    Guarded(((text[at + 1 :], False), *self.runs[i + 1 :])),
                )
            head.append(text)
        return self.text, False, Guarded()

    def split(self, sep: str) -> tuple[Guarded, ...]:
        """Split on every *unquoted* ``sep`` — the commas that mean "or", not those in a title."""
        out: list[list[tuple[str, bool]]] = [[]]
        for text, guarded in self.runs:
            if guarded:
                out[-1].append((text, True))
                continue
            first, *rest = text.split(sep)
            out[-1].append((first, False))
            out.extend([(piece, False)] for piece in rest)
        return tuple(Guarded(tuple(runs)) for runs in out)


@dataclass(frozen=True, slots=True)
class Token:
    """One lexed token plus its source span, so completion can splice by offset."""

    body: Guarded
    start: int  # inclusive offset into the source
    end: int  # exclusive

    @property
    def text(self) -> str:
        """The token with its quote characters removed."""
        return self.body.text


def lex(source: str) -> tuple[Token, ...]:
    """Split a query into tokens. **Never raises.**

    Hand-rolled rather than ``shlex`` for three reasons, all of which matter for a
    search box over names people typed:

    * ``shlex`` treats ``'`` as a quote, so ``Don't Look Up`` raises — and closing the quote
      to recover silently mangles it to ``Dont Look Up``. Here only ``"`` groups; an
      apostrophe is always a literal character.
    * An unterminated quote is the normal state while typing ``cast:"Alan Rit``, not an error.
    * ``shlex`` discards offsets, and cursor-aware completion needs spans — using it would
      mean a second lexer for completion, which could then disagree with this one.
    """
    tokens: list[Token] = []
    i, n = 0, len(source)
    while i < n:
        while i < n and source[i].isspace():
            i += 1
        if i >= n:
            break
        start = i
        body, i = _scan(source, i)
        tokens.append(Token(body=body, start=start, end=i))
    return tuple(tokens)


def _scan(source: str, i: int) -> tuple[Guarded, int]:
    """One token from ``i``: its runs of quoted and unquoted text, and where it ended."""
    runs: list[tuple[str, bool]] = []
    chars: list[str] = []
    quoted = False
    while i < len(source):
        ch = source[i]
        if ch == QUOTE:
            if quoted and source[i + 1 : i + 2] == QUOTE:
                # Doubled inside quotes is the character itself, so a work called
                # `The "Burbs` can be named at all. There is nowhere else to put an escape:
                # a backslash is a character titles genuinely contain.
                chars.append(QUOTE)
                i += 2
                continue
            if chars:
                runs.append(("".join(chars), quoted))
                chars = []
            quoted = not quoted
        elif ch.isspace() and not quoted:
            break
        else:
            chars.append(ch)
        i += 1
    if chars:
        runs.append(("".join(chars), quoted))
    return Guarded(tuple(runs)), i


def separated(text: str, sep: str) -> tuple[tuple[int, int], ...]:
    """The ``[start, end)`` spans of ``text`` between its *unquoted* ``sep`` characters.

    :meth:`Guarded.split` for raw text, where the offsets are the point: completion splices
    one segment of a comma list back into the source. Quoted is decided as :func:`_scan`
    decides it — an odd number of quotes so far — and a doubled ``""`` adds two, so it never
    changes the answer.
    """
    spans: list[tuple[int, int]] = []
    start, quoted = 0, False
    for i, ch in enumerate(text):
        if ch == QUOTE:
            quoted = not quoted
        elif ch == sep and not quoted:
            spans.append((start, i))
            start = i + 1
    return (*spans, (start, len(text)))


def active_span(source: str, cursor: int) -> tuple[int, int]:
    """The ``[start, end)`` span of the token under ``cursor`` (empty span on whitespace)."""
    c = max(0, min(cursor, len(source)))
    for tok in lex(source):
        if tok.start <= c <= tok.end:
            return tok.start, tok.end
    return c, c
