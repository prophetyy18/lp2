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

from tools.implement import naming
from tools.implement.errors import StateError

STATE_ROOT = Path("docs/implement")

# The pseudo-capability a contract-level design blocker hangs off. Not a
# capability id -- it has no `provides` entry and is never registered -- but
# it needs a path that cannot collide with one, and reusing the artifact
# naming keeps the two scopes shaped identically.
CONTRACT_SCOPE = "CONTRACT"

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
    # `pending` is reachable only through `reopen`, and only with evidence that
    # the design actually changed. It is not reachable through `retry`: a
    # design change is nobody's review verdict, and routing it through
    # mark-changes would be the same error the upstream-regression report
    # deliberately avoids -- recording one module's rework as another role's
    # rejection.
    "fully_approved": frozenset({"changes_requested", "abandoned", "pending"}),
    "changes_requested": frozenset({"pending", "abandoned"}),
    "abandoned": frozenset(),
}

# Which states each command may act on. `_ALLOWED` is the graph; this says
# who is allowed to walk which edge, and it has to exist separately because
# the graph cannot tell two edges to `pending` apart. `retry` means "a
# reviewer rejected this" and its whole value is that a rejection is always a
# rejection. `reopen` means "the design under this changed". Both land on
# `pending`; if either could be walked from either state, a design change
# could be recorded as a review verdict and a rejection could be recorded as
# a design change.
_RETRYABLE: frozenset[str] = frozenset({"changes_requested", "mvp_developed"})
_REOPENABLE: frozenset[str] = frozenset({"fully_approved"})


class CapabilityState(str, Enum):
    PENDING = "pending"
    MVP_DEVELOPED = "mvp_developed"
    FULLY_APPROVED = "fully_approved"
    CHANGES_REQUESTED = "changes_requested"
    ABANDONED = "abandoned"


class ModuleState(str, Enum):
    """How far along a module is. A summary, never a gate.

    Three values, because three is what it can say without repeating the
    capabilities underneath it. The previous six (`planned / partial_mvp /
    rework / partially_complete / complete / abandoned`) each encoded a
    detail the capability rows already carry, and one of them --
    `partially_complete` -- implied a granularity that does not exist:
    consumption is per capability, so a module is never a consumable unit.
    """

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"


@dataclass
class CapabilityRecord:
    state: str = "pending"
    mode: str = "full"  # mvp | full
    mvp_at: str = ""
    approved_at: str = ""
    manifest: str = ""
    tests: str = ""
    review: str = ""
    blocker: str = ""
    consumes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"state": self.state, "mode": self.mode}
        if self.mvp_at:
            out["mvp_at"] = self.mvp_at
        if self.approved_at:
            out["approved_at"] = self.approved_at
        if self.manifest:
            out["manifest"] = self.manifest
        if self.tests:
            out["tests"] = self.tests
        if self.review:
            out["review"] = self.review
        if self.blocker:
            out["blocker"] = self.blocker
        if self.consumes:
            out["consumes"] = list(self.consumes)
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapabilityRecord":
        return cls(
            state=str(data.get("state", "pending")),
            mode=str(data.get("mode", "full")),
            mvp_at=str(data.get("mvp_at", "")),
            approved_at=str(data.get("approved_at", "")),
            manifest=str(data.get("manifest", "")),
            tests=str(data.get("tests", "")),
            review=str(data.get("review", "")),
            blocker=str(data.get("blocker", "")),
            consumes=[str(c) for c in (data.get("consumes") or [])],
        )


