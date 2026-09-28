"""AST-based cross-module import scanner.

Rules:

  - Allowed:
    * stdlib and third-party packages (anything not rooted at a project
      top-level package)
    * `framework.architecture` (public API surface only)
    * the module's own source tree: `modules/<self>/**`
    * a declared upstream's public surface, when this module's module.yaml
      both (a) declares `depends_on` on a contract that upstream owns and
      (b) grants the path through `readable_extra`
  - Forbidden:
    * `modules/<N>/**` for N != self without that declaration
      -> CONTRACT_INSUFFICIENT when the upstream publishes a contract this
         module does not declare; BOUNDARY_VIOLATION otherwise
    * `framework.architecture.<private>` (anything starting with an
      underscore) -> INTERNAL_LEAK
    * legacy project packages (`robinhood_lp.*`) -> LEGACY_LEAK

Boundary semantics are NOT re-implemented here. For every `modules.*` import
this scanner resolves the repo-relative path and asks the architecture
framework (`framework.architecture.check_read`) whether the importing module
may read it. The scanner only adds import-level detail on top: which module
owns the path, and whether the denial is fixable by declaring a dependency.

`modules/` directory names use hyphens (`robinhood-protocol`) while Python
package names use underscores (`robinhood_protocol`); the scanner resolves
between them through the architecture, so both spellings work.

Output: a list of Finding records, each tagged with file/line/code.
The CLI returns exit code 1 if any ERROR-severity finding is present.
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from framework.architecture import Architecture, check_read, load as load_arch

# Modules that look like stdlib but live in `tools/` and `tests/` are
# legitimate top-level project packages; do not flag them.
PROJECT_TOP_LEVEL: frozenset[str] = frozenset(
    {"tools", "tests", "framework", "architecture", "modules"}
)

# Legacy project package names that must never leak into modules/.
LEGACY_DENYLIST: frozenset[str] = frozenset(
    {"robinhood_lp", "robinhood-lp", "robinhood"}
)

# Third-party packages this project depends on. Allow anything not
# matching PROJECT_TOP_LEVEL and not starting with `modules.`.
# We do not enumerate every dep; we only check the import exists.
THIRD_PARTY_PREFIXES: tuple[str, ...] = ()

# Anything under `framework.architecture` whose path starts with an
# underscore is private internals.
INTERNAL_LEAK_PREFIX = "framework.architecture."


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str  # ERROR | INFO
    module: str
    file: str
    line: int
    spec: str
    message: str

    def format(self) -> str:
        return (
            f"[{self.severity}] {self.code}: {self.module}: "
            f"{self.file}:{self.line} {self.spec} -- {self.message}"
        )


def _imports_in(tree: ast.AST) -> Iterable[tuple[str, int]]:
    """Yield (module_spec, lineno) for every import statement."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield (alias.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level and node.module is None:
                # relative import; treat as the current package's own scope
                yield (".relative", node.lineno)
                continue
            if node.level:
                # `from .foo import bar` => `mod` is the in-package path
                yield (mod, node.lineno)
            else:
                yield (mod, node.lineno)


def _pkg_key(module_name: str) -> str:
    """Python package spelling of a module directory name."""
    return module_name.replace("-", "_")


def _resolve_owner(
    spec: str, self_module: str, arch: Architecture | None
) -> tuple[str, str]:
    """Return (kind, owner) for a dotted import spec.

    kind is one of: 'modules-self', 'modules-other', 'modules-unknown',
    'framework-public', 'framework-internal', 'legacy', 'third-party',
    'top-level', 'relative'.
    owner is the module directory name this would route to, when applicable.
    """
    if spec.startswith("."):
        return ("relative", "")
    parts = spec.split(".")
    head = parts[0]
    if head in LEGACY_DENYLIST:
        return ("legacy", head)
    if head in PROJECT_TOP_LEVEL:
        if head == "modules" and len(parts) >= 2:
            key = parts[1]
            real = None
            if arch is not None:
                real = next(
                    (
                        m.name
                        for m in arch.modules.values()
                        if _pkg_key(m.name) == key
                    ),
                    None,
                )
            if real is None:
                # No architecture to resolve against: fall back to comparing
                # the normalised spellings so `modules.robinhood_rpc` is
                # recognised as self.
                if arch is not None:
                    return ("modules-unknown", key)
                real = self_module if _pkg_key(self_module) == key else key
            if real == self_module:
                return ("modules-self", real)
            return ("modules-other", real)
        if head == "framework" and len(parts) >= 2 and parts[1] == "architecture":
            return ("framework-public", head)
        return ("top-level", head)
    # Anything else is third-party or stdlib. We don't differentiate;
    # the scanner does not enforce third-party denylists by default.
    return ("third-party", head)


