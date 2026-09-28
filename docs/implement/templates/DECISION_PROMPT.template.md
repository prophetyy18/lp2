# Decision Prompt templates

The ONLY thing the Owner sees in normal operation. Four forms.

## MVP path — after developer

```
✓ <module>/<capability> MVP ready (manifest OK, imports clean, <N> tests pass).
 Mark as mvp_developed? [y / not-yet / abandon]
```

## Full path — after developer, before reviewer

```
✓ <module>/<capability> developer done. dispatch reviewer? [y / changes / abandon]
   manifest: docs/implement/<module>/<capability>.manifest.md
```

## Full path — after reviewer

```
✓ <module>/<capability> reviewer: <VERDICT>  scores: c=<X> b=<X> t=<X> s=<X>
 Approve and mark fully_approved? [y / changes / abandon]
```

## Promote path — Owner re-promotes a MVP capability to full

```
⚠ promoting <module>/<capability> from MVP. existing tests + manifest unchanged.
  Dispatch reviewer on same impl? [y / redo / abandon]
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