@dataclass
class ModuleRecord:
    name: str
    capabilities: dict[str, CapabilityRecord] = field(default_factory=dict)

    @property
    def module_state(self) -> str:
        """Derived, and deliberately not a stored field.

        It used to be persisted alongside the capabilities it summarises.
        Nothing ever read it -- not even `load_state`, which recomputed it
        and overwrote whatever the file said -- so it was a copy that could
        silently disagree with the rows beneath it, and hand-editing STATE
        was forbidden anyway. Computing it here means drift is impossible by
        construction rather than by discipline, and the file keeps facts
        only.
        """
        return compute_module_state(self.capabilities.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.name,
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
        return cls(name=name, capabilities=caps)


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
    path = root / record.name / "STATE.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(record.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def compute_module_state(
    records: Iterable[CapabilityRecord], unregistered: Iterable[str] = ()
) -> str:
    """Aggregate capability states into one module_state string.

    Three outcomes, and every one of them is a question about *work*, never
    about consumability. That distinction is the whole point: whether
    another module may depend on this one is answered per capability by the
    upstream gate, so a module-level "partially available" would describe a
    granularity that does not exist.

      complete     every capability is fully_approved -- the module is done
      not_started  nothing has been worked on (all pending, or none declared)
      in_progress  everything else: work has started and has not landed

    `unregistered` is the set of capabilities the contract declares and
    STATE.yaml has never heard of. It counts as pending, because a
    capability nobody has registered is work nobody has done -- and leaving
    it out is how a module with one approved capability out of three reported
    `complete`. Observed on the first end-to-end run, which is exactly the
    moment it should have been caught: `market-data` had one of its three
    capabilities `fully_approved` and printed `complete`, because the other
    two were invisible to a function that only ever saw STATE.yaml.

    A module whose capabilities were all abandoned reports `in_progress`:
    three values cannot also say "started and then deliberately closed", and
    `in_progress` at least records that it was touched. Adding a capability
    to a `complete` module drops it back to `in_progress`, which is the
    intended ratchet -- the new work is genuinely outstanding.
    """
    states = {r.state for r in records}
    if unregistered:
        states.add(CapabilityState.PENDING.value)
    if not states or states == {CapabilityState.PENDING.value}:
        # nothing declared, or nothing built yet
        return ModuleState.NOT_STARTED.value
    if states == {CapabilityState.FULLY_APPROVED.value}:
        return ModuleState.COMPLETE.value
    return ModuleState.IN_PROGRESS.value


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
    expected = naming.artifact_path(root, module, capability, kind)
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


def _capability_defs(module: str, capability: str) -> Any | None:
    """The contract's own record of what this capability must handle.

    Read from the architecture rather than from the Card, because the Card is
    a document the module-designer wrote and the contract is what the
    framework enforces. Resolved against `REPO_ROOT`, the same root the
    artifact checks use, so one root governs every read this CLI makes.
    Returns None when the capability is not declared, so a typo is a refusal
    rather than a crash.
    """
    arch = load_arch(REPO_ROOT)
    found = _provider_of(arch, capability)
    if found is None or found[0] != module:
        return None
    for cap in arch.contract(found[1]).provides:
        if cap.id == capability:
            return cap
    return None


def _test_obligations(cap: Any) -> dict[str, str]:
    """What the contract itself demands a test for, keyed by obligation.

    Every error code is a promise to a consumer that this failure is
    reported rather than raised as something else, and every `behavior`
    guarantee is a promise about what a consumer may assume. All of it is
    already machine-readable in the contract YAML, and the MVP path had
    learned this the hard way -- the discovery template's own worked example
    is "3 of the 4 declared error codes are unimplemented". The full path is
    the only one another module may consume, so it is the one that has to
    carry the lesson.

    **Derived from what the contract declares, not from a hand-picked list.**
    It used to name `idempotent` and `ordering` and ignore `unit`, `time` and
    `stale_tolerance` -- so those three were decoration, and a contract could
    declare fourteen `unit: decimal` guarantees across four capabilities that
    nothing would ever check. Two of five fields had a reader and three did
    not, which made `behavior` 60% decorative, and adding a field to it added
    a fourth unread one. Deriving the list means a field is either enforced
    or it should not exist.

    What earns an obligation is a *guarantee*, so the negative and
    unspecified values do not: `idempotent: false` promises nothing to test,
    and neither does an absent `unit`. `stale_tolerance` is free text and no
    test name can be derived from it, so it is the one field with no
    obligation; it is called out here rather than left as a silent gap.

    Empty for a capability that declares no errors and no behavior, which is
    most of a base module; the check is then vacuous, not absent.
    """
    obligations: dict[str, str] = {e.code: f"error code {e.code}" for e in cap.errors}
    behavior = cap.behavior
    if behavior is None:
        return obligations
    for field_name in ("unit", "time", "timezone"):
        value = getattr(behavior, field_name, "")
        if value:
            obligations[field_name] = f"behavior.{field_name}: {value}"
    # `idempotent` is Optional, and None means "not specified" rather than
    # False -- a capability that says nothing is not promising to be
    # non-idempotent, so it earns no obligation.
    if behavior.idempotent is True:
        obligations["idempotent"] = "behavior.idempotent: true"
    if behavior.ordering in ("total", "partial"):
        obligations["ordering"] = f"behavior.ordering: {behavior.ordering}"
    return obligations


