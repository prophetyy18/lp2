"""Data model for the architecture subsystem.

Five concepts:

    Contract       - a public interface published by exactly one module.
    Capability     - one addressable thing a contract provides (granularity for
                     "is the contract enough?"). Carries input/output/payload
                     schema refs, error codes, and behavior tags.
    SchemaRef      - a qualified reference to a schema owned by a contract.
    ErrorCode      - one named failure mode an operation capability declares.
    BehaviorTag    - machine-readable behavior guarantee (unit, time semantics,
                     idempotency, ordering).
    Dependency     - a module's *declared* need for a contract and the
                     capabilities it uses from it.
    Module         - a unit of implementation with its own source tree and boundary.

The Capability.kind field is a closed vocabulary: 'operation' (request/response),
'event' (asynchronous notification), 'data' (published type only). Default is
'operation' to keep existing metadata backward compatible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Capability kind is a closed vocabulary; loader validates membership.
CAPABILITY_KINDS: tuple[str, ...] = ("operation", "event", "data")

# Behavior.unit is a controlled vocabulary. Empty string means "not specified";
# the loader rejects empty if the field is present at all.
BEHAVIOR_UNITS: tuple[str, ...] = (
    "",
    "usdg",
    "q64_64",
    "wei",
    "block_height",
    "seconds",
    "symbol",
    "decimal",
    "bytes",
    "address",
)

# Behavior.time: which clock does the capability's time-bearing fields use?
BEHAVIOR_TIME: tuple[str, ...] = ("", "event_time", "wall_clock")

# Behavior.ordering: how are repeated deliveries of the same logical event ordered?
BEHAVIOR_ORDERING: tuple[str, ...] = ("", "total", "partial", "none")

# ErrorCode.recoverable: hint for retry / circuit-breaker policy.
RECOVERABLE_KINDS: tuple[str, ...] = ("transient", "permanent", "user_input")


@dataclass(frozen=True)
class SchemaRef:
    """A qualified reference to a schema owned by some contract.

    The schema id is qualified as `<contract>.<schema_name>`; the loader does
    not (yet) verify the schema actually exists in that contract's schemas
    file. A missing schema id is a downstream wiring bug, not a load-time
    error: the framework treats refs as opaque strings so transport and
    schema language stay out of architecture.
    """

    schema: str

    def to_dict(self) -> dict[str, str]:
        return {"schema": self.schema}


@dataclass(frozen=True)
class ErrorCode:
    """One named failure mode an operation capability declares.

    `code` is the stable identifier consumers branch on. Renaming or removing
    a code is a breaking change. `recoverable` is a hint, not a guarantee:

        transient   - retry may succeed (network blip, downstream warming up)
        permanent   - retry will not help without a state change
        user_input  - the caller's input was malformed
    """

    code: str
    recoverable: str = "transient"

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "recoverable": self.recoverable}


@dataclass(frozen=True)
class BehaviorTag:
    """Machine-readable behavior guarantee on a capability.

    Only fields that prevent the failure mode "same schema, different
    understanding across providers" go here; everything else stays in the
    capability description (human-readable). Empty strings mean "not
    specified" and are accepted as defaults; the loader rejects the field
    only when an explicit value falls outside the controlled vocabulary.
    """

    unit: str = ""
    time: str = ""
    idempotent: bool | None = None
    ordering: str = ""
    stale_tolerance: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.unit:
            out["unit"] = self.unit
        if self.time:
            out["time"] = self.time
        if self.idempotent is not None:
            out["idempotent"] = self.idempotent
        if self.ordering:
            out["ordering"] = self.ordering
        if self.stale_tolerance:
            out["stale_tolerance"] = self.stale_tolerance
        return out


@dataclass(frozen=True)
class Capability:
    id: str
    kind: str = "operation"
    signature: str = ""
    description: str = ""
    input: SchemaRef | None = None
    output: SchemaRef | None = None
    payload: SchemaRef | None = None
    errors: tuple[ErrorCode, ...] = ()
    behavior: BehaviorTag | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
        }
        if self.signature:
            out["signature"] = self.signature
        if self.description:
            out["description"] = self.description
        if self.input is not None:
            out["input"] = self.input.to_dict()
        if self.output is not None:
            out["output"] = self.output.to_dict()
        if self.payload is not None:
            out["payload"] = self.payload.to_dict()
        if self.errors:
            out["errors"] = [e.to_dict() for e in self.errors]
        if self.behavior is not None:
            out["behavior"] = self.behavior.to_dict()
        return out


@dataclass(frozen=True)
class Contract:
    name: str
    path: str  # repo-relative path of the yaml file
    version: int = 1
    description: str = ""
    provides: tuple[Capability, ...] = ()
    requires: tuple[str, ...] = ()  # other contracts this contract builds on

    def capability_ids(self) -> tuple[str, ...]:
        return tuple(c.id for c in self.provides)

    def has_capability(self, cap_id: str) -> bool:
        return cap_id in self.capability_ids()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "provides": [c.to_dict() for c in self.provides],
            "requires": list(self.requires),
        }


@dataclass(frozen=True)
class Dependency:
    contract: str
    uses: tuple[str, ...] = ()  # capability ids; empty means "not itemised yet"
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": self.contract,
            "uses": list(self.uses),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Module:
    name: str
    path: str  # repo-relative module source root, e.g. modules/backtest
    description: str = ""
    depends_on: tuple[Dependency, ...] = ()
    owns_contracts: tuple[str, ...] = ()  # contract names this module implements
    readable_extra: tuple[str, ...] = ()  # additional granted read roots (globs)

    def dependency_on(self, contract: str) -> Dependency | None:
        for dep in self.depends_on:
            if dep.contract == contract:
                return dep
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "description": self.description,
            "depends_on": [d.to_dict() for d in self.depends_on],
            "owns_contracts": list(self.owns_contracts),
            "readable_extra": list(self.readable_extra),
        }


@dataclass
class Architecture:
    """The loaded, whole-project architecture metadata."""

    root: str
    contracts: dict[str, Contract] = field(default_factory=dict)
    modules: dict[str, Module] = field(default_factory=dict)

    def module(self, name: str) -> Module:
        from .errors import ArchError, UNKNOWN_MODULE

        if name not in self.modules:
            raise ArchError(UNKNOWN_MODULE, f"unknown module: {name}")
        return self.modules[name]

    def contract(self, name: str) -> Contract:
        from .errors import ArchError, UNKNOWN_CONTRACT

        if name not in self.contracts:
            raise ArchError(UNKNOWN_CONTRACT, f"unknown contract: {name}")
        return self.contracts[name]

    def module_for_contract(self, contract: str) -> Module | None:
        for mod in self.modules.values():
            if contract in mod.owns_contracts:
                return mod
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "contracts": {n: c.to_dict() for n, c in sorted(self.contracts.items())},
            "modules": {n: m.to_dict() for n, m in sorted(self.modules.items())},
        }
