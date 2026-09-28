"""Capability state machine.

Reads and writes `docs/implement/<module>/STATE.yaml`. Validates every
transition against the closed state set. Computes the aggregated
`module_state` from per-capability states.

State transition table (mechanical, enforced here):

    from \\ to          pending  mvp_developed  fully_approved  changes_requested  abandoned
    pending              -          yes             yes             yes              yes
    mvp_developed        -            -             yes             yes              yes
    fully_approved     yes            -               -             yes              yes
    changes_requested  yes            -               -               -              yes
    abandoned            -            -               -               -                -

Yes = the `mark-*` / `promote` / `abandon` subcommands accept the
transition. The dispatcher (not this CLI) is responsible for firing the
right command at the right moment; this module records what happened.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

import yaml

from tools.implement.errors import StateError

STATE_ROOT = Path("docs/implement")

VALID_STATES: tuple[str, ...] = (
    "pending",
    "mvp_developed",
    "fully_approved",
    "changes_requested",
    "abandoned",
)

# Allowed transitions (from -> set of allowed to-states).
_ALLOWED: dict[str, frozenset[str]] = {
    "pending": frozenset({"mvp_developed", "fully_approved", "changes_requested", "abandoned"}),
    "mvp_developed": frozenset({"fully_approved", "changes_requested", "abandoned"}),
    "fully_approved": frozenset({"changes_requested", "abandoned"}),
    "changes_requested": frozenset({"pending", "abandoned"}),
    "abandoned": frozenset(),
}

# Mode rules per transition. ``None`` means the command does not constrain mode.
_MODE_RULES: dict[str, str | None] = {
    "mark_mvp": "mvp",
    "mark_changes": None,
    "mark_approved": None,
    "promote": "full",
    "abandon": None,
}


class CapabilityState(str, Enum):
    PENDING = "pending"
    MVP_DEVELOPED = "mvp_developed"
    FULLY_APPROVED = "fully_approved"
    CHANGES_REQUESTED = "changes_requested"
    ABANDONED = "abandoned"


class ModuleState(str, Enum):
    PLANNED = "planned"
    PARTIAL_MVP = "partial_mvp"
    PARTIALLY_COMPLETE = "partially_complete"
    COMPLETE = "complete"
    ABANDONED = "abandoned"


@dataclass
class CapabilityRecord:
    state: str = "pending"
    mode: str = "full"  # mvp | full
    mvp_at: str = ""
    approved_at: str = ""
    reviewer_run: str = ""
    manifest: str = ""
    review: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"state": self.state, "mode": self.mode}
        if self.mvp_at:
            out["mvp_at"] = self.mvp_at
        if self.approved_at:
            out["approved_at"] = self.approved_at
        if self.reviewer_run:
            out["reviewer_run"] = self.reviewer_run
        if self.manifest:
            out["manifest"] = self.manifest
        if self.review:
            out["review"] = self.review
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilityRecord":
        return cls(
            state=str(data.get("state", "pending")),
            mode=str(data.get("mode", "full")),
            mvp_at=str(data.get("mvp_at", "")),
            approved_at=str(data.get("approved_at", "")),
            reviewer_run=str(data.get("reviewer_run", "")),
            manifest=str(data.get("manifest", "")),
            review=str(data.get("review", "")),
        )


@dataclass
class ModuleRecord:
    name: str
    capabilities: dict[str, CapabilityRecord] = field(default_factory=dict)
    module_state: str = "planned"

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.name,
            "module_state": self.module_state,
            "capabilities": {
                cid: rec.to_dict() for cid, rec in sorted(self.capabilities.items())
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModuleRecord":
        name = str(data.get("module", ""))
        caps_raw = data.get("capabilities", {}) or {}
        if not isinstance(caps_raw, dict):
            raise StateError(f"STATE.yaml: capabilities must be a mapping, got {type(caps_raw).__name__}")
        caps = {str(cid): CapabilityRecord.from_dict(v) for cid, v in caps_raw.items()}
        mod = cls(name=name, capabilities=caps)
        mod.module_state = compute_module_state(caps.values())
        return mod


def load_state(module: str, root: Path | None = None) -> ModuleRecord:
    """Load a module's STATE.yaml. If the file does not exist, return a fresh
    ModuleRecord with no capabilities (caller may add entries)."""
    if root is None:
        root = STATE_ROOT
    path = root / module / "STATE.yaml"
    if not path.exists():
        return ModuleRecord(name=module)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise StateError(f"{path}: cannot parse YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise StateError(f"{path}: top level must be a mapping")
    return ModuleRecord.from_dict(data)


def save_state(record: ModuleRecord, root: Path | None = None) -> Path:
    if root is None:
        root = STATE_ROOT
    record.module_state = compute_module_state(record.capabilities.values())
    path = root / record.name / "STATE.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(record.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def compute_module_state(records: Iterable[CapabilityRecord]) -> str:
    """Aggregate capability states into one module_state string."""
    states = {r.state for r in records}
    if not states:
        return ModuleState.PLANNED.value
    if states == {CapabilityState.PENDING.value}:
        return ModuleState.PLANNED.value
    if states == {CapabilityState.ABANDONED.value}:
        return ModuleState.ABANDONED.value
    if states == {CapabilityState.FULLY_APPROVED.value}:
        return ModuleState.COMPLETE.value
    if CapabilityState.FULLY_APPROVED.value in states and CapabilityState.ABANDONED.value not in states:
        # some approved, none abandoned, but others still in flight
        if all(
            s in (CapabilityState.FULLY_APPROVED.value, CapabilityState.ABANDONED.value)
            for s in states
        ):
            return ModuleState.COMPLETE.value
        return ModuleState.PARTIALLY_COMPLETE.value
    if CapabilityState.MVP_DEVELOPED.value in states and CapabilityState.FULLY_APPROVED.value not in states:
        return ModuleState.PARTIAL_MVP.value
    if CapabilityState.FULLY_APPROVED.value in states:
        return ModuleState.PARTIALLY_COMPLETE.value
    return ModuleState.PARTIAL_MVP.value


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _validate_transition(from_state: str, to_state: str) -> None:
    if from_state not in VALID_STATES:
        raise StateError(f"unknown from-state {from_state!r}")
    if to_state not in VALID_STATES:
        raise StateError(f"unknown to-state {to_state!r}")
    if to_state not in _ALLOWED[from_state]:
        raise StateError(
            f"transition {from_state!r} -> {to_state!r} is not allowed; "
            f"allowed targets from {from_state!r}: "
            f"{sorted(_ALLOWED[from_state]) or '(terminal)'}"
        )


def _get_cap(record: ModuleRecord, cap: str) -> CapabilityRecord:
    if cap not in record.capabilities:
        raise StateError(
            f"capability {cap!r} is not declared for module {record.name!r}; "
            f"add it to the module's contract first"
        )
    return record.capabilities[cap]


# --- CLI subcommands -------------------------------------------------------


def cmd_mark_mvp(args: argparse.Namespace) -> int:
    record = load_state(args.module)
    rec = _get_cap(record, args.capability)
    _validate_transition(rec.state, "mvp_developed")
    # Mode is set at planning time on the capability record; do not let
    # a developer promote a full-scoped capability through the MVP gate.
    # If the capability was planned as mode=full, the reviewer path must
    # be used (mark-approved directly, never mark-mvp).
    if rec.mode != "mvp":
        raise StateError(
            f"mark-mvp requires mode=mvp on the record, got mode={rec.mode!r}; "
            f"either re-plan this capability as mode=mvp, or use mark-approved "
            f"for the full path"
        )
    rec.state = "mvp_developed"
    rec.mode = "mvp"
    rec.mvp_at = _now_iso()
    if args.manifest:
        rec.manifest = args.manifest
    save_state(record)
    _print(f"marked {args.module}/{args.capability} as mvp_developed (mode=mvp)")
    return 0


def cmd_mark_changes(args: argparse.Namespace) -> int:
    record = load_state(args.module)
    rec = _get_cap(record, args.capability)
    _validate_transition(rec.state, "changes_requested")
    rec.state = "changes_requested"
    save_state(record)
    _print(f"marked {args.module}/{args.capability} as changes_requested")
    return 0


def cmd_mark_approved(args: argparse.Namespace) -> int:
    record = load_state(args.module)
    rec = _get_cap(record, args.capability)
    _validate_transition(rec.state, "fully_approved")
    rec.state = "fully_approved"
    rec.approved_at = _now_iso()
    if args.reviewer_run:
        rec.reviewer_run = args.reviewer_run
    if args.review:
        rec.review = args.review
    save_state(record)
    _print(f"marked {args.module}/{args.capability} as fully_approved")
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    """Owner-triggered: flip mode from mvp to full and re-dispatch reviewer.

    Records a pending transition by setting mode=full and state back to
    pending, expecting the reviewer path (mark-approved) to land next.
    This CLI does not invoke the reviewer itself; the dispatcher does.
    """
    record = load_state(args.module)
    rec = _get_cap(record, args.capability)
    if rec.state != "mvp_developed":
        raise StateError(
            f"promote requires state=mvp_developed, got state={rec.state!r}"
        )
    if rec.mode != "mvp":
        raise StateError(
            f"promote requires mode=mvp, got mode={rec.mode!r}"
        )
    rec.mode = "full"
    rec.state = "pending"  # reviewer will mark-approved next
    save_state(record)
    _print(
        f"promoted {args.module}/{args.capability}: mode mvp -> full, "
        f"state reset to pending awaiting reviewer"
    )
    return 0


def cmd_abandon(args: argparse.Namespace) -> int:
    record = load_state(args.module)
    rec = _get_cap(record, args.capability)
    _validate_transition(rec.state, "abandoned")
    rec.state = "abandoned"
    save_state(record)
    _print(f"abandoned {args.module}/{args.capability}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    record = load_state(args.module)
    if args.capability:
        rec = record.capabilities.get(args.capability)
        if rec is None:
            raise StateError(
                f"capability {args.capability!r} not declared for {args.module!r}"
            )
        yaml.safe_dump({args.capability: rec.to_dict()}, sys.stdout, sort_keys=False)
    else:
        yaml.safe_dump(record.to_dict(), sys.stdout, sort_keys=False)
    return 0


def cmd_dependers_of(args: argparse.Namespace) -> int:
    """List modules whose STATE declares an upstream dependency on this capability.

    NOTE: cross-module dependency declarations live in
    architecture/modules/<M>/module.yaml, not STATE.yaml. This subcommand
    scans STATE files only as a quick check that no downstream module
    is currently building on a capability that is not yet fully_approved.
    The dispatcher uses the framework's graph + STATE to combine both
    views before launching developer.
    """
    target_module, _, target_cap = args.capability.partition(".")
    root = Path(args.root) if args.root else STATE_ROOT
    hits: list[str] = []
    for state_path in root.glob("*/STATE.yaml"):
        rec = load_state(state_path.parent.name, root)
        if args.capability in rec.capabilities:
            hits.append(state_path.parent.name)
    yaml.safe_dump(
        {
            "capability": args.capability,
            "owning_module": target_module or "(unknown)",
            "registered_in": hits,
        },
        sys.stdout,
        sort_keys=False,
    )
    return 0


def _print(msg: str) -> None:
    print(msg, file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m tools.implement.state")
    p.add_argument(
        "--root",
        default=str(STATE_ROOT),
        help=f"STATE root (default: {STATE_ROOT})",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def module_cap(p: argparse.ArgumentParser) -> None:
        p.add_argument("module")
        p.add_argument("capability")

    sp = sub.add_parser("mark-mvp", help="developer marks MVP done (pending|mvp_developed)")
    module_cap(sp)
    sp.add_argument("--manifest", default="")
    sp.add_argument("--mode", default="")

    sp = sub.add_parser("mark-changes", help="reviewer rejects; developer iterates")
    module_cap(sp)

    sp = sub.add_parser(
        "mark-approved", help="reviewer approves (reviewer must call this)"
    )
    module_cap(sp)
    sp.add_argument("--reviewer-run", default="")
    sp.add_argument("--review", default="")

    sp = sub.add_parser("promote", help="owner promotes mvp -> full")
    module_cap(sp)

    sp = sub.add_parser("abandon", help="owner closes a capability")
    module_cap(sp)

    sp = sub.add_parser("show", help="print state for module or capability")
    sp.add_argument("module")
    sp.add_argument("capability", nargs="?")

    sp = sub.add_parser(
        "dependers-of",
        help="list modules that have this capability in their STATE",
    )
    sp.add_argument("capability")

    return p


_HANDLERS = {
    "mark-mvp": cmd_mark_mvp,
    "mark-changes": cmd_mark_changes,
    "mark-approved": cmd_mark_approved,
    "promote": cmd_promote,
    "abandon": cmd_abandon,
    "show": cmd_show,
    "dependers-of": cmd_dependers_of,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _HANDLERS.get(args.command)
    if handler is None:
        parser.error(f"unknown command {args.command!r}")
    try:
        return handler(args)
    except StateError as exc:
        print(f"STATE_ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())