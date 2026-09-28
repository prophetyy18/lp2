# Review Record template

Reviewer produces this at `docs/implement/<module>/<capability>.review.md`
after auditing developer's diff + manifest + Capability Card.

```markdown
# review: <module> / <capability_id>

- reviewer model: MiniMax-M3
- reviewed: <ISO timestamp>
- scores (4 项,每项 OK / ISSUE):
   contract_conformance: <OK | ISSUE>   # contract and Card match; no undeclared public behavior
   boundary:             <OK | ISSUE>   # python -m tools.check_imports <module> clean
   test_coverage:        <OK | ISSUE>   # normal / boundary / invalid / failure paths covered
   implementation_quality: <OK | ISSUE> # errors, bounded I/O, cleanup, readable code, useful types
- verdict: <APPROVED | CHANGES_REQUESTED | ABANDON>
- reason codes: [<signature | schema | behavior | boundary | test | scope | quality>]
- notes (≤ 2 lines per ISSUE):
   - <issue>: <one-line explanation>
   - <issue>: <one-line explanation>

# consumed by dispatcher; Owner decides before dispatcher updates STATE
```

Notes:

  - The four score names above are the canonical ones. `mark-approved` and
    `mark-changes` match them literally, so do not abbreviate them here.
    The reviewer's *handoff line* to the dispatcher uses a deliberately
    different compact spelling — `c= b= t= q=` — because that line is the
    ≤100-word summary Owner reads. Two surfaces, two spellings, no mixing.
  - Any single ISSUE forces verdict = `CHANGES_REQUESTED`. Use `ABANDON` only
    when the implementation is fundamentally off-target (not a fixable
    detail).
  - `CHANGES_REQUESTED` must cite at least one reason code; `mark-changes`
    rejects a Record with an empty list, because a rejection the developer
    cannot act on sends the next developer back to guessing.
  - `ABANDON` is a verdict the reviewer *recommends*, not one it decides:
    the dispatcher calls `abandon --review <record>`, and Owner may decline
    and ask for changes instead. Closing a capability that was never
    reviewed is an ordinary Owner decision and takes a plain `abandon`.
  - `boundary: ISSUE` is special: a real cross-module import is a hard
    rule break, not a stylistic call. Reject unconditionally.
  - Reviewer MUST run `python -m tools.check_imports <module>` itself;
    do not trust the developer's `cross-module imports: NONE` line.
