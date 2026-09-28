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
- resolution: <one sentence, written by the dispatcher; leave empty when filed>
```

Do not use `CHANGES_REQUESTED` or alter `STATE.yaml` for a design blocker.
STATE carries no blocker state, so the file is the only record there is —
which is why the state CLI refuses every gate transition while this file
exists, and `retry` stays open so the path out is never deadlocked.

To resolve: fill in `resolution` with the decision and the changed design
file paths, then rename the file to
`<capability>.design-blocker.resolved.md`. Renaming rather than deleting is
deliberate — the resolution stays readable, and the rename is itself the
recorded act that lifts the gate.
