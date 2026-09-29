"""Architecture validator.

Checks the invariants that make the other three answers trustworthy. Everything
it reports is machine-readable so CI (or a future workflow) can gate on codes.

Invariant list, in the order a mistake usually appears:

  1. every contract is published by exactly one module
  2. every contract reference resolves (module depends_on, contract requires)
  3. every `uses` capability actually exists in the contract  -> CONTRACT_INSUFFICIENT
  4. no module depends on another module directly                -> ILLEGAL_DEPENDENCY
  5. no contract requirement cycles                              -> CYCLE_DETECTED
  6. `readable_extra` never reaches into another module's tree   -> BOUNDARY_VIOLATION
  7. no duplicate capability ids inside a contract
  8. hygiene warnings: consumers that itemise no `uses`, contracts nobody uses
  9. every `input`/`output`/`payload` schema ref resolves        -> SCHEMA_DANGLING
 10. every type named in a `signature` has a declared shape      -> SCHEMA_UNDECLARED
"""

from __future__ import annotations

from .boundary import _glob_to_regex
from .errors import (
    BOUNDARY_VIOLATION,
    CYCLE_DETECTED,
    CONTRACT_INSUFFICIENT,
    ERROR,
    ILLEGAL_DEPENDENCY,
    INFO,
    SCHEMA_AMBIGUOUS,
    SCHEMA_DANGLING,
    SCHEMA_UNDECLARED,
    UNITEMISED_USES,
    UNKNOWN_CONTRACT,
    WARNING,
    Finding,
)
from .graph import consumers, owners
from .model import Architecture, Capability, Module, SchemaRef
from .signatures import bare_name_index, type_names


def validate(arch: Architecture) -> list[Finding]:
    findings: list[Finding] = []
    findings += _check_publication(arch)
    findings += _check_references(arch)
    findings += _check_capabilities(arch)
    findings += _check_module_edges(arch)
    findings += _check_cycles(arch)
    findings += _check_readable_extra(arch)
    findings += _check_schemas(arch)
    findings += _check_hygiene(arch)
    return findings


def has_errors(findings: list[Finding]) -> bool:
    return any(f.severity == ERROR for f in findings)


def _check_publication(arch: Architecture) -> list[Finding]:
    out: list[Finding] = []
    for name in sorted(arch.contracts):
        own = owners(arch, name)
        if not own:
            out.append(
                Finding(
                    code=INFO,
                    severity=INFO,
                    message=f"contract `{name}` is not published by any module",
                    context={"contract": name, "path": arch.contracts[name].path},
                )
            )
        elif len(own) > 1:
            out.append(
                Finding(
                    code=ILLEGAL_DEPENDENCY,
                    message=(
                        f"contract `{name}` is published by {len(own)} modules: "
                        f"{', '.join(m.name for m in own)}; exactly one publisher is required"
                    ),
                    context={"contract": name, "modules": [m.name for m in own]},
                )
            )
    for mod in sorted(arch.modules.values(), key=lambda m: m.name):
        for cname in sorted(mod.owns_contracts):
            if cname not in arch.contracts:
                out.append(
                    Finding(
                        code=UNKNOWN_CONTRACT,
                        message=f"module `{mod.name}` publishes unknown contract `{cname}`",
                        context={"module": mod.name, "contract": cname},
                    )
                )
    return out


def _check_references(arch: Architecture) -> list[Finding]:
    out: list[Finding] = []
    for mod in sorted(arch.modules.values(), key=lambda m: m.name):
        seen: set[str] = set()
        for dep in mod.depends_on:
            if dep.contract in seen:
                out.append(
                    Finding(
                        code=ILLEGAL_DEPENDENCY,
                        message=f"module `{mod.name}` declares contract `{dep.contract}` twice",
                        context={"module": mod.name, "contract": dep.contract},
                    )
                )
            seen.add(dep.contract)
            if dep.contract not in arch.contracts:
                out.append(
                    Finding(
                        code=UNKNOWN_CONTRACT,
                        message=(
                            f"module `{mod.name}` depends on unknown contract `{dep.contract}`; "
                            "create it under architecture/contracts/ first"
                        ),
                        context={"module": mod.name, "contract": dep.contract},
                    )
                )
    for c in sorted(arch.contracts.values(), key=lambda c: c.name):
        for req in sorted(c.requires):
            if req not in arch.contracts:
                out.append(
                    Finding(
                        code=UNKNOWN_CONTRACT,
                        message=f"contract `{c.name}` requires unknown contract `{req}`",
                        context={"contract": c.name, "requires": req},
                    )
                )
    return out


