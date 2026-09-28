"""Write-scope audit for one module.

Read scope is declared in the role prompts (`docs`, layer 1 of the isolation
stack) and cannot be mechanically enforced: this environment does not
register per-role subagents, so a subagent runs with the ambient tool
permissions. What *can* be enforced, and is what actually breaks isolation,
is **write** scope: which files a run was allowed to change.

This CLI compares the working tree against the module's allowed write roots:

    modules/<module>/**                  its own implementation (from module.yaml `source`)
    docs/implement/<module>/**           its own cards, manifests, records
    tests/test_<module>_<capability>*.py its own tests, for this capability only
                                        (hyphens and dots become underscores;
                                         see tools/implement/naming.py)

Anything else that is modified, added, or staged is a SCOPE_VIOLATION. Note
what is deliberately NOT allowed: a declared upstream's granted public
surface is readable, but never writable. Granting `modules/<upstream>/api/**`
is a read grant, not a hand-over of the files.

The audit is honest about its limits: it sees the file set a run left
behind, not what it read. It is a backstop on top of the declared read
scope, not a substitute for it.

Usage:
    ./bin/python -m tools.implement.scope <module> [--capability <cap>]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from framework.architecture import Architecture, load as load_arch

from tools.implement import naming

SEVERITY_ERROR = "ERROR"
SEVERITY_INFO = "INFO"


@dataclass(frozen=True)
class ScopeFinding:
    code: str
    severity: str
    module: str
    path: str
    message: str

    def format(self) -> str:
        return f"[{self.severity}] {self.code}: {self.module}: {self.path} -- {self.message}"


def _git(repo: Path, *args: str) -> list[str]:
    out = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"git {' '.join(args)} failed")
    return [line for line in out.stdout.splitlines() if line.strip()]


def touched_files(repo: Path, base: str = "HEAD") -> list[tuple[str, str]]:
    """(path, how it was touched) for everything changed since `base`.

    The two sources are kept apart because they are not equally trustworthy.
    A tracked file that differs from `base` really was modified after that
    commit, so attributing it to the run is sound. An untracked file has no
    such anchor: git cannot say when it appeared, so *every* untracked file
    in the repository is attributed to the run whether this run created it
    or it predates the spawn. On a tree that was dirty when the developer
    was dispatched, that is the entire source of false positives — a real
    one, measured: the first end-to-end run of this audit reported 19
    violations, all of them the dispatcher's own uncommitted work, and none
    of them the developer's.
    """
    tracked = _git(repo, "diff", "--name-only", base)
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard")
    out = [(p.strip(), "modified") for p in tracked if p.strip()]
    seen = {p for p, _ in out}
    out += [(p.strip(), "untracked") for p in untracked if p.strip() and p.strip() not in seen]
    return sorted(out)


def allowed_roots(
    module: str,
    capability: str | None,
    arch: Architecture | None,
) -> list[tuple[str, str]]:
    """(prefix, why) pairs this module may write under."""
    own = f"modules/{module}"
    if arch is not None:
        declared = arch.modules.get(module)
        if declared is not None:
            own = declared.path.rstrip("/")
    roots = [
        (own + "/", "own module implementation"),
        (f"docs/implement/{module}/", "own capability cards and records"),
    ]
    if capability:
        # Not `tests/test_{module}_{capability}`: module names are hyphenated
        # and capability ids are dotted, so that string names a file nobody
        # can write and the developer's own test read as a violation. Both
        # sides are translated in one place, which is the only reason the
        # audit and the role prompts can be expected to agree.
        roots.append(
            (
                naming.test_path_prefix(module, capability),
                "own tests for this capability",
            )
        )
    return roots


def audit(
    module: str,
    capability: str | None = None,
    repo: Path | None = None,
    arch: Architecture | None = None,
    base: str = "HEAD",
) -> list[ScopeFinding]:
    repo = repo or Path.cwd()
    if arch is None:
        arch = load_arch(repo)
    roots = allowed_roots(module, capability, arch)
    out: list[ScopeFinding] = []
    for path, how in touched_files(repo, base):
        hit = next((why for prefix, why in roots if path.startswith(prefix)), None)
        if hit is None:
            out.append(
                ScopeFinding(
                    code="SCOPE_VIOLATION",
                    severity=SEVERITY_ERROR,
                    module=module,
                    path=path,
                    message=(
                        f"`{module}` may not write `{path}` ({how}). Allowed: "
                        + "; ".join(f"{p}" for p, _ in roots)
                        + ". A declared upstream's public surface is readable, "
                        "never writable."
                        + (
                            "  NOTE: an untracked file is attributed to this "
                            "run without evidence — it only holds if the tree "
                            "was clean when the run was spawned."
                            if how == "untracked"
                            else ""
                        )
                    ),
                )
            )
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="./bin/python -m tools.implement.scope")
    p.add_argument("module")
    p.add_argument(
        "--capability",
        default="",
        help="narrow the test allow-list to this capability",
    )
    p.add_argument(
        "--base",
        default="HEAD",
        help="commit the run started from (default HEAD; record it before spawning)",
    )
    p.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        findings = audit(args.module, args.capability or None, base=args.base)
    except RuntimeError as exc:
        print(f"SCOPE_ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        import json

        json.dump(
            [
                {
                    "code": f.code,
                    "severity": f.severity,
                    "module": f.module,
                    "path": f.path,
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
        if not findings:
            print(f"[OK] {args.module}: write scope clean")
        for f in findings:
            print(f.format())
    return 1 if any(f.severity == SEVERITY_ERROR for f in findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
