# Decision Prompt templates

The ONLY thing the Owner sees in normal operation. Two normal forms, one
reopen form, and one exceptional design blocker form.

An `mvp_developed` capability is not usable by any other module. Nothing
downstream may build on it; there is no yellow flag.

## MVP path — after developer

```
✓ <module>/<capability> MVP ready (manifest OK, imports clean, <N> tests pass).
 Mark as mvp_developed? [y / not-yet / abandon]
```

## Full path — after reviewer

```
✓ <module>/<capability> reviewer: <VERDICT>  scores: c=<X> b=<X> t=<X> q=<X>
 Approve and mark fully_approved? [y / changes / abandon]
```

## Reopen path — Owner turns an MVP into a capability other modules may use

```
⚠ reopening <module>/<capability> from MVP to full. Not usable by other
  modules until it reaches fully_approved; existing source and tests are kept.
```

## Design blocker — exceptional path

```
⚠ <module>/<capability> DESIGN_BLOCKED (<contract|card>): <one-line conflict>.
  Decision needed: <one-line decision>; blocker: docs/implement/<module>/<capability>.design-blocker.md
```

---

Notes for the dispatcher:

  - Never show the Owner anything longer than ~100 words in a single message.
  - Background / history / spec stays in the agent prompts and CLI output.
  - When Owner answers `not-yet` / `changes` / `redo`, ask one short
    follow-up: "what specifically needs to change?" Capture the answer
    and pass it back to the relevant subagent on the next loop.
  - When Owner answers `abandon`, call
    `python -m tools.implement.state abandon <module> <cap>` and move to
    the next capability without further ceremony.
