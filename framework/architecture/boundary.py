"""Module path boundary.

Answers question 1: "what may this module read?"

A module may read:
  * its own implementation tree          modules/<self>/**
  * the architecture metadata tree       architecture/**   (contracts + module
                                        declarations - the public surface)
  * anything explicitly granted          readable_extra globs in module.yaml

It may NOT read any other module's implementation. Not even to satisfy an
undeclared need: when a need is not covered by a contract, the framework
reports CONTRACT_INSUFFICIENT and the fix is a contract change, not a read.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import NamedTuple

from .errors import (
    ARCHITECTURE_CHANGE_REQUIRED,
    BOUNDARY_VIOLATION,
    Finding,
)
from .model import Architecture, Module

ARCH_TREE = "architecture/**"


class ReadRule(NamedTuple):
    glob: str
    reason: str
    granted: bool = True  # False => a deny rule, checked first


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    out = ["^"]
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    out.append("$")
    return re.compile("".join(out))


def normalize_path(path: str) -> str | None:
    """Return a repo-relative posix path, or None if it escapes the repo."""
    p = path.strip().lstrip("./")
    pure = PurePosixPath(p)
    if pure.is_absolute():
        return None
    parts: list[str] = []
    for part in pure.parts:
        if part == "..":
            if not parts:
                return None  # escapes the repo root
            parts.pop()
        elif part not in (".", ""):
            parts.append(part)
    return "/".join(parts)


def rules_for(module: Module) -> list[ReadRule]:
    """Effective read rules for a module: explicit grants only."""
    return [ReadRule(g, "granted by module.yaml readable_extra") for g in module.readable_extra]


def readable_rules(module: Module) -> list[ReadRule]:
    """Full allow-list shown to humans, baseline first."""
    base = [
        ReadRule(f"{module.path}/**", "own module implementation"),
        ReadRule(ARCH_TREE, "architecture metadata: contracts + module declarations"),
    ]
    return base + rules_for(module)


def check_read(module: Module, path: str, arch: Architecture | None = None) -> Finding | None:
    """Return None if readable, otherwise a Finding explaining the denial."""
    rel = normalize_path(path)
    if rel is None or not rel:
        return Finding(
            code=BOUNDARY_VIOLATION,
            message=f"path `{path}` is outside the repository root",
            context={"module": module.name, "path": path},
        )

    for rule in readable_rules(module):
        if _glob_to_regex(rule.glob).match(rel):
            return None

    return _denial(module, rel, arch)


def check_read_many(
    module: Module, paths: list[str], arch: Architecture | None = None
) -> list[Finding]:
    return [f for f in (check_read(module, p, arch) for p in paths) if f is not None]


def _denial(module: Module, rel: str, arch: Architecture | None) -> Finding:
    """Explain *why* it is denied and what the legitimate route is."""
    other = _owning_module(rel, arch)
    reason_key: str
    if other is not None and other != module.name:
        reason_key = "another module's internal implementation"
    elif rel.startswith("modules/"):
        reason_key = "a module implementation tree without being its owner"
    elif rel.startswith("framework/"):
        reason_key = "framework internals; framework calls modules, not the reverse"
    else:
        reason_key = "not covered by any read rule"

    context = {
        "module": module.name,
        "path": rel,
        "reason": reason_key,
        "allowed": [r.glob for r in readable_rules(module)],
        "remedy": ARCHITECTURE_CHANGE_REQUIRED,
    }

    if other is not None and arch is not None:
        # Point at the contracts this module already consumes: one of them is
        # the right place to declare the missing surface.
        context["consumed_contracts"] = [d.contract for d in module.depends_on]
        context["published_by"] = other

    return Finding(
        code=BOUNDARY_VIOLATION,
        message=(
            f"module `{module.name}` may not read `{rel}` ({reason_key}). "
            f"If this data is genuinely needed, add it to a contract "
            f"({ARCHITECTURE_CHANGE_REQUIRED}); do not read the implementation."
        ),
        context=context,
    )


def _owning_module(rel: str, arch: Architecture | None) -> str | None:
    """Which module's implementation tree contains this path."""
    if arch is None or not rel.startswith("modules/"):
        return None
    best: str | None = None
    best_len = -1
    for mod in arch.modules.values():
        prefix = mod.path.rstrip("/") + "/"
        if rel.startswith(prefix) and len(prefix) > best_len:
            best, best_len = mod.name, len(prefix)
    return best
