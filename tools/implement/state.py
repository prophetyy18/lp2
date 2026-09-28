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

from framework.architecture import ArchError, Architecture
from framework.architecture import load as load_arch

from tools.implement.errors import StateError

STATE_ROOT = Path("docs/implement")

# Repo-relative root that architecture/, modules/ and tests/ hang off.
# Separate from STATE_ROOT because they are different trees, and a constant
# rather than an argument so the artifact checks stay pure w.r.t. the state.
REPO_ROOT = Path(".")

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
    REWORK = "rework"
    PARTIALLY_COMPLETE = "partially_complete"
    COMPLETE = "complete"
    ABANDONED = "abandoned"


@dataclass
class CapabilityRecord:
    state: str = "pending"
    mode: str = "full"  # mvp | full
    mvp_at: str = ""
    approved_at: str = ""
    manifest: str = ""
    review: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"state": self.state, "mode": self.mode}
        if self.mvp_at:
            out["mvp_at"] = self.mvp_at
        if self.approved_at:
            out["approved_at"] = self.approved_at
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
    """Aggregate capability states into one module_state string.

    Order matters: the first matching case wins, and it runs from most to
    least conclusive. The old version fell through to `partial_mvp` for
    anything it did not recognise, so a module whose every capability had
    been rejected by a reviewer was reported as holding MVPs -- a label that
    has since stopped meaning "work in progress" at all, since an MVP is no
    longer a path to completion.
    """
    states = {r.state for r in records}
    if not states or states == {CapabilityState.PENDING.value}:
        # nothing declared, or nothing built yet
        return ModuleState.PLANNED.value
    if states == {CapabilityState.ABANDONED.value}:
        return ModuleState.ABANDONED.value
    if states == {CapabilityState.FULLY_APPROVED.value}:
        return ModuleState.COMPLETE.value
    if CapabilityState.FULLY_APPROVED.value in states:
        # some consumable, the rest not yet
        return ModuleState.PARTIALLY_COMPLETE.value
    if CapabilityState.CHANGES_REQUESTED.value in states:
        # a reviewer said work is owed and named why
        return ModuleState.REWORK.value
    if CapabilityState.MVP_DEVELOPED.value in states:
        return ModuleState.PARTIAL_MVP.value
    # only pending and/or abandoned, mixed: work is planned, not started
    return ModuleState.PLANNED.value


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


# Reason codes a Review Record may cite. Defined once so the template, the
# reviewer prompt and this validator cannot drift apart.
REASON_CODES: tuple[str, ...] = (
    "signature",
    "schema",
    "behavior",
    "boundary",
    "test",
    "scope",
    "quality",
)


def _require_verdict(module: str, capability: str, content: str, expected: str) -> None:
    verdicts = re.findall(r"^- verdict:\s*(\S+)\s*$", content, re.MULTILINE)
    if verdicts != [expected]:
        raise StateError(
            f"review of {module} / {capability} must carry exactly one "
            f"{expected} verdict, got {verdicts or 'none'}"
        )


def _require_reason_codes(module: str, capability: str, content: str) -> list[str]:
    """A rejection the developer cannot act on is not a decision.

    `changes_requested` used to record nothing at all, which left the
    dispatcher's documented instruction — "dispatch developer with its reason
    codes" — pointing at a file nothing had ever recorded.
    """
    lines = re.findall(r"^-\s*reason codes:\s*\[(.*?)\]\s*$", content, re.MULTILINE)
    if len(lines) != 1:
        raise StateError(
            f"review of {module} / {capability} must carry exactly one "
            f"`- reason codes: [...]` line, got {len(lines)}"
        )
    codes = [c.strip() for c in lines[0].split(",") if c.strip()]
    if not codes:
        raise StateError(
            f"a CHANGES_REQUESTED review must cite at least one reason code "
            f"from {list(REASON_CODES)}; an unexplained rejection sends the "
            f"next developer back to guessing"
        )
    unknown = [c for c in codes if c not in REASON_CODES]
    if unknown:
        raise StateError(
            f"unknown reason code(s) {unknown} in {module} / {capability}; "
            f"expected any of {list(REASON_CODES)}"
        )
    return codes


