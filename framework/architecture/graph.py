"""Dependency graph and reverse/consumer queries.

Two edge kinds exist, and only two:

    module  --depends_on-->  contract      (declared in module.yaml)
    contract --requires-->  contract       (declared in contract yaml)

There is deliberately no `module --depends_on--> module` edge. Module-to-module
coupling is always mediated by a contract, which is what makes "who is
affected" computable.

A module-level edge is *derived*: A depends on B when A consumes a contract that
B publishes. Derived edges are read-only views, never authored by hand.
"""

from __future__ import annotations

from collections import deque

from .errors import ArchError, CYCLE_DETECTED
from .model import Architecture, Module


def consumers(arch: Architecture, contract: str) -> list[Module]:
    """Modules that directly declare a dependency on `contract`."""
    return sorted(
        (m for m in arch.modules.values() if m.dependency_on(contract)), key=lambda m: m.name
    )


def owners(arch: Architecture, contract: str) -> list[Module]:
    """Modules that publish `contract`."""
    return sorted(
        (m for m in arch.modules.values() if contract in m.owns_contracts),
        key=lambda m: m.name,
    )


def direct_module_edges(arch: Architecture) -> dict[str, set[str]]:
    """consumer module -> set of provider modules, via contracts."""
    edges: dict[str, set[str]] = {name: set() for name in arch.modules}
    for mod in arch.modules.values():
        for dep in mod.depends_on:
            for owner in owners(arch, dep.contract):
                if owner.name != mod.name:
                    edges[mod.name].add(owner.name)
    return edges


def reverse_contracts(arch: Architecture, contract: str) -> list[tuple[str, int]]:
    """Contracts that transitively require `contract`, nearest first.

    Distance 1 = requires `contract` directly.
    """
    reverse: dict[str, list[str]] = {n: [] for n in arch.contracts}
    for name, c in arch.contracts.items():
        for req in c.requires:
            if req in reverse:
                reverse[req].append(name)

    seen = {contract}
    queue: deque[tuple[str, int]] = deque([(contract, 0)])
    out: list[tuple[str, int]] = []
    while queue:
        node, dist = queue.popleft()
        for dependent in sorted(reverse.get(node, ())):
            if dependent in seen:
                continue
            seen.add(dependent)
            out.append((dependent, dist + 1))
            queue.append((dependent, dist + 1))
    return out


def transitive_module_consumers(arch: Architecture, contract: str) -> list[str]:
    """Modules consuming any contract in the reverse-requires closure."""
    names = {contract}
    for name, _ in reverse_contracts(arch, contract):
        names.add(name)
    return sorted({m.name for c in names for m in consumers(arch, c)})


def contract_order(arch: Architecture) -> list[str]:
    """Topological order of contracts (dependencies first). Raises on cycles."""
    pending = {n: set(c.requires) & set(arch.contracts) for n, c in arch.contracts.items()}
    order: list[str] = []
    while pending:
        ready = sorted(n for n, reqs in pending.items() if not reqs)
        if not ready:
            raise ArchError(
                CYCLE_DETECTED,
                "contract requirement cycle: " + ", ".join(sorted(pending)),
            )
        for name in ready:
            order.append(name)
            del pending[name]
        pending = {
            n: {r for r in reqs if r in pending} for n, reqs in pending.items()
        }
    return order


def to_dot(arch: Architecture) -> str:
    """Graphviz DOT rendering of the full graph."""
    lines = [
        "digraph architecture {",
        '  rankdir="LR";',
        '  node [shape=box, fontname="Helvetica"];',
    ]
    for name in sorted(arch.contracts):
        lines.append(f'  "{name}" [shape=ellipse, style=filled, fillcolor="#eef"];')
    for name in sorted(arch.modules):
        lines.append(f'  "mod:{name}" [fillcolor="#ffe"];')
    for cname in sorted(arch.contracts):
        c = arch.contracts[cname]
        for req in sorted(c.requires):
            lines.append(f'  "{req}" -> "{cname}";')
    for m in sorted(arch.modules.values(), key=lambda m: m.name):
        for dep in m.depends_on:
            uses = f' [label="{",".join(dep.uses)}"]' if dep.uses else ""
            lines.append(f'  "mod:{m.name}" -> "{dep.contract}"{uses};')
    lines.append("}")
    return "\n".join(lines)


def to_text(arch: Architecture) -> str:
    """Human-readable rendering."""
    out: list[str] = ["CONTRACTS"]
    for name in contract_order_or_sorted(arch):
        c = arch.contracts[name]
        own = ", ".join(o.name for o in owners(arch, name)) or "(unpublished)"
        out.append(f"  {name}  v{c.version}  owner={own}")
        for cap in c.provides:
            out.append(f"      - {cap.id}: {cap.signature or cap.description}")
        if c.requires:
            out.append(f"      requires: {', '.join(sorted(c.requires))}")

    out.append("")
    out.append("MODULES")
    for m in sorted(arch.modules.values(), key=lambda m: m.name):
        out.append(f"  {m.name}  ({m.path})")
        if m.owns_contracts:
            out.append(f"      publishes: {', '.join(sorted(m.owns_contracts))}")
        if not m.depends_on:
            out.append("      depends_on: (none)")
        for dep in m.depends_on:
            uses = f" uses={list(dep.uses)}" if dep.uses else ""
            out.append(f"      -> {dep.contract}{uses}")
    return "\n".join(out)


def contract_order_or_sorted(arch: Architecture) -> list[str]:
    """Topological order when acyclic, else plain sorted order (for rendering)."""
    try:
        return contract_order(arch)
    except ArchError:
        return sorted(arch.contracts)