def _obligation_block(record: str) -> dict[str, str] | None:
    """Parse a Test Record's `tests by obligation:` mapping, or None.

    A mapping rather than a count, because a count cannot say *which*
    failure a test covers, and the failure this exists to catch is precisely
    an unclaimed one. Deliberately not matched by searching the test file
    for the error code as a string: a developer who parametrizes over
    `cap.errors` has written a better test than one who pastes the literal,
    and refusing that would train people into the worse habit.
    """
    lines = record.splitlines()
    for index, line in enumerate(lines):
        if not re.match(r"^-\s*tests by obligation:\s*$", line):
            continue
        out: dict[str, str] = {}
        for entry in lines[index + 1 :]:
            match = re.match(r"^\s+-\s+(\S+):\s+(\S+)\s*$", entry)
            if not match:
                break
            out[match.group(1)] = match.group(2)
        return out
    return None


def _require_obligations_tested(
    module: str, capability: str, record: str
) -> list[str]:
    """Every guarantee the contract declares must be claimed by a named test.

    And the named test must exist. A mapping the tester wrote but did not
    honour is the failure mode a count cannot see.

    The mapping is read from the *Tester's* Test Record, not the developer's
    Manifest. It used to live in the Manifest, which meant the implementer
    was signing a statement about test coverage for code it had just written
    -- the same self-certification `_require_work_exists` is built to refuse.
    Asking the party that did not write the code, and did not write the
    tests' expectations from the code, is the whole point of having a tester.

    The honest limit: this reads three artifacts -- contract, Test Record,
    test file -- so an agent that writes all three consistently but tests
    nothing still passes. What it rules out is the specific, common, and
    previously invisible case of a capability whose declared error surface
    is partly untested, and where the record quietly says otherwise.
    """
    cap = _capability_defs(module, capability)
    if cap is None:
        raise StateError(
            f"capability {capability!r} is not declared by any contract owned "
            f"by module {module!r}; add it to the module's contract first"
        )
    obligations = _test_obligations(cap)
    if not obligations:
        return []
    claimed = _obligation_block(record)
    if claimed is None:
        raise StateError(
            f"{module} / {capability} declares "
            f"{len(obligations)} guarantee(s) that need a test -- "
            + ", ".join(sorted(obligations))
            + f" -- but the Test Record carries no `tests by obligation:` block. "
            f"Map each one to a test method that covers it."
        )
    unknown = sorted(set(claimed) - set(obligations))
    if unknown:
        raise StateError(
            f"Test Record for {module} / {capability} claims obligation(s) "
            f"{unknown} the contract does not declare; the contract declares "
            f"{sorted(obligations)}"
        )
    missing = [o for o in obligations if o not in claimed]
    if missing:
        raise StateError(
            f"{module} / {capability} declares guarantee(s) {missing} with no "
            f"test claimed for them in the Manifest. A declared error code is "
            f"a promise to whoever consumes this module that the failure is "
            f"reported that way; an untested one is the commonest way that "
            f"promise is broken."
        )
    test_file = REPO_ROOT / naming.test_rel_path(module, capability)
    if not test_file.is_file():
        raise StateError(
            f"{module} / {capability} claims tests in its Manifest but "
            f"{test_file} does not exist. `./bin/python -m tools.implement.naming "
            f"{module} {capability}` prints the expected path."
        )
    source = test_file.read_text(encoding="utf-8")
    unfulfilled = [
        f"{key} -> {name}"
        for key, name in sorted(claimed.items())
        if not re.search(rf"^\s*def\s+{re.escape(name)}\s*\(", source, re.MULTILINE)
    ]
    if unfulfilled:
        raise StateError(
            f"{test_file} has no test method for {unfulfilled}. The Test Record "
            f"maps a guarantee to a test that is not there."
        )
    return sorted(obligations)


