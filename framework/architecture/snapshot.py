"""Contract snapshots and diffing.

Impact analysis tells you "who is affected by contract X". It still needs
someone to notice that X actually changed. A snapshot is a normalised JSON dump
of the metadata; diffing two snapshots turns "the contract changed" into a
machine-readable set of changed capabilities, which impact analysis then maps to
affected modules.

    archctl snapshot --out architecture/.snapshots/baseline.json
    # ... edit contracts ...
    archctl diff architecture/.snapshots/baseline.json
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ArchError, INVALID_METADATA
from .model import Architecture

SNAPSHOT_DIR = "architecture/.snapshots"


def write(arch: Architecture, path: str | Path | None = None) -> Path:
    target = Path(path) if path else Path(arch.root) / SNAPSHOT_DIR / "baseline.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(arch.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return target


def read(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = Path.cwd() / p
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArchError(INVALID_METADATA, f"cannot read snapshot {p}: {exc}") from exc


@dataclass(frozen=True)
class CapabilityChange:
    """One capability whose machine-readable fields changed between snapshots.

    `field_changes` is the sorted tuple of fields that changed AND are part
    of the capability's behavior contract (signature / schema refs / errors /
    behavior tags). Renaming a description is intentionally NOT a breaking
    change and so never appears here.
    """

    id: str
    field_changes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "field_changes": list(self.field_changes)}


# Fields of a capability that, when changed, constitute a breaking change.
# Other fields (description, signature as a free-form string when no schema
# ref is given, version metadata) are non-breaking.
_BREAKING_CAPABILITY_FIELDS: tuple[str, ...] = (
    "kind",
    "input",
    "output",
    "payload",
    "errors",
    "behavior",
    "signature",
)


@dataclass(frozen=True)
class ContractDelta:
    contract: str
    kind: str  # added | removed | changed | version_bump
    added_capabilities: tuple[str, ...] = ()
    removed_capabilities: tuple[str, ...] = ()
    changed_capabilities: tuple[CapabilityChange, ...] = ()
    added_requires: tuple[str, ...] = ()
    removed_requires: tuple[str, ...] = ()
    version_from: int = 0
    version_to: int = 0

    def breaking(self) -> bool:
        if self.removed_capabilities or self.removed_requires:
            return True
        if any(c.field_changes for c in self.changed_capabilities):
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "kind": self.kind,
            "breaking": self.breaking(),
            "added_capabilities": list(self.added_capabilities),
            "removed_capabilities": list(self.removed_capabilities),
            "changed_capabilities": [c.to_dict() for c in self.changed_capabilities],
            "added_requires": list(self.added_requires),
            "removed_requires": list(self.removed_requires),
            "version_from": self.version_from,
            "version_to": self.version_to,
        }


@dataclass
class DiffResult:
    contracts: list[ContractDelta] = field(default_factory=list)
    module_edges_added: list[str] = field(default_factory=list)
    module_edges_removed: list[str] = field(default_factory=list)

    def changed_contract_names(self) -> list[str]:
        return [d.contract for d in self.contracts]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contracts": [d.to_dict() for d in self.contracts],
            "module_edges_added": self.module_edges_added,
            "module_edges_removed": self.module_edges_removed,
        }


def diff(old: dict[str, Any], new: dict[str, Any]) -> DiffResult:
    old_c = old.get("contracts", {}) or {}
    new_c = new.get("contracts", {}) or {}
    out = DiffResult()

    for name in sorted(set(old_c) | set(new_c)):
        before, after = old_c.get(name), new_c.get(name)
        if before is None:
            out.contracts.append(
                ContractDelta(contract=name, kind="added", version_to=after.get("version", 1))
            )
            continue
        if after is None:
            out.contracts.append(
                ContractDelta(
                    contract=name,
                    kind="removed",
                    removed_capabilities=tuple(
                        c["id"] for c in before.get("provides", [])
                    ),
                    version_from=before.get("version", 1),
                )
            )
            continue

        b_caps = {c["id"] for c in before.get("provides", [])}
        a_caps = {c["id"] for c in after.get("provides", [])}
        b_req, a_req = set(before.get("requires", [])), set(after.get("requires", []))
        v_b, v_a = before.get("version", 1), after.get("version", 1)

        if b_caps == a_caps and b_req == a_req and v_b == v_a:
            continue
        kind = "changed"
        if v_a != v_b and b_caps == a_caps and b_req == a_req:
            kind = "version_bump"

        # Detect capability-level field changes that are breaking.
        b_by_id = {c["id"]: c for c in before.get("provides", [])}
        a_by_id = {c["id"]: c for c in after.get("provides", [])}
        common_ids = b_caps & a_caps
        changed_caps: list[CapabilityChange] = []
        for cid in sorted(common_ids):
            before_cap = b_by_id[cid]
            after_cap = a_by_id[cid]
            field_changes = [
                f for f in _BREAKING_CAPABILITY_FIELDS if before_cap.get(f) != after_cap.get(f)
            ]
            if field_changes:
                changed_caps.append(
                    CapabilityChange(id=cid, field_changes=tuple(sorted(field_changes)))
                )

        out.contracts.append(
            ContractDelta(
                contract=name,
                kind=kind,
                added_capabilities=tuple(sorted(a_caps - b_caps)),
                removed_capabilities=tuple(sorted(b_caps - a_caps)),
                changed_capabilities=tuple(changed_caps),
                added_requires=tuple(sorted(a_req - b_req)),
                removed_requires=tuple(sorted(b_req - a_req)),
                version_from=v_b,
                version_to=v_a,
            )
        )

    out.module_edges_added, out.module_edges_removed = _edge_diff(old, new)
    return out


def _edges(snapshot: dict[str, Any]) -> set[str]:
    edges: set[str] = set()
    for mod_name, mod in (snapshot.get("modules", {}) or {}).items():
        for dep in mod.get("depends_on", []):
            edges.add(f"{mod_name} -> {dep['contract']}")
    return edges


def _edge_diff(old: dict[str, Any], new: dict[str, Any]) -> tuple[list[str], list[str]]:
    before, after = _edges(old), _edges(new)
    return sorted(after - before), sorted(before - after)
