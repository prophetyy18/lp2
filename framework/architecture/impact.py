"""Contract change impact analysis.

Answers question 3: "if a contract changes, who is affected?"

Two blast radii are computed separately, because they need different remedies:

    DIRECT   - modules that declare a dependency on the changed contract
               (and the module that publishes it). Remedy: re-read the contract.
    INDIRECT - modules reached through the reverse `requires` closure: they
               consume a contract built on top of the changed one. Remedy: check
               whether the capability they use still means the same thing.

Impact is computed from declared metadata only. If a consumer needs something
the contract does not describe, the answer is CONTRACT_INSUFFICIENT - not an
excuse to read the publishing module's implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import CONTRACT_INSUFFICIENT, UNKNOWN_CONTRACT, ArchError
from .graph import consumers, owners, reverse_contracts
from .model import Architecture


@dataclass(frozen=True)
class ModuleImpact:
    module: str
    distance: int  # 1 = direct, 2+ = indirect
    via: str  # contract this module consumes that carries the impact
    uses: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "distance": self.distance,
            "direct": self.distance == 1,
            "via_contract": self.via,
            "uses": list(self.uses),
        }


@dataclass
class ImpactResult:
    subject: str
    subject_kind: str  # "contract" | "module"
    capabilities: tuple[str, ...] = ()
    direct: list[ModuleImpact] = field(default_factory=list)
    indirect: list[ModuleImpact] = field(default_factory=list)
    impacted_contracts: list[tuple[str, int]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def all_modules(self) -> list[ModuleImpact]:
        return sorted(self.direct + self.indirect, key=lambda i: (i.distance, i.module))

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "subject_kind": self.subject_kind,
            "capabilities": list(self.capabilities),
            "direct": [i.to_dict() for i in self.direct],
            "indirect": [i.to_dict() for i in self.indirect],
            "impacted_contracts": [
                {"contract": c, "distance": d} for c, d in self.impacted_contracts
            ],
            "affected_modules": [i.module for i in self.all_modules],
            "notes": self.notes,
        }


def impact_of_contract(
    arch: Architecture, contract: str, capabilities: list[str] | None = None
) -> ImpactResult:
    """Blast radius of a change to `contract` (or to the listed capabilities)."""
    if contract not in arch.contracts:
        raise ArchError(
            UNKNOWN_CONTRACT,
            f"unknown contract `{contract}`; known: {', '.join(sorted(arch.contracts))}",
        )

    result = ImpactResult(subject=contract, subject_kind="contract")
    if capabilities:
        unknown = [c for c in capabilities if not arch.contracts[contract].has_capability(c)]
        if unknown:
            raise ArchError(
                CONTRACT_INSUFFICIENT,
                f"contract `{contract}` does not provide: {', '.join(sorted(unknown))}",
            )
        result.capabilities = tuple(sorted(capabilities))

    # Direct: publishers implement it, consumers read it.
    for mod in owners(arch, contract):
        result.direct.append(
            ModuleImpact(
                module=mod.name,
                distance=1,
                via=contract,
                uses=tuple(arch.contracts[contract].capability_ids()),
            )
        )
    for mod in consumers(arch, contract):
        if mod.name in {o.name for o in owners(arch, contract)}:
            continue  # self-published, already recorded
        dep = mod.dependency_on(contract)
        result.direct.append(
            ModuleImpact(
                module=mod.name, distance=1, via=contract, uses=tuple(dep.uses if dep else ())
            )
        )

    # Indirect: anything consuming a contract that requires the changed one.
    for via, dist in reverse_contracts(arch, contract):
        result.impacted_contracts.append((via, dist))
        for mod in consumers(arch, via):
            if any(i.module == mod.name for i in result.direct):
                continue
            dep = mod.dependency_on(via)
            result.indirect.append(
                ModuleImpact(
                    module=mod.name,
                    distance=dist + 1,
                    via=via,
                    uses=tuple(dep.uses if dep else ()),
                )
            )

    result.notes.extend(_semver_notes(arch, contract, result))
    return result


def impact_of_module(arch: Architecture, module: str) -> ImpactResult:
    """Blast radius of a change to a module = union over the contracts it owns."""
    mod = arch.module(module)
    if not mod.owns_contracts:
        result = ImpactResult(subject=module, subject_kind="module")
        result.notes.append(
            f"module `{module}` publishes no contract; its implementation is private, "
            "so only the contracts it publishes can create a blast radius"
        )
        return result

    merged = ImpactResult(subject=module, subject_kind="module")
    for contract in sorted(mod.owns_contracts):
        sub = impact_of_contract(arch, contract)
        merged.direct.extend(sub.direct)
        merged.indirect.extend(sub.indirect)
        merged.impacted_contracts.extend(
            (c, d) for c, d in sub.impacted_contracts if (c, d) not in merged.impacted_contracts
        )
        merged.notes.append(f"via contract `{contract}`: {len(sub.all_modules)} module(s) affected")
    return merged


def _semver_notes(arch: Architecture, contract: str, result: ImpactResult) -> list[str]:
    """Flag consumers that pinned nothing, which makes review unenforceable."""
    notes: list[str] = []
    for item in result.all_modules:
        if item.uses:
            continue
        mod = arch.modules.get(item.module)
        if mod is None or mod.name in {o.name for o in owners(arch, contract)}:
            continue
        notes.append(
            f"`{item.module}` depends on `{item.via}` without itemising `uses`; "
            "declare which capabilities it relies on so impact stays reviewable"
        )
    return notes