def _require_tests_run(content: str, module: str, capability: str) -> int:
    """The reviewer must have run the tests, and none of them may be skipped.

    `test_coverage: OK` is a claim about tests nobody in the record was
    required to execute. A skipped test still leaves the file on disk, still
    counts as coverage, and still reports OK to the exit code -- so four
    skipped tests pass every other check in this CLI. Zero skips is the rule
    because a skip is unreviewable: it asserts nothing, and "we cannot run
    this here" is what `mode: mvp` is for.
    """
    found = re.findall(
        r"^-\s*tests run:\s*(\d+)\s+passed,\s*(\d+)\s+skipped\s*$",
        content,
        re.MULTILINE,
    )
    if len(found) != 1:
        raise StateError(
            f"review of {module} / {capability} must carry exactly one "
            f"`- tests run: <N> passed, <M> skipped` line recording what the "
            f"reviewer actually ran, got {len(found)}"
        )
    passed, skipped = (int(n) for n in found[0])
    if passed < 1:
        raise StateError(
            f"review of {module} / {capability} reports {passed} tests passed; "
            f"the reviewer must have run the capability's test file"
        )
    if skipped:
        raise StateError(
            f"review of {module} / {capability} reports {skipped} skipped "
            f"test(s). A skip asserts nothing, so it is not coverage: a "
            f"guarantee that cannot be exercised here is what `mode: mvp` is "
            f"for, not a reason to skip."
        )
    return passed


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


def _contract_capabilities(arch: Architecture, module: str) -> set[str]:
    """Every capability the architecture says this module owns.

    The complement of STATE.yaml's rows, and the reason `state show` cannot
    trust them alone: STATE only ever learns about a capability when someone
    registers it, so a contract capability that nobody has reached yet is
    invisible to a function that reads only the file.
    """
    mod = arch.modules.get(module)
    if mod is None:
        return set()
    caps: set[str] = set()
    for name in mod.owns_contracts:
        caps.update(arch.contract(name).capability_ids())
    return caps


def _consumed_upstreams(manifest: str) -> list[str]:
    """The capability ids this implementation was built against.

    Read from the Manifest's machine-readable `upstream consumed:` line. It
    is what makes a *retracted* guarantee visible after the fact: the
    upstream gate answers "may I start", and it can only see the module's
    whole declared `uses` set. This answers "what was this approved thing
    actually standing on", which is the question nobody could ask before.
    """
    match = re.search(r"^-\s*upstream consumed:\s*\[(.*?)\]\s*$", manifest, re.MULTILINE)
    if not match:
        return []
    return [c.strip() for c in match.group(1).split(",") if c.strip()]


