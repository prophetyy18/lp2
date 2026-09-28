"""Stable query API.

One entry point per acceptance question. A future workflow calls these and
never touches the internals; the CLI is a thin shell over the same functions.

    1. what may this module read?      -> readable()
    2. what may this module depend on? -> dependencies()
    3. who is affected by this change? -> blast_radius()

All three return plain dicts/lists so they can be serialised to JSON or mapped
onto a future workflow's vocabulary without this package changing.
"""

from __future__ import annotations

from typing import Any

from . import boundary, graph, impact
from .errors import CONTRACT_INSUFFICIENT, ILLEGAL_DEPENDENCY, UNKNOWN_CONTRACT, ArchError
from .model import Architecture
from .snapshot import diff as diff_snapshots
from .snapshot import read as read_snapshot
from .validator import has_errors, validate


def readable(arch: Architecture, module: str) -> dict[str, Any]:
    """Q1: which paths may this module read?"""
    mod = arch.module(module)
    rules = boundary.readable_rules(mod)
    return {
        "module": mod.name,
        "allowed": [{"glob": r.glob, "reason": r.reason} for r in rules],
        "denied": _denied_summary(arch, mod),
    }


def _denied_summary(arch: Architecture, mod) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for other in sorted(arch.modules.values(), key=lambda m: m.name):
        if other.name == mod.name:
            continue
        out.append({"path": f"{other.path}/**", "reason": "another module's implementation"})
    return out


def check_paths(arch: Architecture, module: str, paths: list[str]) -> list[dict[str, Any]]:
    """Q1 applied to concrete paths. Readable paths produce no findings."""
    mod = arch.module(module)
    return [f.to_dict() for f in boundary.check_read_many(mod, paths, arch)]


def dependencies(arch: Architecture, module: str) -> dict[str, Any]:
    """Q2: which contracts may this module depend on, and does it have enough?"""
    mod = arch.module(module)
    entries: list[dict[str, Any]] = []
    for dep in mod.depends_on:
        contract = arch.contracts.get(dep.contract)
        available = list(contract.capability_ids()) if contract else []
        missing = [u for u in dep.uses if u not in available]
        entries.append(
            {
                "contract": dep.contract,
                "publisher": next((o.name for o in graph.owners(arch, dep.contract)), None),
                "uses": list(dep.uses),
                "available": available,
                "satisfied": not missing,
                "missing_capabilities": missing,
                "reason": dep.reason,
            }
        )

    findings = [
        f
        for f in validate(arch)
        if f.context.get("module") == mod.name
        and f.code in (CONTRACT_INSUFFICIENT, ILLEGAL_DEPENDENCY)
    ]

    return {
        "module": mod.name,
        "publishes": sorted(mod.owns_contracts),
        "depends_on": entries,
        "depends_on_modules": {
            name: sorted(targets)
            for name, targets in sorted(graph.direct_module_edges(arch).items())
            if name == mod.name
        },
        "blockers": [f.to_dict() for f in findings if has_errors([f])],
    }


def consumers_of(arch: Architecture, contract: str) -> dict[str, Any]:
    """Reverse dependency query: who depends on this contract?"""
    arch.contract(contract)
    direct = graph.consumers(arch, contract)
    return {
        "contract": contract,
        "published_by": [m.name for m in graph.owners(arch, contract)],
        "direct_consumers": [
            {"module": m.name, "uses": list(m.dependency_on(contract).uses)} for m in direct
        ],
        "indirect_consumers": graph.transitive_module_consumers(arch, contract),
        "indirect_contracts": [
            {"contract": c, "distance": d} for c, d in graph.reverse_contracts(arch, contract)
        ],
    }


def blast_radius(
    arch: Architecture, subject: str, capabilities: list[str] | None = None
) -> dict[str, Any]:
    """Q3: who is affected if this contract/module changes?"""
    if subject in arch.contracts:
        return impact.impact_of_contract(arch, subject, capabilities).to_dict()
    if subject in arch.modules:
        if capabilities:
            raise ArchError(
                "INVALID_METADATA",
                "capability filters only apply to a contract subject, not a module",
            )
        return impact.impact_of_module(arch, subject).to_dict()
    raise ArchError(
        UNKNOWN_CONTRACT,
        f"`{subject}` is neither a known contract nor a known module",
    )


def impact_of_diff(arch: Architecture, snapshot_path: str) -> dict[str, Any]:
    """Q3 applied to real edits: diff against a snapshot, then analyse."""
    delta = diff_snapshots(read_snapshot(snapshot_path), arch.to_dict())
    reports: list[dict[str, Any]] = []
    for name in delta.changed_contract_names():
        if name not in arch.contracts:
            continue
        reports.append(impact.impact_of_contract(arch, name).to_dict())
    affected = sorted({m for rep in reports for m in rep["affected_modules"]})
    return {
        "snapshot": snapshot_path,
        "diff": delta.to_dict(),
        "impact": reports,
        "affected_modules": affected,
        "breaking": any(d.breaking() for d in delta.contracts),
    }


def validation_report(arch: Architecture) -> dict[str, Any]:
    findings = validate(arch)
    return {
        "ok": not has_errors(findings),
        "findings": [f.to_dict() for f in findings],
        "codes": sorted({f.code for f in findings}),
    }