def _spec_paths(spec: str, owner: str, arch: Architecture | None) -> list[str]:
    """Repo-relative paths a `modules.<owner>...` spec could denote, deepest first.

    The first entry adds a sentinel child so that a glob ending in `/**`
    matches a bare package import (`from modules.b.api import x` names the
    package `api`, not a file inside it). The second is the bare path, for
    grants written without `/**`.
    """
    parts = spec.split(".")
    root = f"modules/{owner}"
    if arch is not None:
        declared = arch.modules.get(owner)
        if declared is not None:
            root = declared.path.rstrip("/")
    tail = "/".join(parts[2:])
    path = f"{root}/{tail}" if tail else root
    return [f"{path}/_", path]


def _cross_module_finding(
    self_module: str,
    owner: str,
    spec: str,
    arch: Architecture | None,
) -> tuple[str, str]:
    """Decide the finding code for a denied cross-module import.

    When the upstream publishes a contract and this module never declared
    `depends_on` on it, the denial is fixable by declaring the dependency:
    report CONTRACT_INSUFFICIENT, which points at the missing declaration
    instead of restating the wall.
    """
    if arch is not None:
        upstream = arch.modules.get(owner)
        consumer = arch.modules.get(self_module)
        if upstream is not None and consumer is not None and upstream.owns_contracts:
            declared = {d.contract for d in consumer.depends_on}
            missing = [c for c in upstream.owns_contracts if c not in declared]
            if missing:
                return (
                    "CONTRACT_INSUFFICIENT",
                    f"module `{self_module}` imports `{spec}` from `{owner}` but "
                    f"declares no depends_on on {', '.join(missing)}. Declare the "
                    f"dependency and grant the public surface via readable_extra; "
                    f"do not import `{owner}`'s implementation.",
                )
    return (
        "BOUNDARY_VIOLATION",
        f"cross-module import: {self_module} may not import `{spec}` "
        f"(owned by {owner}); route through a contract capability instead",
    )


def _load_architecture() -> Architecture | None:
    """Load the real project architecture, or None if it is unavailable."""
    try:
        return load_arch()
    except Exception:  # noqa: BLE001 - absence of architecture is not fatal here
        return None


def _is_readable(
    arch: Architecture | None,
    self_module: str,
    owner: str,
    spec: str,
) -> bool:
    """Ask the framework whether this module may read this path.

    Without an architecture there is nothing to declare against, so the
    scanner stays strict and denies every cross-module import.
    """
    if arch is None:
        return False
    consumer = arch.modules.get(self_module)
    if consumer is None:
        return False
    # Deepest match wins: the import is allowed when the most specific
    # spelling of the path is covered by a read rule.
    return any(
        check_read(consumer, path, arch) is None
        for path in _spec_paths(spec, owner, arch)
    )