def _require_work_exists(module: str) -> None:
    """Refuse a gate on a capability with nothing in the tree.

    A capability with no source file and no test cannot have been developed,
    so a Review Record claiming four OK scores over it is describing work
    that provably does not exist. This is a floor, not a proof: the tool
    cannot know which files belong to which capability, so it only rejects
    the empty case. It will not catch an agent that fabricates both a
    Manifest and a Review Record — nothing in this CLI can, because a
    document is all it ever sees. The write-scope audit
    (`./bin/python -m tools.implement.scope --base <commit>`) is the layer that
    proves a run actually touched files.
    """
    source = _module_source(module)
    has_code = source.is_dir() and any(source.rglob("*.py"))
    # A gate that knows only a module cannot know which of its test files
    # belong to this capability, so it asks the weaker question the data can
    # actually answer: does the module have tests at all? The write-scope
    # audit does know the capability and asks the exact one. Both go through
    # `naming`, so the two layers cannot disagree on what a test file is
    # called — which is how they came to disagree before.
    stem = naming.module_test_prefix(module)
    tests = REPO_ROOT / "tests"
    has_tests = tests.is_dir() and any(
        p.name.startswith(stem) and p.suffix == ".py" for p in tests.iterdir()
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
            f"no test file matching {stem}*.py exists under tests/, so there is "
            f"no test coverage behind the Review Record's `test_coverage: OK`. "
            f"The developer must add tests under tests/ before review; "
            f"`./bin/python -m tools.implement.naming {module} <capability>` prints "
            f"the expected path."
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


def _require_resolution_recorded(path: Path) -> None:
    """A resolved blocker must say what was decided, not just that it ended.

    Resolution was a rename and nothing else, so `mv x.design-blocker.md
    x.design-blocker.resolved.md` lifted the gate while writing down
    nothing. The rename is the recorded act; the sentence next to it is what
    makes it worth reading a month later, and the template has always asked
    for one.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in content.splitlines():
        match = re.match(r"^-\s*resolution:\s*(.*)$", line)
        if match:
            if match.group(1).strip() and match.group(1).strip() not in ("-", "<", "<...>"):
                return
            break
    raise StateError(
        f"{path.name} carries no resolution. Renaming a blocker is how the gate "
        f"lifts, so an empty `- resolution:` records that a design question was "
        f"closed without recording what closed it. Fill in the decision and the "
        f"design files that changed, then re-run."
    )


def _refuse_if_blocked(module: str, capability: str, root: Path, command: str) -> None:
    """Refuse a gate transition while a design blocker for it is still open.

    A design blocker is deliberately not a state: it leaves STATE unchanged
    and is resolved by routing to ac-designer or module-designer. That is
    right, but it also meant nothing stopped a stale blocker from coexisting
    with `fully_approved`. The blocker file is the only record there is, so
    the file is what the gate checks.

    Two scopes, because a contract defect belongs to no single capability and
    a capability-scoped-only gate let the rest of the module walk straight
    past it. `market-data` was the demonstration: a blocker filed against
    `series.symbols` -- the capability that tripped over the missing
    ingestion surface -- gates only `series.symbols`, while `series.get` and
    `series.calendar` carry on building on the same broken contract. And they
    are the two that actually consume bars, so they are the two that needed
    the decision most. A contract-level defect now stops the whole module.

    Which scope a defect belongs to is the dispatcher's call to route, and the
    rule is simple: "how this Card is written" is capability-scoped; "the
    contract itself is wrong" is contract-scoped.
    """
    contract_path = naming.artifact_path(root, module, CONTRACT_SCOPE, "design-blocker")
    if contract_path.is_file():
        _require_resolution_recorded(
            naming.artifact_path(root, module, CONTRACT_SCOPE, "design-blocker.resolved")
        )
        raise StateError(
            f"{command} refused for every capability of {module}: an open "
            f"contract-level design blocker exists at {contract_path}. A defect "
            f"in the contract belongs to no single capability, so gating only "
            f"the one that found it lets the rest of the module build on the "
            f"same broken design. Resolve it, record what changed, then rename "
            f"the file to {contract_path.name.replace('.md', '.resolved.md')} "
            f"and re-run."
        )
    path = naming.artifact_path(root, module, capability, "design-blocker")
    if not path.is_file():
        _require_resolution_recorded(
            naming.artifact_path(root, module, capability, "design-blocker.resolved")
        )
        return
    _require_resolution_recorded(
        naming.artifact_path(root, module, capability, "design-blocker.resolved")
    )
    resolved = naming.artifact_path(root, module, capability, "design-blocker.resolved")
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
    dest = naming.artifact_in(src.parent, capability, "mvp-manifest")
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
    if rec.state not in _RETRYABLE:
        raise StateError(
            f"{args.module}/{args.capability} is {rec.state}; `retry` reopens "
            f"work a reviewer rejected ({', '.join(sorted(_RETRYABLE))}). A "
            f"published capability whose design changed is `reopen` — and it "
            f"needs a reason and the resolved blocker, because taking back "
            f"what other modules may build on is a design decision"
        )
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

    Two checks here read the *contract* rather than a document, and they are
    the only ones that do. Every declared error code, and every declared
    behavior guarantee, must be mapped by the Manifest to a test method that
    exists; and the Review Record must say how many tests the reviewer
    actually ran, with none skipped. Both exist because `fully_approved` is
    consumable: it is the one state in which something this CLI has never
    read — the code, and the promise the contract makes to a consumer that
    does not exist yet — is taken on trust.
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
    manifest = _require_artifact(
        args.module,
        args.capability,
        Path(args.root),
        "manifest",
        args.manifest,
        f"# manifest: {args.module} / {args.capability}",
    )
    test_record = _require_artifact(
        args.module,
        args.capability,
        Path(args.root),
        "tests",
        args.tests,
        f"# tests: {args.module} / {args.capability}",
    )
    _require_work_exists(args.module)
    # The two checks below are the only ones in this CLI that read the
    # contract rather than a document, and they are here because
    # `fully_approved` is the one state another module is allowed to build
    # on: what a consumer is entitled to assume about this capability is
    # whatever the contract declares, and an untested error code is a broken
    # promise made to a module that has not been written yet.
    _require_obligations_tested(args.module, args.capability, test_record)
    _require_review_after_manifest(args.review, args.manifest)
    content = _require_artifact(
        args.module,
        args.capability,
        Path(args.root),
        "review",
        args.review,
        f"# review: {args.module} / {args.capability}",
    )
    _require_verdict(args.module, args.capability, content, "APPROVED")
    for score in ("contract_conformance", "boundary", "test_coverage", "implementation_quality"):
        values = re.findall(rf"^\s*{score}:\s*(\S+)", content, re.MULTILINE)
        if values != ["OK"]:
            raise StateError(f"review score {score} must be exactly one OK")
    run = _require_tests_run(content, args.module, args.capability)
    rec.state = "fully_approved"
    rec.approved_at = _now_iso()
    rec.review = str(Path(args.review))
    if not rec.manifest:
        rec.manifest = args.manifest
    rec.tests = str(Path(args.tests))
    consumed = _consumed_upstreams(manifest)
    if consumed:
        rec.consumes = consumed
    save_state(record, Path(args.root))
    _print(
        f"marked {args.module}/{args.capability} as fully_approved "
        f"({run} tests run by the reviewer)"
    )
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


def cmd_resolve(args: argparse.Namespace) -> int:
    """Close a design blocker by recording the decision, then renaming it.

    This was a manual `mv` by the dispatcher, and a manual `mv` records
    nothing: the resolution is the sentence next to the rename, and nobody
    was checking it. `mark-approved` now refuses a resolved blocker with an
    empty `resolution:`, but a check that fires after the fact is a trap for
    whoever tripped it -- so the decision is written here, once, by the
    command that performs the rename, and the path is recorded in STATE so
    "this capability went through a design change" survives the file.

    `CONTRACT` resolves a contract-level blocker, which has no single
    capability to attach to; it is left as the file, and `state show` names
    it.
    """
    root = Path(args.root)
    contract_scope = args.capability == CONTRACT_SCOPE
    if contract_scope:
        src = naming.artifact_path(root, args.module, CONTRACT_SCOPE, "design-blocker")
    else:
        _require_declared_capability(args.module, args.capability)
        src = naming.artifact_path(root, args.module, args.capability, "design-blocker")
    if not src.is_file():
        raise StateError(
            f"no open design blocker at {src}; nothing to resolve. A blocker "
            f"is filed by the role that hit the problem and closed here, so "
            f"that the decision survives the file."
        )
    decision = args.resolution.strip()
    if not decision:
        raise StateError(
            f"--resolution is required. Renaming a blocker is what lifts the "
            f"gate, so a rename with nothing next to it closes a design "
            f"question without leaving a trace of what closed it."
        )
    dest = naming.artifact_path(
        root, args.module, args.capability, "design-blocker.resolved"
    )
    if dest.is_file():
        raise StateError(
            f"{dest} already exists; a second resolution would overwrite the "
            f"first one's reasoning. Read it first, move it aside if it is "
            f"stale, then resolve again."
        )
    text = src.read_text(encoding="utf-8")
    line = f"- resolution: {decision}"
    if re.search(r"^-\s*resolution:", text, re.MULTILINE):
        text = re.sub(r"^-\s*resolution:.*$", line, text, count=1, flags=re.MULTILINE)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    src.write_text(text, encoding="utf-8")
    src.rename(dest)

    if contract_scope:
        _print(
            f"resolved the contract-level design blocker for {args.module}: "
            f"{dest}. Every capability in the module was stopped on it and is "
            f"unblocked now. Any capability already `fully_approved` on the "
            f"old wording is NOT automatically re-opened — run "
            f"`dependers-of` for each one you retracted and decide with Owner."
        )
        return 0
    record = load_state(args.module, root)
    rec = _get_cap(record, args.capability)
    rec.blocker = str(dest)
    save_state(record, root)
    _print(
        f"resolved the design blocker for {args.module}/{args.capability}: "
        f"{dest}. The capability is no longer gated. If the resolution moved "
        f"the design, re-run the tester against the revised Card before the "
        f"developer reconciles — the old tests assert the old specification, "
        f"and the developer is not allowed to change them."
    )
    return 0


def _require_declared_capability(module: str, capability: str) -> None:
    """Guard the resolve path against a typo creating an orphan file."""
    arch = load_arch(REPO_ROOT)
    found = _provider_of(arch, capability)
    if found is None or found[0] != module:
        raise StateError(
            f"capability {capability!r} is not provided by module {module!r}; "
            f"a design blocker can only be resolved for a declared capability, "
            f"or for {CONTRACT_SCOPE} (a contract-level blocker)"
        )


def cmd_reopen(args: argparse.Namespace) -> int:
    """Re-open an approved capability because the design under it changed.

    `fully_approved` is the one state another module may build on, and it is
    reachable in a loop: the upstream gate is checked once, at approval, and
    a later design change can retract what was approved. The loop back to
    `pending` therefore has to exist — and it is deliberately NOT `retry`,
    which means "a reviewer rejected this". A design change is nobody's
    review verdict, and `retry` requires a CHANGES_REQUESTED Record and its
    reason codes precisely so that a rejection is always a rejection.

    The evidence is a resolved design blocker, and it is mandatory. Re-opening
    something other modules are consuming is a serious act, and the only thing
    that makes it one is a design decision that actually happened. A `--reason`
    typed by whoever wants the capability back is not evidence of anything, so
    the blocker is what the command checks and the reason is what it records
    for the next reader.
    """
    root = Path(args.root)
    record = load_state(args.module, root)
    rec = _get_cap(record, args.capability)
    if rec.state not in _REOPENABLE:
        raise StateError(
            f"{args.module}/{args.capability} is {rec.state}, not fully_approved. "
            f"reopen takes back a capability that was published; for one that "
            f"owes work use `retry` — a reviewer rejection and a design change "
            f"are different facts and land in different places"
        )
    _validate_transition(rec.state, "pending")
    reason = args.reason.strip()
    if not reason:
        raise StateError(
            f"--reason is required. Taking back a capability other modules may "
            f"build on is a design decision, and this is the only record that "
            f"one happened and what it was."
        )
    # The evidence is mandatory, and it is the whole reason this command is
    # not "a way to undo an approval". A reason typed by whoever wants to
    # take the capability back is not evidence of anything — it is the
    # reason the sentence is still asked for, but the blocker is what proves
    # a design decision actually happened. Same rule as mark-changes needing
    # a real Review Record: the credential comes from the decision, never
    # from the account of someone executing it.
    if not args.blocker.strip():
        raise StateError(
            f"--blocker is required. Re-opening a capability other modules may "
            f"build on is only legitimate when a design decision retracted "
            f"something, and that decision is on record as a resolved design "
            f"blocker. A reason alone would let anyone retake a published "
            f"capability by typing a sentence."
        )
    resolved = naming.artifact_path(
        root, args.module, args.capability, "design-blocker.resolved"
    )
    contract_resolved = naming.artifact_path(
        root, args.module, CONTRACT_SCOPE, "design-blocker.resolved"
    )
    if not resolved.is_file() and not contract_resolved.is_file():
        raise StateError(
            f"--blocker points at nothing resolved: neither {resolved} nor "
            f"{contract_resolved} exists. Resolve the design first "
            f"(`state resolve`), then re-open."
        )
    rec.state = "pending"
    # `approved_at` goes because the capability is no longer approved, and a
    # stale timestamp saying it was would be a lie in the state file. The
    # Review Record path stays: it is a real historical artifact and `retry`
    # keeps it too. The consequence — `state show` displays a review path on
    # a capability with work in flight — is the known open item, not
    # something to fix inconsistently in one command.
    rec.approved_at = ""
    if not rec.blocker:
        rec.blocker = args.blocker
    save_state(record, root)
    _print(
        f"re-opened {args.module}/{args.capability} as pending: it is no longer "
        f"consumable by other modules until it reaches fully_approved again. "
        f"Reason: {reason}. Any module that declared `uses:` on it should be "
        f"told — run `dependers-of {args.capability}` for the list."
    )
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
        # Corrected against the architecture before it is printed. Without
        # this the summary only ever saw the capabilities somebody happened
        # to register, so a module with one of three approved printed
        # `complete` and the two it had never reached were not there to
        # disagree. Asking the architecture costs one read and closes it.
        try:
            declared = _contract_capabilities(load_arch(REPO_ROOT), args.module)
        except (ArchError, StateError):
            declared = set()
        missing = sorted(declared - set(record.capabilities))
        # A comment, not a field: the summary belongs to the reader, not to
        # the file, so the YAML below stays facts only.
        print(
            f"# module_state: "
            f"{compute_module_state(record.capabilities.values(), missing)}"
        )
        if missing:
            print(
                f"# not registered ({len(missing)} of {len(declared)} declared "
                f"by the contract): {', '.join(missing)}",
                file=sys.stderr,
            )
        # A contract-level blocker has no capability to hang off, so `state
        # show` is the only place it can be named. A module with one is
        # stopped, and the rows below all look ordinary.
        open_contract = naming.artifact_path(
            Path(args.root), args.module, CONTRACT_SCOPE, "design-blocker"
        )
        if open_contract.is_file():
            print(
                f"# STOPPED: an open contract-level design blocker at "
                f"{open_contract} — every capability in {args.module} is "
                f"gated until `state resolve {args.module} {CONTRACT_SCOPE}`",
                file=sys.stderr,
            )
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

    _report_retracted_guarantees(arch, root, args.module, args.capability)
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


def _report_retracted_guarantees(
    arch: Architecture, root: Path, module: str, capability: str | None
) -> None:
    """Approved capabilities standing on something no longer consumable.

    The upstream gate answers "may I start", and it can only see the module's
    whole declared `uses` set. This answers a different question: a
    capability that was `fully_approved` — consumable by every other module —
    on the strength of a guarantee that a later design change retracted. The
    transition `fully_approved -> changes_requested` exists, but nothing
    performs it on its behalf, and deliberately so: a capability would be
    re-opened by another module's work, using a review verdict to record
    something no reviewer said, and one upstream rework would take out every
    downstream capability with it.

    So it is reported, not enforced. The capability stays consumable until
    Owner decides otherwise; the point is that the decision gets made with
    the information in front of them rather than never.
    """
    record = load_state(module, root)
    if capability:
        targets = [(capability, record.capabilities.get(capability))]
    else:
        targets = sorted(record.capabilities.items())
    for cap, rec in targets:
        if rec is None or rec.state != "fully_approved" or not rec.consumes:
            continue
        broken = []
        for dep in rec.consumes:
            found = _provider_of(arch, dep)
            if found is None:
                broken.append((dep, "(no provider)", "undeclared"))
                continue
            provider, _ = found
            dep_rec = load_state(provider, root).capabilities.get(dep)
            state = dep_rec.state if dep_rec else "unregistered"
            if state != "fully_approved":
                broken.append((dep, provider, state))
        if broken:
            detail = ", ".join(f"{d} ({pr}, {st})" for d, pr, st in broken)
            _print(
                f"  ⚠ {module}/{cap} is fully_approved and consumable, but "
                f"rests on: {detail}. A design change retracted it. Nothing "
                f"re-opened this automatically — decide with Owner whether to "
                f"`mark-changes` it or leave it."
            )


def _print(msg: str) -> None:
    print(msg, file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="./bin/python -m tools.implement.state")
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
    sp.add_argument(
        "--tests",
        default="",
        help="the Tester's Test Record; required, and the source of the obligation mapping",
    )

    sp = sub.add_parser("abandon", help="owner closes a capability")
    module_cap(sp)
    sp.add_argument(
        "--review",
        default="",
        help="the reviewer's ABANDON Record; omit when this is purely an Owner decision",
    )

    sp = sub.add_parser(
        "resolve",
        help="close a design blocker, recording the decision",
    )
    sp.add_argument("module")
    sp.add_argument(
        "capability",
        help=f"the capability, or {CONTRACT_SCOPE} for a contract-level blocker",
    )
    sp.add_argument(
        "--resolution",
        default="",
        help="what was decided and which design files changed; required",
    )

    sp = sub.add_parser(
        "reopen",
        help="take back a fully_approved capability whose design changed",
    )
    module_cap(sp)
    sp.add_argument(
        "--reason",
        default="",
        help="what changed in the design; required and recorded",
    )
    sp.add_argument(
        "--blocker",
        default="",
        help="the resolved design blocker that caused this; required, and must exist",
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
    "reopen": cmd_reopen,
    "resolve": cmd_resolve,
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
