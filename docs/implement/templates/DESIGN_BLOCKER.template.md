# Design blocker template

Use only when the approved contract or Capability Card cannot reasonably
produce the intended behavior. Save as `docs/implement/<module>/<capability>.design-blocker.md`, or — when
the defect is in the contract as a whole rather than in one Card — as
`docs/implement/<module>/CONTRACT.design-blocker.md`.

**Which one.** "How this Card should be written" is capability-scoped. "The
contract declares a surface that does not exist / an error vocabulary nobody
declared / a parameter with no possible values" is contract-scoped, and it
stops every capability in the module. Filing a contract defect against
whichever capability tripped over it is the expensive mistake: the rest of
the module walks past it and builds on the same broken design.

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

To resolve, do not rename it by hand:

```bash
./bin/python -m tools.implement.state resolve <module> <capability> \
  --resolution "<the decision, and the design files that changed>"
```

The command writes the resolution into this file, renames it to
`<capability>.design-blocker.resolved.md`, and records the path in STATE.
Renaming rather than deleting is deliberate — the resolution stays readable,
and the rename is the recorded act that lifts the gate — but a *hand* rename
recorded nothing, and an empty `resolution:` is refused, because a design
question that closed without a trace of what closed it has not closed.
