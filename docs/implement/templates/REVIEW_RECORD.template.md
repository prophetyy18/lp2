# Review Record template

Reviewer produces this at `docs/implement/<module>/<capability>.review.md`
after auditing developer's diff + manifest + Capability Card.

```markdown
# review: <module> / <capability_id>

- reviewer model: MiniMax-M3[1m]
- reviewed: <ISO timestamp>
- scores (4 项,每项 OK / ISSUE):
   contract_conformance: <OK | ISSUE>   # signature / schema refs / errors / behavior tags all match
   boundary:             <OK | ISSUE>   # python -m tools.check_imports <module> clean
   test_coverage:        <OK | ISSUE>   # normal / boundary / invalid / failure paths covered
   spec_drift:           <OK | ISSUE>   # no behavior exposed beyond the Capability Card
- verdict: <APPROVED | CHANGES_REQUESTED | ABANDON>
- reason codes: [<signature | schema | behavior | boundary | test | scope>]
- notes (≤ 2 lines per ISSUE):
   - <issue>: <one-line explanation>
   - <issue>: <one-line explanation>

# consumed by dispatcher; dispatcher fires mark-approved / mark-changes / abandon
```

Notes:

  - Any single ISSUE forces verdict = `CHANGES_REQUESTED`. Use `ABANDON` only
    when the implementation is fundamentally off-target (not a fixable
    detail).
  - `boundary: ISSUE` is special: a real cross-module import is a hard
    rule break, not a stylistic call. Reject unconditionally.
  - Reviewer MUST run `python -m tools.check_imports <module>` itself;
    do not trust the developer's `cross-module imports: NONE` line.