def _module_source(module: str) -> Path:
    """The module's declared source root, from its module.yaml.

    Read rather than assumed as `modules/<name>`: the declaration is the
    source of truth, and a hardcoded path would check the wrong directory
    for any module that declares otherwise.
    """
    path = REPO_ROOT / "architecture/modules" / module / "module.yaml"
    if not path.is_file():
        raise StateError(f"module declaration not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    source = data.get("source")
    if not isinstance(source, str) or not source:
        raise StateError(f"{path} declares no `source:` root to check")
    return REPO_ROOT / source


def _require_work_exists(module: str) -> None:
    """Refuse a gate on a capability with nothing in the tree.

    A capability with no source file and no test cannot have been developed,
    so a Review Record claiming four OK scores over it is describing work
    that provably does not exist. This is a floor, not a proof: the tool
    cannot know which files belong to which capability, so it only rejects
    the empty case. It will not catch an agent that fabricates both a
    Manifest and a Review Record — nothing in this CLI can, because a
    document is all it ever sees. The write-scope audit
    (`python -m tools.implement.scope --base <commit>`) is the layer that
    proves a run actually touched files.
    """
    source = _module_source(module)
    has_code = source.is_dir() and any(source.rglob("*.py"))
    # tests are conventionally tests/test_<module>_<cap>.py; the directory
    # uses hyphens and the package uses underscores, so accept either
    stem = module.replace("-", "_")
    tests = REPO_ROOT / "tests"
    has_tests = tests.is_dir() and any(
        p.name.startswith("test_" + stem) and p.suffix == ".py" for p in tests.iterdir()
    )
    if not has_code:
        raise StateError(
            f"{module} has no Python source under {source}/, so no "
            f"implementation of this capability exists to review. If the work "
            f"lives elsewhere, fix the module's declared `source:` rather than "
            f"approving a Record over an empty tree."
        )
    if not has_tests:
        raise StateError(
            f"no test file matching tests/test_{stem}*.py exists, so there is "
            f"no test coverage behind the Review Record's `test_coverage: OK`. "
            f"The developer must add tests under tests/ before review."
        )


def _require_review_after_manifest(review: str, manifest: str) -> None:
    """The staleness rule AGENTS.md promises and nothing used to enforce.

    A review that predates the Manifest it reviewed is reviewing something
    else. Compared by mtime, which is an *ordering* check and not a content
    check: it cannot tell a rewrite from a `touch`, and it is defeated by a
    copied file. Equal timestamps pass, because on a coarse clock a review
    written moments after its Manifest legitimately lands on the same tick.
    """
    review_mtime = Path(review).stat().st_mtime
    manifest_mtime = Path(manifest).stat().st_mtime
    if review_mtime < manifest_mtime:
        raise StateError(
            f"the Review Record ({review}) is older than the Implementation "
            f"Manifest ({manifest}), so it reviewed an earlier state of the "
            f"work. Re-run the review over the current Manifest. Note this is "
            f"an mtime ordering check only, not proof that the code is "
            f"unchanged."
        )


def _refuse_if_blocked(module: str, capability: str, root: Path, command: str) -> None:
    """Refuse a gate transition while a design blocker for it is still open.

    A design blocker is deliberately not a state: it leaves STATE unchanged
    and is resolved by routing to ac-designer or module-designer. That is
    right, but it also meant nothing stopped a stale blocker from coexisting
    with `fully_approved`. The blocker file is the only record there is, so
    the file is what the gate checks.
    """
    path = root / module / f"{capability}.design-blocker.md"
    if not path.is_file():
        return
    resolved = path.with_name(f"{capability}.design-blocker.resolved.md")
    raise StateError(
        f"{command} refused: an open design blocker exists at {path}. A design "
        f"blocker is not a review outcome and does not change STATE, so this "
        f"check is the only thing keeping a stale one from coexisting with a "
        f"completion. Resolve the design, record what changed, then rename the "
        f"file to {resolved.name} and re-run."
    )


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
    _refuse_if_blocked(args.module, args.capability, Path(args.root), "mark-mvp")
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
    """Record a reviewer's rejection, with the reasons behind it.

    `changes_requested` used to be a bare state flip: no Review Record path,
    no reasons. The dispatcher was told to "re-dispatch developer with its
    reason codes" while nothing recorded any, so the next developer was sent
    back to guessing what the reviewer had objected to.
    """
    record = load_state(args.module, Path(args.root))
    rec = _get_cap(record, args.capability)
    _validate_transition(rec.state, "changes_requested")
    _refuse_if_blocked(args.module, args.capability, Path(args.root), "mark-changes")
    _require_artifact(
        args.module,
        args.capability,
        Path(args.root),
        "manifest",
        args.manifest,
        f"# manifest: {args.module} / {args.capability}",
    )
    _require_work_exists(args.module)
    content = _require_artifact(
        args.module,
        args.capability,
        Path(args.root),
        "review",
        args.review,
        f"# review: {args.module} / {args.capability}",
    )
    _require_review_after_manifest(args.review, args.manifest)
    _require_verdict(args.module, args.capability, content, "CHANGES_REQUESTED")
    codes = _require_reason_codes(args.module, args.capability, content)
    rec.state = "changes_requested"
    rec.review = str(Path(args.review))
    if not rec.manifest:
        rec.manifest = args.manifest
    save_state(record, Path(args.root))
    _print(
        f"marked {args.module}/{args.capability} as changes_requested "
        f"(reasons: {', '.join(codes)})"
    )
    return 0


def _archive_mvp_manifest(module: str, capability: str, given: str) -> Path | None:
    """Preserve an MVP Manifest before the full pass overwrites it.

    The full developer writes its Manifest to the same canonical path, so
    without this the `## discovery` section — the only durable record of
    what the spike found, and what the revised Card is built from — would be
    silently destroyed by the very pass it was written for.

    Returns the archive path, or None when there is nothing to archive.

    A missing or unrecorded Manifest degrades rather than refuses. `retry` is
    the way *out* of a stuck capability, and there is no CLI remedy for a
    refusal here: `register` rejects an already-registered capability and
    there is no unregister, so refusing would leave the only escape as a
    hand-edit of STATE.yaml — which the policy forbids. A lost bookkeeping
    field is a smaller problem than that. The cost is that the reopen path
    loses its handoff, so this returns loudly and the caller says so.

    An archive that already exists *is* a refusal: overwriting it would
    destroy an earlier spike's findings permanently and silently.
    """
    if not given.strip():
        _print(
            f"WARNING: {module}/{capability} is mvp_developed but its record "
            f"carries no manifest path, so there is nothing to archive. The "
            f"reopen handoff has no discovery to read: module-designer must "
            f"rebuild the Card from the existing source and the current "
            f"architecture, and that Card must go to Owner for approval as if "
            f"it were a first plan."
        )
        return None
    src = Path(given)
    if not src.is_file():
        _print(
            f"WARNING: {module}/{capability} records its MVP Manifest at {src}, "
            f"which no longer exists, so there is nothing to archive. The "
            f"reopen handoff has no discovery to read: module-designer must "
            f"rebuild the Card from the existing source and the current "
            f"architecture, and that Card must go to Owner for approval as if "
            f"it were a first plan."
        )
        return None
    dest = src.with_name(f"{capability}.mvp-manifest.md")
    if dest.exists():
        raise StateError(
            f"refusing to reopen {module}/{capability}: an archived MVP Manifest "
            f"already exists at {dest}, and archiving again would overwrite an "
            f"earlier spike's discovery permanently. Inspect {dest}, move it "
            f"aside if it is stale, then retry."
        )
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return dest


def cmd_retry(args: argparse.Namespace) -> int:
    """Reopen a capability for another developer pass.

    Valid from two states, both of which mean "a developer owes work":

      changes_requested  the reviewer rejected it; fix and resubmit
      mvp_developed      an MVP turned out to be needed for real

    Reopening from `mvp_developed` requires `--mode full`: that is how an
    Owner turns a prototype into something another module may consume. The
    existing source and tests stay; the capability simply has to earn an
    APPROVED review like any other.

    Reopening from `mvp_developed` first archives the MVP Manifest to
    `<cap>.mvp-manifest.md` and clears `rec.manifest`, because the full pass
    writes to the same path and would otherwise erase the discovery. If the
    Manifest is unrecorded or gone, the reopen still proceeds and says so:
    this is the way out of a stuck capability, and there is no CLI remedy
    for refusing it.
    """
    record = load_state(args.module, Path(args.root))
    rec = _get_cap(record, args.capability)
    _validate_transition(rec.state, "pending")
    archived = None
    if rec.state == "mvp_developed":
        if args.mode != "full":
            raise StateError(
                f"reopening {args.module}/{args.capability} from mvp_developed "
                f"requires --mode full; an MVP cannot be promoted in place, and "
                f"only mode=full work can reach fully_approved"
            )
        archived = _archive_mvp_manifest(args.module, args.capability, rec.manifest)
        rec.mode = "full"
        rec.manifest = ""
    rec.state = "pending"
    save_state(record, Path(args.root))
    _print(
        f"reopened {args.module}/{args.capability} as pending "
        f"(mode={rec.mode}); it is not consumable by other modules until "
        f"fully_approved"
    )
    if archived is not None:
        _print(
            f"archived its MVP Manifest to {archived}; its discovery section "
            f"is what module-designer must fold into the revised Card"
        )
    return 0


def cmd_mark_approved(args: argparse.Namespace) -> int:
    """Record Owner's approval of an APPROVED review.

    Requires the Manifest as well as the Review. Full mode is the only path
    to `fully_approved` — the one state other modules may consume — so it
    used to have the weaker evidence requirement, which was backwards:
    mark-mvp demanded a Manifest, mark-approved did not. The Manifest is
    what lists the files that were written, so it is the one artifact that
    can be checked against the tree.
    """
    record = load_state(args.module, Path(args.root))
    rec = _get_cap(record, args.capability)
    _validate_transition(rec.state, "fully_approved")
    _refuse_if_blocked(args.module, args.capability, Path(args.root), "mark-approved")
    if rec.mode != "full":
        raise StateError(
            "mark-approved requires mode=full; reopen an MVP with "
            "`retry --mode full` and take it through the reviewed path"
        )
    _require_artifact(
        args.module,
        args.capability,
        Path(args.root),
        "manifest",
        args.manifest,
        f"# manifest: {args.module} / {args.capability}",
    )
    _require_work_exists(args.module)
    _require_review_after_manifest(args.review, args.manifest)
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
        raise StateError(
            f"review of {args.module} / {args.capability} must carry exactly "
            f"one APPROVED verdict, got {verdicts or 'none'}"
        )
    for score in ("contract_conformance", "boundary", "test_coverage", "implementation_quality"):
        values = re.findall(rf"^\s*{score}:\s*(\S+)", content, re.MULTILINE)
        if values != ["OK"]:
            raise StateError(f"review score {score} must be exactly one OK")
    rec.state = "fully_approved"
    rec.approved_at = _now_iso()
    rec.review = str(Path(args.review))
    if not rec.manifest:
        rec.manifest = args.manifest
    save_state(record, Path(args.root))
    _print(f"marked {args.module}/{args.capability} as fully_approved")
    return 0


def cmd_abandon(args: argparse.Namespace) -> int:
    """Close a capability. Two different things share this command.

    Owner decision: the Owner looked at it and does not want it. Always
    legal from any non-terminal state, including `fully_approved`.

    Reviewer verdict: the reviewer returned `ABANDON`, meaning the
    implementation is fundamentally off-target rather than a fixable detail.
    Pass `--review` so the Record is validated and its path recorded --
    otherwise a review that recommended closing a capability is
    indistinguishable, in STATE, from the Owner simply changing their mind,
    and that difference is the whole reason the verdict exists.

    `--review` stays optional: abandoning a `pending` capability that was
    never reviewed is an ordinary Owner decision and must not require
    inventing a review to justify it.
    """
    record = load_state(args.module, Path(args.root))
    rec = _get_cap(record, args.capability)
    _validate_transition(rec.state, "abandoned")
    if args.review:
        content = _require_artifact(
            args.module,
            args.capability,
            Path(args.root),
            "review",
            args.review,
            f"# review: {args.module} / {args.capability}",
        )
        _require_verdict(args.module, args.capability, content, "ABANDON")
        rec.review = str(Path(args.review))
    rec.state = "abandoned"
    save_state(record, Path(args.root))
    if args.review:
        _print(
            f"abandoned {args.module}/{args.capability} on the reviewer's "
            f"ABANDON verdict (record at {args.review})"
        )
    else:
        _print(f"abandoned {args.module}/{args.capability} by Owner decision")
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


def _provider_of(arch: Architecture, capability: str) -> tuple[str, str] | None:
    """(module, contract) that publishes `capability`, or None if no one does.

    Asked of the architecture rather than guessed from the id. The old
    `dependers-of` took the text before the first dot as the module name, so
    `series.get` reported a module called `series` -- which does not exist;
    the provider is `market-data`.
    """
    for cname, contract in sorted(arch.contracts.items()):
        if not contract.has_capability(capability):
            continue
        owner = arch.module_for_contract(cname)
        if owner is not None:
            return owner.name, cname
    return None


def _upstream_states(
    arch: Architecture, root: Path, uses: Iterable[str]
) -> list[tuple[str, str, str]]:
    """(capability, provider module, state) for each declared upstream use.

    Only `fully_approved` is consumable, so anything else -- including a
    capability the provider has not registered at all -- is a red gate.
    """
    rows: list[tuple[str, str, str]] = []
    for cap in sorted(set(uses)):
        found = _provider_of(arch, cap)
        if found is None:
            rows.append((cap, "(no provider)", "undeclared"))
            continue
        provider, _contract = found
        rec = load_state(provider, root).capabilities.get(cap)
        rows.append((cap, provider, rec.state if rec else "unregistered"))
    return rows


def cmd_dependers_of(args: argparse.Namespace) -> int:
    """List the modules that declare a dependency on this capability.

    Both halves come from the architecture: the provider is the module that
    publishes the contract owning the capability id, and the dependers are
    the modules whose module.yaml `uses:` it. STATE is then layered on top,
    so the dispatcher can see which dependers have actually started.
    """
    arch = load_arch()
    root = Path(args.root) if args.root else STATE_ROOT
    found = _provider_of(arch, args.capability)
    if found is None:
        raise StateError(
            f"no contract in the architecture provides capability "
            f"{args.capability!r}; it is not declared anywhere"
        )
    provider, contract = found

    dependers: list[dict[str, str]] = []
    for mod in sorted(arch.modules.values(), key=lambda m: m.name):
        if mod.name == provider:
            continue
        dep = mod.dependency_on(contract)
        if dep is None or args.capability not in dep.uses:
            continue
        rec = load_state(mod.name, root).capabilities.get(args.capability)
        dependers.append(
            {
                "module": mod.name,
                "reason": dep.reason or "(none declared)",
                "state_here": rec.state if rec else "not-owned",
            }
        )
    own = load_state(provider, root).capabilities.get(args.capability)
    yaml.safe_dump(
        {
            "capability": args.capability,
            "owning_module": provider,
            "contract": contract,
            "state": own.state if own else "unregistered",
            "declared_dependers": dependers,
        },
        sys.stdout,
        sort_keys=False,
    )
    return 0


def cmd_upstream(args: argparse.Namespace) -> int:
    """The green/red upstream gate the dispatcher has to check by hand.

    The architecture declares upstream use at module granularity
    (`depends_on[].uses`), not per capability, so this reports what the
    architecture actually declares. `--upstream` narrows the set when the
    dispatcher knows which specific capabilities a given Card consumes;
    without it the gate is deliberately the wider, safe one.
    """
    arch = load_arch()
    root = Path(args.root) if args.root else STATE_ROOT
    try:
        mod = arch.module(args.module)
    except ArchError as exc:
        raise StateError(str(exc)) from exc

    target = f"{args.module}/{args.capability}" if args.capability else args.module
    if args.upstream:
        uses: list[str] = list(args.upstream)
        granularity = "explicit (--upstream)"
    else:
        uses = [cap for dep in mod.depends_on for cap in dep.uses]
        granularity = "module-level declared (depends_on[].uses)"

    if not uses:
        _print(
            f"upstream gate for {target}: green. this module declares no "
            f"upstream capability use, so there is nothing to wait for."
        )
        return 0

    rows = _upstream_states(arch, root, uses)
    red = [r for r in rows if r[2] != "fully_approved"]
    _print(
        f"upstream gate for {target} [{granularity}] -- "
        f"{len(rows) - len(red)}/{len(rows)} consumable"
    )
    for cap, provider, state in rows:
        mark = "green" if state == "fully_approved" else "red"
        _print(f"  [{mark:5}] {provider:22} {cap:34} {state}")
    if red:
        _print(
            f"RED: {len(red)} upstream capabilit{'y' if len(red) == 1 else 'ies'} "
            f"not fully_approved. Only fully_approved is consumable. Do not "
            f"spawn developer. An MVP upstream is red, not a warning: reopen "
            f"it with `retry <module> <cap> --mode full` or wait for approval."
        )
        return 1
    _print("green: every declared upstream is fully_approved.")
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
    sp.add_argument("--review", default="")
    sp.add_argument(
        "--manifest",
        default="",
        help="the Implementation Manifest this review covers; required",
    )

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
    sp.add_argument("--review", default="")
    sp.add_argument(
        "--manifest",
        default="",
        help="the Implementation Manifest this review covers; required",
    )

    sp = sub.add_parser("abandon", help="owner closes a capability")
    module_cap(sp)
    sp.add_argument(
        "--review",
        default="",
        help="the reviewer's ABANDON Record; omit when this is purely an Owner decision",
    )

    sp = sub.add_parser("show", help="print state for module or capability")
    sp.add_argument("module")
    sp.add_argument("capability", nargs="?")

    sp = sub.add_parser(
        "dependers-of",
        help="list the modules that declare a dependency on this capability",
    )
    sp.add_argument("capability")

    sp = sub.add_parser(
        "upstream",
        help="green/red upstream gate for a module or capability",
    )
    sp.add_argument("module")
    sp.add_argument("capability", nargs="?")
    sp.add_argument(
        "--upstream",
        action="append",
        default=[],
        metavar="CAP",
        help="check this capability id instead of the module's declared uses; repeatable",
    )

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
    "upstream": cmd_upstream,
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
