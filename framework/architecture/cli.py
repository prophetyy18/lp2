"""archctl - command line access to the architecture framework.

    python3 -m framework.architecture.cli <command>

Every command supports --json for machine consumption. Exit code is 1 when the
result contains ERROR-severity findings, so CI can gate on it directly.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import graph, loader, query, snapshot
from .errors import ERROR, ArchError

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def _emit(data: Any, as_json: bool, text: str | None = None) -> int:
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=True))
    elif text is not None:
        print(text)
    else:
        print(json.dumps(data, indent=2, sort_keys=True))
    return EXIT_OK


def _emit_findings(findings: list[dict[str, Any]], as_json: bool) -> int:
    if as_json:
        print(json.dumps({"findings": findings}, indent=2, sort_keys=True))
    elif not findings:
        print("OK - no findings")
    else:
        for f in findings:
            print(f"[{f['severity']}] {f['code']}: {f['message']}")
    return EXIT_FINDINGS if any(f["severity"] == ERROR for f in findings) else EXIT_OK


def _render_readable(data: dict[str, Any]) -> str:
    lines = [f"module {data['module']} MAY read:"]
    lines += [f"  {r['glob']:<45} # {r['reason']}" for r in data["allowed"]]
    lines.append(f"module {data['module']} MAY NOT read:")
    lines += [f"  {r['path']:<45} # {r['reason']}" for r in data["denied"]]
    return "\n".join(lines)


def _render_dependencies(data: dict[str, Any]) -> str:
    lines = [f"module {data['module']} publishes: {', '.join(data['publishes']) or '(none)'}"]
    if not data["depends_on"]:
        lines.append("  depends on no contracts")
    for e in data["depends_on"]:
        mark = "OK " if e["satisfied"] else "BAD"
        lines.append(f"  [{mark}] {e['contract']} (publisher={e['publisher'] or 'UNPUBLISHED'})")
        if e["uses"]:
            lines.append(f"        uses: {', '.join(e['uses'])}")
        if e["missing_capabilities"]:
            lines.append(f"        MISSING: {', '.join(e['missing_capabilities'])}")
    for target in data.get("depends_on_modules", {}).get(data["module"], []):
        lines.append(f"  -> module {target} (derived, via contract)")
    return "\n".join(lines)


def _render_consumers(data: dict[str, Any]) -> str:
    lines = [f"contract {data['contract']} published_by: {', '.join(data['published_by']) or '(none)'}"]
    for c in data["direct_consumers"]:
        uses = f" uses={c['uses']}" if c["uses"] else ""
        lines.append(f"  direct consumer: {c['module']}{uses}")
    for c in data["indirect_contracts"]:
        lines.append(f"  requires it (distance {c['distance']}): {c['contract']}")
    extra = [m for m in data["indirect_consumers"]
             if m not in {c["module"] for c in data["direct_consumers"]}]
    for m in extra:
        lines.append(f"  indirect consumer: {m}")
    return "\n".join(lines)


def _render_impact(data: dict[str, Any]) -> str:
    lines = [f"impact of change to {data['subject']} ({data['subject_kind']}):"]
    lines.append("  direct:")
    for i in data["direct"]:
        uses = f" uses={i['uses']}" if i["uses"] else ""
        lines.append(f"    {i['module']} via {i['via_contract']}{uses}")
    if data["indirect"]:
        lines.append("  indirect:")
        for i in data["indirect"]:
            uses = f" uses={i['uses']}" if i["uses"] else ""
            lines.append(f"    {i['module']} (distance {i['distance']}) via {i['via_contract']}{uses}")
    if not data["affected_modules"]:
        lines.append("  (nobody)")
    for note in data.get("notes", []):
        lines.append(f"  note: {note}")
    return "\n".join(lines)


def _render_graph(arch) -> str:
    return graph.to_text(arch)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="archctl", description=__doc__)
    parser.add_argument("--root", help="repo root (default: auto-detect)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("readable", help="Q1: what may this module read?")
    p.add_argument("module")

    p = sub.add_parser("check-paths", help="Q1: may this module read these paths?")
    p.add_argument("module")
    p.add_argument("paths", nargs="+")

    p = sub.add_parser("depends", help="Q2: what may this module depend on?")
    p.add_argument("module")

    p = sub.add_parser("consumers", help="Q2 reversed: who depends on this contract?")
    p.add_argument("contract")

    p = sub.add_parser("impact", help="Q3: who is affected if this changes?")
    p.add_argument("subject", help="contract or module name")
    p.add_argument("--capability", action="append", help="narrow to capability id(s)")

    p = sub.add_parser("graph", help="print the dependency graph")
    p.add_argument("--dot", action="store_true", help="graphviz DOT output")

    p = sub.add_parser("validate", help="run the architecture validator")
    p.set_defaults(cmd="validate")

    p = sub.add_parser("snapshot", help="write a metadata snapshot")
    p.add_argument("--out")

    p = sub.add_parser("diff", help="diff current metadata against a snapshot, then analyse impact")
    p.add_argument("snapshot")

    args = parser.parse_args(argv)

    try:
        arch = loader.load(args.root)

        if args.command == "readable":
            data = query.readable(arch, args.module)
            return _emit(data, args.json, _render_readable(data))

        if args.command == "check-paths":
            findings = query.check_paths(arch, args.module, args.paths)
            return _emit_findings(findings, args.json)

        if args.command == "depends":
            data = query.dependencies(arch, args.module)
            if not args.json and data["blockers"]:
                _emit(data, False, _render_dependencies(data))
                print()
                return _emit_findings(data["blockers"], False)
            return _emit(data, args.json, _render_dependencies(data))

        if args.command == "consumers":
            data = query.consumers_of(arch, args.contract)
            return _emit(data, args.json, _render_consumers(data))

        if args.command == "impact":
            data = query.blast_radius(arch, args.subject, args.capability)
            return _emit(data, args.json, _render_impact(data))

        if args.command == "graph":
            if args.dot:
                return _emit(arch.to_dict(), True, graph.to_dot(arch))
            return _emit(arch.to_dict(), args.json, _render_graph(arch))

        if args.command == "validate":
            report = query.validation_report(arch)
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                for f in report["findings"]:
                    print(f"[{f['severity']}] {f['code']}: {f['message']}")
                if report["ok"]:
                    print("OK - architecture is valid")
            return EXIT_OK if report["ok"] else EXIT_FINDINGS

        if args.command == "snapshot":
            path = snapshot.write(arch, args.out)
            return _emit({"snapshot": str(path)}, args.json, f"wrote {path}")

        if args.command == "diff":
            data = query.impact_of_diff(arch, args.snapshot)
            text: list[str] = []
            for d in data["diff"]["contracts"]:
                text.append(f"  {d['contract']}: {d['kind']} breaking={d['breaking']}")
            for rep in data["impact"]:
                text.append(f"  impact of {rep['subject']}: {', '.join(rep['affected_modules']) or '(nobody)'}")
            text.append(f"  affected modules overall: {', '.join(data['affected_modules']) or '(none)'}")
            return _emit(data, args.json, "\n".join(text))

    except ArchError as exc:
        print(json.dumps(exc.to_dict(), indent=2) if args.json else f"ERROR {exc.code}: {exc.message}",
              file=sys.stderr)
        return EXIT_USAGE

    return EXIT_USAGE


if __name__ == "__main__":
    raise SystemExit(main())