def _check_capabilities(arch: Architecture) -> list[Finding]:
    out: list[Finding] = []
    for c in sorted(arch.contracts.values(), key=lambda c: c.name):
        seen: set[str] = set()
        for cap in c.provides:
            if cap.id in seen:
                out.append(
                    Finding(
                        code=CONTRACT_INSUFFICIENT,
                        message=f"contract `{c.name}` declares capability `{cap.id}` twice",
                        context={"contract": c.name, "capability": cap.id},
                    )
                )
            seen.add(cap.id)

    for mod in sorted(arch.modules.values(), key=lambda m: m.name):
        for dep in mod.depends_on:
            contract = arch.contracts.get(dep.contract)
            if contract is None:
                continue
            for cap in dep.uses:
                if contract.has_capability(cap):
                    continue
                out.append(
                    Finding(
                        code=CONTRACT_INSUFFICIENT,
                        message=(
                            f"module `{mod.name}` uses capability `{cap}` from contract "
                            f"`{dep.contract}`, which does not provide it. "
                            f"Extend the contract or add a new one - reading "
                            f"`{_publisher_hint(arch, dep.contract)}`'s implementation is not allowed."
                        ),
                        context={
                            "module": mod.name,
                            "contract": dep.contract,
                            "capability": cap,
                            "available": list(contract.capability_ids()),
                        },
                    )
                )
    return out


def _publisher_hint(arch: Architecture, contract: str) -> str:
    own = owners(arch, contract)
    return own[0].name if own else contract


def _check_module_edges(arch: Architecture) -> list[Finding]:
    """Modules must reach each other through contracts, never directly."""
    out: list[Finding] = []
    for mod in sorted(arch.modules.values(), key=lambda m: m.name):
        for dep in mod.depends_on:
            if dep.contract in arch.modules:
                out.append(
                    Finding(
                        code=ILLEGAL_DEPENDENCY,
                        message=(
                            f"module `{mod.name}` depends on module `{dep.contract}` directly; "
                            "declare a dependency on a contract instead"
                        ),
                        context={"module": mod.name, "target": dep.contract},
                    )
                )
    return out


def _check_cycles(arch: Architecture) -> list[Finding]:
    state: dict[str, int] = {n: 0 for n in arch.contracts}
    stack: list[str] = []
    out: list[Finding] = []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for req in sorted(arch.contracts[node].requires):
            if req not in arch.contracts:
                continue
            if state[req] == 1:
                cyc = stack[stack.index(req):] + [req]
                out.append(
                    Finding(
                        code=CYCLE_DETECTED,
                        message="contract requirement cycle: " + " -> ".join(cyc),
                        context={"cycle": cyc},
                    )
                )
            elif state[req] == 0:
                visit(req)
        stack.pop()
        state[node] = 2

    for name in sorted(arch.contracts):
        if state[name] == 0:
            visit(name)
    return out


def _check_readable_extra(arch: Architecture) -> list[Finding]:
    """A granted read root must not open another module's implementation."""
    out: list[Finding] = []
    for mod in sorted(arch.modules.values(), key=lambda m: m.name):
        for glob in sorted(mod.readable_extra):
            rx = _glob_to_regex(glob)
            for other in sorted(arch.modules.values(), key=lambda m: m.name):
                if other.name == mod.name:
                    continue
                prefix = other.path.rstrip("/") + "/"
                # Would this glob admit a path inside the other module's tree?
                sample = prefix + "x.py"
                if rx.match(sample):
                    out.append(
                        Finding(
                            code=BOUNDARY_VIOLATION,
                            message=(
                                f"module `{mod.name}` grants readable_extra `{glob}`, which "
                                f"covers `{other.path}/**`. Cross-module access must go through "
                                "a contract."
                            ),
                            context={
                                "module": mod.name,
                                "readable_extra": glob,
                                "violates_module": other.name,
                            },
                        )
                    )
    return out