def scan_module(
    module_name: str,
    modules_root: Path = Path("modules"),
    arch: Architecture | None = None,
    strict_missing: bool = False,
) -> list[Finding]:
    """Scan all .py files under modules/<module_name>/ for cross-module imports.

    `arch` defaults to the real project architecture; pass an explicit one in
    tests. When no architecture can be loaded the scanner falls back to the
    strict rule (no cross-module import is ever allowed).

    `strict_missing` promotes the "no source tree yet" finding to ERROR. By
    default it is INFO, because an unimplemented module is a normal state,
    not a boundary violation.
    """
    if arch is None:
        arch = _load_architecture()
    src = modules_root / module_name
    if not src.exists():
        return [
            Finding(
                code="MODULE_NOT_FOUND",
                severity="ERROR" if strict_missing else "INFO",
                module=module_name,
                file=str(src),
                line=0,
                spec="",
                message=(
                    f"no source tree at {src}; nothing to scan "
                    f"(use --strict to treat this as an error)"
                ),
            )
        ]
    out: list[Finding] = []
    for py in sorted(src.rglob("*.py")):
        try:
            rel = str(py.resolve().relative_to(Path.cwd().resolve()))
        except ValueError:
            rel = str(py)
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            out.append(
                Finding(
                    code="SYNTAX_ERROR",
                    severity="ERROR",
                    module=module_name,
                    file=rel,
                    line=exc.lineno or 0,
                    spec="",
                    message=f"cannot parse: {exc.msg}",
                )
            )
            continue
        for spec, lineno in _imports_in(tree):
            kind, owner = _resolve_owner(spec, module_name, arch)
            if kind == "modules-other":
                if _is_readable(arch, module_name, owner, spec):
                    continue
                code, message = _cross_module_finding(
                    module_name, owner, spec, arch
                )
                out.append(
                    Finding(
                        code=code,
                        severity="ERROR",
                        module=module_name,
                        file=rel,
                        line=lineno,
                        spec=spec,
                        message=message,
                    )
                )
            elif kind == "modules-unknown":
                out.append(
                    Finding(
                        code="BOUNDARY_VIOLATION",
                        severity="ERROR",
                        module=module_name,
                        file=rel,
                        line=lineno,
                        spec=spec,
                        message=(
                            f"`{spec}` resolves to no module declared in "
                            f"architecture/modules; declare it or route through a contract"
                        ),
                    )
                )
            elif kind == "legacy":
                out.append(
                    Finding(
                        code="LEGACY_LEAK",
                        severity="ERROR",
                        module=module_name,
                        file=rel,
                        line=lineno,
                        spec=spec,
                        message=(
                            f"legacy project package `{owner}` is forbidden in the new "
                            f"framework; port the symbol into modules/ first"
                        ),
                    )
                )
            elif kind == "framework-public":
                # check for private subpath
                if any(p.startswith("_") for p in spec.split(".")[2:]):
                    out.append(
                        Finding(
                            code="INTERNAL_LEAK",
                            severity="ERROR",
                            module=module_name,
                            file=rel,
                            line=lineno,
                            spec=spec,
                            message=(
                                f"private framework path: use framework.architecture "
                                f"public API only, not `{spec}`"
                            ),
                        )
                    )
    return out


def scan_repo(
    modules_root: Path = Path("modules"),
    arch: Architecture | None = None,
    strict_missing: bool = False,
) -> list[Finding]:
    """Scan every module under modules/."""
    if arch is None:
        arch = _load_architecture()
    if not modules_root.exists():
        return [
            Finding(
                code="NO_MODULES_TREE",
                severity="ERROR" if strict_missing else "INFO",
                module="(repo)",
                file=str(modules_root),
                line=0,
                spec="",
                message=(
                    f"no source tree at {modules_root}; every module is still "
                    f"unimplemented (use --strict to treat this as an error)"
                ),
            )
        ]
    out: list[Finding] = []
    declared = arch.modules if arch is not None else {}
    for entry in sorted(modules_root.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        # An implementation directory exists but no module.yaml declares it:
        # it would sit outside the architecture entirely.
        if name not in declared:
            out.append(
                Finding(
                    code="MODULE_UNDECLARED",
                    severity="ERROR" if strict_missing else "INFO",
                    module=name,
                    file=str(entry),
                    line=0,
                    spec="",
                    message=(
                        f"`{entry}` has no architecture/modules/{name}/module.yaml; "
                        f"declare it with ac-designer before implementing it"
                    ),
                )
            )
            continue
        out.extend(
            scan_module(name, modules_root, arch=arch, strict_missing=strict_missing)
        )
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m tools.check_imports")
    p.add_argument("module", nargs="?", help="module name to scan (default: scan every module)")
    p.add_argument("--modules-root", default="modules", help="root of modules/ tree")
    p.add_argument(
        "--strict",
        action="store_true",
        help="treat missing / undeclared sources as errors instead of notes",
    )
    p.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.modules_root)
    if args.module:
        findings = scan_module(args.module, root, strict_missing=args.strict)
    else:
        findings = scan_repo(root, strict_missing=args.strict)
    if args.json:
        import json

        json.dump(
            [
                {
                    "code": f.code,
                    "severity": f.severity,
                    "module": f.module,
                    "file": f.file,
                    "line": f.line,
                    "spec": f.spec,
                    "message": f.message,
                }
                for f in findings
            ],
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        sys.stdout.write("\n")
    else:
        for f in findings:
            print(f.format())
    has_error = any(f.severity == "ERROR" for f in findings)
    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
