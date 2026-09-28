"""Data model for the architecture subsystem.

Four concepts only:

    Contract   - a public interface published by exactly one module.
    Capability - one addressable thing a contract provides (granularity for
                 "is the contract enough?").
    Dependency - a module's *declared* need for a contract and the
                 capabilities it uses from it.
    Module     - a unit of implementation with its own source tree and boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Capability:
    id: str
    kind: str = "opaque"
    signature: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "signature": self.signature,
            "description": self.description,
        }


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