def _check_schemas(arch: Architecture) -> list[Finding]:
    """Do the types this architecture names actually have shapes?

    Two spellings, checked separately because they mean different things when
    they fail.

    An explicit `{schema: <contract>.<Type>}` ref is a direct claim that this
    is where the type lives. If nothing is there, the ref is a lie and no
    severity below ERROR is honest — a consumer that follows it has nowhere to
    go, and the only way the architecture could have passed before is that
    nobody ever resolved the string.

    A bare name in a `signature:` is weaker: the prose may simply have missed
    the schema. That is still a real gap — a tester cannot state an expected
    value for a type with no fields, and two developers can both be "right"
    about what `RunRecord` holds — so it is reported, but at WARNING until the
    declared shapes are filled in. Promoting it to ERROR is the signal that
    the gap is closed, and it belongs to whoever owns that call, not to me.
    """
    out: list[Finding] = []
    index = bare_name_index(arch.schemas)

    dangling: dict[str, set[str]] = {}
    undeclared: dict[str, set[str]] = {}

    for name in sorted(arch.contracts):
        contract = arch.contracts[name]
        for cap in contract.provides:
            where = f"{name}:{cap.id}"
            for ref, slot in _explicit_refs(cap):
                if ref.schema not in arch.schemas:
                    dangling.setdefault(ref.schema, set()).add(f"{where} ({slot})")
            for type_name in sorted(type_names(cap.signature)):
                owners_ = index.get(type_name, ())
                if len(owners_) == 1:
                    continue
                if len(owners_) > 1:
                    out.append(
                        Finding(
                            code=SCHEMA_AMBIGUOUS,
                            message=(
                                f"{where}: type `{type_name}` is declared by more "
                                f"than one contract ({', '.join(sorted(owners_))}), "
                                f"so a bare name in a signature cannot identify it"
                            ),
                            severity=WARNING,
                            context={
                                "contract": name,
                                "capability": cap.id,
                                "type": type_name,
                                "owners": sorted(owners_),
                            },
                        )
                    )
                    continue
                undeclared.setdefault(type_name, set()).add(where)

    for ref_id in sorted(dangling):
        out.append(
            Finding(
                code=SCHEMA_DANGLING,
                message=(
                    f"schema `{ref_id}` is referenced but not declared; declare it "
                    f"in architecture/schemas/{ref_id.rpartition('.')[0]}.yaml or "
                    f"change the reference"
                ),
                severity=ERROR,
                context={"schema": ref_id, "referenced_by": sorted(dangling[ref_id])},
            )
        )

    for type_name in sorted(undeclared):
        out.append(
            Finding(
                code=SCHEMA_UNDECLARED,
                message=(
                    f"type `{type_name}` is named in a capability signature but has "
                    f"no declared shape; a tester cannot state an expected value "
                    f"for a type whose fields are undeclared"
                ),
                severity=WARNING,
                context={"type": type_name, "named_by": sorted(undeclared[type_name])},
            )
        )

    return out


def _explicit_refs(cap: Capability) -> list[tuple[SchemaRef, str]]:
    refs = [
        (cap.input, "input"),
        (cap.output, "output"),
        (cap.payload, "payload"),
    ]
    return [(ref, slot) for ref, slot in refs if ref is not None]


def _check_hygiene(arch: Architecture) -> list[Finding]:
    out: list[Finding] = []
    for mod in sorted(arch.modules.values(), key=lambda m: m.name):
        for dep in mod.depends_on:
            contract = arch.contracts.get(dep.contract)
            # When the contract publishes capabilities, an unitemised `uses`
            # is now an ERROR: capability-level impact analysis requires
            # every consumer to name what it relies on.
            if not dep.uses and contract and contract.provides:
                out.append(
                    Finding(
                        code=UNITEMISED_USES,
                        message=(
                            f"module `{mod.name}` depends on `{dep.contract}` without itemising "
                            "`uses`; capability-level impact analysis cannot narrow without ids"
                        ),
                        context={
                            "module": mod.name,
                            "contract": dep.contract,
                            "available": list(contract.capability_ids()),
                        },
                    )
                )
            elif not dep.uses:
                # Contract publishes nothing yet (e.g. placeholder); keep this
                # as a soft warning so a contract in flight doesn't block CI.
                out.append(
                    Finding(
                        code=CONTRACT_INSUFFICIENT,
                        severity=WARNING,
                        message=(
                            f"module `{mod.name}` depends on `{dep.contract}` without itemising "
                            "`uses`; impact analysis cannot be precise without capability ids"
                        ),
                        context={"module": mod.name, "contract": dep.contract},
                    )
                )
        for dep in mod.depends_on:
            if dep.contract in mod.owns_contracts:
                out.append(
                    Finding(
                        code=WARNING,
                        severity=WARNING,
                        message=(
                            f"module `{mod.name}` both publishes and depends on `{dep.contract}`"
                        ),
                        context={"module": mod.name, "contract": dep.contract},
                    )
                )
    for name in sorted(arch.contracts):
        if not consumers(arch, name) and not owners(arch, name):
            out.append(
                Finding(
                    code=INFO,
                    severity=INFO,
                    message=f"contract `{name}` has no publisher and no consumer",
                    context={"contract": name},
                )
            )
    return out
