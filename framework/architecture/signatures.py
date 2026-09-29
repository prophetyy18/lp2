"""Read the type names out of a contract signature string.

A contract may declare a capability two ways: with `input`/`output`/`payload`
schema refs, or with a free-text `signature:` that only names its types in
prose. Both spellings put type names in the metadata, and only the first one
is checkable today.

This module exists so the second spelling stops being invisible. It pulls the
type names back out of the signature string, and the validator reports any
that have no declared shape in `architecture/schemas/`. That is the whole
point: a type name nobody has declared is a name a tester cannot state an
expected value for and a developer cannot agree on.

It is a text scan, not a parser. It is deliberately conservative: it only
recognises shapes this repository actually uses, and anything it cannot read
it leaves alone rather than guessing. A signature it misreads produces a
missing-schema warning, not a wrong schema.
"""

from __future__ import annotations

import re

# Names that are part of the type *expression* rather than a declared type.
# A capitalised generic container still gets recursed into for its arguments —
# `list[Bar]` declares Bar — so this is a filter on the identifier stream, not
# a skip of the whole expression.
TYPE_EXPRESSION_NAMES = frozenset(
    {
        "list", "dict", "tuple", "set", "frozenset",
        "Iterable", "Iterator", "Sequence", "MutableSequence",
        "Mapping", "MutableMapping", "Callable",
        "Optional", "Union", "Any",
        "Awaitable", "Coroutine", "AsyncIterable", "AsyncIterator",
        "Generator", "Type",
    }
)

# Lowercase names are Python builtins or module paths, never a declared type.
# `Decimal` and `UUID` are here because they are library types, not ours: a
# schema for them would say nothing this repository decides.
BUILTIN_TYPE_NAMES = frozenset(
    {"str", "int", "float", "bool", "bytes", "bytearray", "None", "object",
     "Decimal", "UUID", "datetime", "date"}
)

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _split_top_level(text: str, sep: str) -> list[str]:
    """Split on `sep`, ignoring separators inside [] () {}."""
    out: list[str] = []
    depth = 0
    cur: list[str] = []
    for ch in text:
        if ch in "[({":
            depth += 1
        elif ch in "])}":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return out


def _declared_names(expr: str) -> set[str]:
    """Every declared type name mentioned anywhere in one type expression."""
    out: set[str] = set()
    for ident in _IDENT.findall(expr):
        if ident in TYPE_EXPRESSION_NAMES or ident in BUILTIN_TYPE_NAMES:
            continue
        # A declared type is capitalised. Anything else is a module path
        # (`decimal.Decimal`, `typing.Iterable`) or a keyword.
        if not ident[:1].isupper():
            continue
        out.add(ident)
    return out


def _params(signature: str) -> str:
    """The text between the outermost parentheses of the parameter list."""
    start = signature.find("(")
    if start == -1:
        return ""
    depth = 0
    for i in range(start, len(signature)):
        if signature[i] == "(":
            depth += 1
        elif signature[i] == ")":
            depth -= 1
            if depth == 0:
                return signature[start + 1 : i]
    return signature[start + 1 :]


def type_names(signature: str) -> set[str]:
    """The declared type names a signature mentions, parameters and return.

    >>> sorted(type_names("a.f(x: PositionKey, at: int) -> PositionValuation"))
    ['PositionKey', 'PositionValuation']
    >>> sorted(type_names("a.f(xs: list[LogRecord]) -> None"))
    ['LogRecord']
    >>> type_names("a.g(a: str, b: dict[str, int]) -> bytes")
    set()
    """
    if not signature or "(" not in signature:
        return set()

    out: set[str] = set()
    for param in _split_top_level(_params(signature), ","):
        param = param.strip()
        if ":" not in param:
            continue
        out |= _declared_names(param.split(":", 1)[1])

    if "->" in signature:
        out |= _declared_names(signature.split("->", 1)[1])

    return out


def bare_name_index(schemas: dict[str, dict]) -> dict[str, list[str]]:
    """Map each declared type's bare name to the contract-qualified ids owning it.

    A `signature:` names types bare — `ChainId`, not
    `robinhood-protocol-api.ChainId` — so matching a signature against the
    declared schemas needs the short name. It is only sound when the short
    name identifies exactly one type: a name two contracts both declare is
    not a match, it is a collision, and the validator reports it rather than
    picking one.
    """
    index: dict[str, list[str]] = {}
    for qualified in schemas:
        owner, _, bare = qualified.rpartition(".")
        if not bare:
            continue
        index.setdefault(bare, []).append(qualified)
    return index
