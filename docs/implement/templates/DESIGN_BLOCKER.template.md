# Design blocker template

Use only when the approved contract or Capability Card cannot reasonably
produce the intended behavior. Save as
`docs/implement/<module>/<capability>.design-blocker.md`.

```markdown
# design blocker: <module> / <capability_id>

- found by: <developer | reviewer>
- surface: <contract | card>
- conflict: <specific contract/Card clause and why it fails>
- evidence: <one concrete input, failure mode, or contradiction>
- decision needed: <one sentence for the dispatcher/Owner>
- resolution:
```

Do not use `CHANGES_REQUESTED` or alter `STATE.yaml` for a design blocker.
After resolution, the dispatcher records the decision and changed design
file paths in `resolution`, then resumes the affected gate.
