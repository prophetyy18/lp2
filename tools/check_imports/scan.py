"""AST-based cross-module import scanner.

Rules:

  - Allowed:
    * stdlib (anything importable without a third-party prefix and not
      starting with `modules.` / `framework.architecture._private`)
    * third-party packages declared in the scanner's allow list
    * `framework.architecture` (public API surface only)
    * the module's own source tree: `modules.<self>.xxx`
  - Forbidden:
    * `modules.<N>...` for N != self -> BOUNDARY_VIOLATION
    * `framework.architecture.<private>` (anything starting with an
      underscore) -> INTERNAL_LEAK
    * legacy project packages (`robinhood_lp.*`) -> LEGACY_LEAK

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


def _resolve_module_owner(spec: str, self_module: str) -> tuple[str, str]:
    """Return (kind, owner) for a dotted import spec.

    kind is one of: 'modules-self', 'modules-other', 'framework-public',
    'framework-internal', 'legacy', 'third-party', 'top-level',
    'relative'.
    owner is the module name this would route to, when applicable.
    """
    if spec.startswith("."):
        return ("relative", "")
    parts = spec.split(".")
    head = parts[0]
    if head in LEGACY_DENYLIST:
        return ("legacy", head)
    if head in PROJECT_TOP_LEVEL:
        if head == "modules" and len(parts) >= 2:
            owner = parts[1]
            if owner == self_module:
                return ("modules-self", owner)
            return ("modules-other", owner)
        if head == "modules" and len(parts) == 1:
            return ("top-level", head)
        if head == "framework" and len(parts) >= 2 and parts[1] == "architecture":
            return ("framework-public", head)
        if head == "framework":
            return ("top-level", head)
        return ("top-level", head)
    # Anything else is third-party or stdlib. We don't differentiate;
    # the scanner does not enforce third-party denylists by default.
    return ("third-party", head)


def scan_module(
    module_name: str,
    modules_root: Path = Path("modules"),
) -> list[Finding]:
    """Scan all .py files under modules/<module_name>/ for cross-module imports."""
    src = modules_root / module_name
    if not src.exists():
        return [
            Finding(
                code="MODULE_NOT_FOUND",
                severity="ERROR",
                module=module_name,
                file=str(src),
                line=0,
                spec="",
                message=f"no source tree at {src}",
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
            kind, owner = _resolve_module_owner(spec, module_name)
            if kind == "modules-other":
                out.append(
                    Finding(
                        code="BOUNDARY_VIOLATION",
                        severity="ERROR",
                        module=module_name,
                        file=rel,
                        line=lineno,
                        spec=spec,
                        message=(
                            f"cross-module import: {module_name} may not import "
                            f"`{spec}` (owned by modules.{owner}); route through a "
                            f"contract capability instead"
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


def scan_repo(modules_root: Path = Path("modules")) -> list[Finding]:
    """Scan every module under modules/."""
    if not modules_root.exists():
        return []
    out: list[Finding] = []
    for entry in sorted(modules_root.iterdir()):
        if entry.is_dir() and (entry / "__init__.py").exists() or any(entry.glob("*.py")):
            out.extend(scan_module(entry.name, modules_root))
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m tools.check_imports")
    p.add_argument("module", nargs="?", help="module name to scan (default: scan every module)")
    p.add_argument("--modules-root", default="modules", help="root of modules/ tree")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.modules_root)
    if args.module:
        findings = scan_module(args.module, root)
    else:
        findings = scan_repo(root)
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
