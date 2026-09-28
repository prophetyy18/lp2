"""Capability state machine.

Reads and writes `docs/implement/<module>/STATE.yaml`. Validates every
transition against the closed state set. Computes the aggregated
`module_state` from per-capability states.

Capabilities start at pending via register. mark-mvp accepts a pending MVP;
mark-approved accepts a full capability with an APPROVED Review Record.
`pending` means exactly one thing — a developer owes work on it. Both the
first registration and a reopened pass land there, and nothing else does.

An MVP is never promoted in place. `mvp_developed` is not usable by any
other module; a capability becomes consumable only through
`fully_approved`. If an MVP later turns out to be needed for real, Owner
reopens it with `retry --mode full` and the developer finishes it through
the normal reviewed path. abandoned is terminal.

The dispatcher is responsible for Owner gates; this CLI records their
outcome.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
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
#
# `mvp_developed` can only be reopened as pending (a full-mode redo) or
# abandoned. There is deliberately no edge to `fully_approved`: an MVP is
# not consumable by another module and does not become so in place.
_ALLOWED: dict[str, frozenset[str]] = {
    "pending": frozenset({"mvp_developed", "fully_approved", "changes_requested", "abandoned"}),
    "mvp_developed": frozenset({"pending", "abandoned"}),
    "fully_approved": frozenset({"changes_requested", "abandoned"}),
    "changes_requested": frozenset({"pending", "abandoned"}),
    "abandoned": frozenset(),
}

# Mode rules per transition. ``None`` means the command does not constrain mode.
_MODE_RULES: dict[str, str | None] = {
    "mark_mvp": "mvp",
    "mark_changes": None,
    "mark_approved": None,
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


def _require_artifact(
    module: str,
    capability: str,
    root: Path,
    kind: str,          # "manifest" | "review"
    given: str,
    header: str,
    required_block: str = "",
) -> str:
    """Validate a gate artifact and return its text.

    An MVP is only worth recording if it produced something. Both gate
    artifacts must exist at the canonical path, carry the header that ties
    them to this capability, and — for a Manifest — actually contain the
    discovery record that the full-mode handoff depends on.
    """
    if not given:
        raise StateError(
            f"mark-{'mvp' if kind == 'manifest' else 'approved'} requires "
            f"--{kind} with the {kind} for {module} / {capability}"
        )
    path = Path(given)
    expected = root / module / f"{capability}.{kind}.md"
    if path.resolve() != expected.resolve() or not path.is_file():
        raise StateError(f"{kind} must be the existing {kind} at {expected}")
    content = path.read_text(encoding="utf-8")
    if header not in content.splitlines():
        raise StateError(f"{kind} header must be {header!r}")
    if required_block and required_block not in content:
        raise StateError(
            f"{kind} must contain a {required_block!r} section: an MVP is the "
            f"foreword to the full implementation, and the discovery it records "
            f"(question / answer / surprised / keep / discard / known_gaps) is "
            f"what the full run inherits"
        )
    return content


# --- CLI subcommands -------------------------------------------------------


def cmd_register(args: argparse.Namespace) -> int:
    """Create a pending record for a capability owned by this module."""
    module_path = Path("architecture/modules") / args.module / "module.yaml"
    if not module_path.is_file():
        raise StateError(f"module declaration not found: {module_path}")
    module_data = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
    contract_names = module_data.get("provides_contracts", [])
    declared: set[str] = set()
    for name in contract_names:
        contract_path = Path("architecture/contracts") / f"{name}.yaml"
        if not contract_path.is_file():
            raise StateError(f"contract not found: {contract_path}")
        contract_data = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
        declared.update(cap["id"] for cap in contract_data.get("provides", []))
    if args.capability not in declared:
        raise StateError(
            f"capability {args.capability!r} is not provided by module {args.module!r}"
        )

    root = Path(args.root)
    record = load_state(args.module, root)
    if args.capability in record.capabilities:
        raise StateError(f"capability {args.capability!r} is already registered")
    record.capabilities[args.capability] = CapabilityRecord(mode=args.mode)
    save_state(record, root)
    _print(f"registered {args.module}/{args.capability} as pending (mode={args.mode})")
    return 0


def cmd_mark_mvp(args: argparse.Namespace) -> int:
    record = load_state(args.module, Path(args.root))
    rec = _get_cap(record, args.capability)
    _validate_transition(rec.state, "mvp_developed")
    # Mode is set at planning time on the capability record. A capability
    # planned as mode=full must take the reviewed path (mark-approved), so a
    # full-scoped capability cannot slip through the MVP gate, which does no
    # review and produces something no other module may consume.
    if rec.mode != "mvp":
        raise StateError(
            f"mark-mvp requires mode=mvp on the record, got mode={rec.mode!r}; "
            f"either re-plan this capability as mode=mvp, or use mark-approved "
            f"for the full path"
        )
    _require_artifact(
        args.module,
        args.capability,
        Path(args.root),
        "manifest",
        args.manifest,
        f"# manifest: {args.module} / {args.capability}",
        required_block="## discovery",
    )
    rec.state = "mvp_developed"
    rec.mode = "mvp"
    rec.mvp_at = _now_iso()
    rec.manifest = args.manifest
    save_state(record, Path(args.root))
    _print(
        f"marked {args.module}/{args.capability} as mvp_developed (mode=mvp); "
        f"not consumable by other modules. Its discovery section is what a "
        f"later `retry --mode full` inherits."
    )
    return 0


def cmd_mark_changes(args: argparse.Namespace) -> int:
    record = load_state(args.module, Path(args.root))
    rec = _get_cap(record, args.capability)
    _validate_transition(rec.state, "changes_requested")
    rec.state = "changes_requested"
    save_state(record, Path(args.root))
    _print(f"marked {args.module}/{args.capability} as changes_requested")
    return 0


def cmd_retry(args: argparse.Namespace) -> int:
    """Reopen a capability for another developer pass.

    Valid from two states, both of which mean "a developer owes work":

      changes_requested  the reviewer rejected it; fix and resubmit
      mvp_developed      an MVP turned out to be needed for real

    Reopening from `mvp_developed` requires `--mode full`: that is how an
    Owner turns a prototype into something another module may consume. The
    existing source and tests stay; the capability simply has to earn an
    APPROVED review like any other.
    """
    record = load_state(args.module, Path(args.root))
    rec = _get_cap(record, args.capability)
    _validate_transition(rec.state, "pending")
    if rec.state == "mvp_developed":
        if args.mode != "full":
            raise StateError(
                f"reopening {args.module}/{args.capability} from mvp_developed "
                f"requires --mode full; an MVP cannot be promoted in place, and "
                f"only mode=full work can reach fully_approved"
            )
        rec.mode = "full"
    rec.state = "pending"
    save_state(record, Path(args.root))
    _print(
        f"reopened {args.module}/{args.capability} as pending "
        f"(mode={rec.mode}); it is not consumable by other modules until "
        f"fully_approved"
    )
    return 0


def cmd_mark_approved(args: argparse.Namespace) -> int:
    record = load_state(args.module, Path(args.root))
    rec = _get_cap(record, args.capability)
    _validate_transition(rec.state, "fully_approved")
    if rec.mode != "full":
        raise StateError(
            "mark-approved requires mode=full; reopen an MVP with "
            "`retry --mode full` and take it through the reviewed path"
        )
    content = _require_artifact(
        args.module,
        args.capability,
        Path(args.root),
        "review",
        args.review,
        f"# review: {args.module} / {args.capability}",
    )
    verdicts = re.findall(r"^- verdict:\s*(\S+)\s*$", content, re.MULTILINE)
    if verdicts != ["APPROVED"]:
        raise StateError("review must have exactly one APPROVED verdict")
    for score in ("contract_conformance", "boundary", "test_coverage", "implementation_quality"):
        values = re.findall(rf"^\s*{score}:\s*(\S+)", content, re.MULTILINE)
        if values != ["OK"]:
            raise StateError(f"review score {score} must be exactly one OK")
    rec.state = "fully_approved"
    rec.approved_at = _now_iso()
    if args.reviewer_run:
        rec.reviewer_run = args.reviewer_run
    rec.review = str(Path(args.review))
    save_state(record, Path(args.root))
    _print(f"marked {args.module}/{args.capability} as fully_approved")
    return 0


def cmd_abandon(args: argparse.Namespace) -> int:
    record = load_state(args.module, Path(args.root))
    rec = _get_cap(record, args.capability)
    _validate_transition(rec.state, "abandoned")
    rec.state = "abandoned"
    save_state(record, Path(args.root))
    _print(f"abandoned {args.module}/{args.capability}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    record = load_state(args.module, Path(args.root))
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

    sp = sub.add_parser("register", help="register a declared capability as pending")
    module_cap(sp)
    sp.add_argument("--mode", choices=("mvp", "full"), default="full")

    sp = sub.add_parser("mark-mvp", help="record Owner acceptance of an MVP")
    module_cap(sp)
    sp.add_argument("--manifest", default="")

    sp = sub.add_parser("mark-changes", help="reviewer rejects; developer iterates")
    module_cap(sp)

    sp = sub.add_parser(
        "retry",
        help="reopen changes_requested, or an MVP with --mode full",
    )
    module_cap(sp)
    sp.add_argument(
        "--mode",
        choices=("full",),
        default="",
        help="required when reopening an mvp_developed capability",
    )

    sp = sub.add_parser(
        "mark-approved", help="record Owner approval of an APPROVED review"
    )
    module_cap(sp)
    sp.add_argument("--reviewer-run", default="")
    sp.add_argument("--review", default="")

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
    "register": cmd_register,
    "mark-mvp": cmd_mark_mvp,
    "mark-changes": cmd_mark_changes,
    "retry": cmd_retry,
    "mark-approved": cmd_mark_approved,
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
