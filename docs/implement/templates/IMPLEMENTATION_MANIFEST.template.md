# Implementation Manifest template

Copy to `docs/implement/<module>/<capability>.manifest.md` after developer
finishes; dispatcher reads this before firing the reviewer.

```markdown
# manifest: <module> / <capability_id>

- mode: <mvp | full>
- new files:
   - modules/<module>/<file>.py
   - tests/<the stem `./bin/python -m tools.implement.naming <module> <capability>` prints>.py
- modified files:
   - modules/<module>/__init__.py    # if re-exports changed
- capability ids touched: <capability_id>
- contract conformance:
   - signature matches:    YES / NO
   - input schema parsed:  YES / NO   # only when input declared on capability
   - output schema:        YES / NO   # only when output declared
   - errors emitted:       <comma-separated code list, must match card>
   - behavior tags:        unit=<...> time=<...> idempotent=<...> ordering=<...>
- pre-handoff checks (run by developer; dispatcher re-runs):
   - archctl validate:           OK / FAIL
   - import-isolation:           OK / FAIL   # ./bin/python -m tools.check_imports <module>
   - tests passing:              <N> unit, <M> contract-conformance
- test plan coverage:              # what the tester's tests cover, not what
   - normal:    YES / NO           # you believe they cover
   - boundary:  YES / NO
   - invalid:   YES / NO
   - failure:   YES / NO
- cross-module imports in new code: NONE   # if non-NONE, dispatcher rejects
- upstream consumed: [<capability_id>, ...]   # machine-readable; mark-approved
                                            # records it, and `state upstream`
                                            # uses it to report approved
                                            # capabilities resting on a
                                            # guarantee a later change retracted

## scenarios found while implementing

The tests were written by the tester from the Card, before you ran, and you
cannot add to them. While implementing you will meet cases the Card did not
anticipate. Write each one as a **requirement question, not a description of
your code**:

  GOOD  "negative `amount` arrives; the contract does not say what happens"
  BAD   "I clamp with `max(0, amount)` in the handler"   ← this is how the
                                                       code reaches the tester
                                                       through the back door

The tester is re-spawned and rules on each one: accepted, rejected with a
reason, or escalated as a Design Blocker. A scenario you raise cannot change
what the Card specifies — it can only surface a gap in it.

- <the question>:
- risk notes: <e.g. chose to fail closed on missing upstream capability>
- upstream state at dispatch: <state of each upstream capability consumed>

## discovery

REQUIRED when `mode: mvp`. An MVP is the foreword to the full
implementation, not a throwaway: its code is disposable, but what it
learned is what the full run inherits. A manifest without this section is
rejected by `mark-mvp`.

In `full` mode this section is optional and usually empty: the tester's
`<capability>.tests.md` carries the `## discovery` instead, because the
tester went and looked at the real thing before any code existed, which is
strictly earlier and strictly more reliable than what you find afterwards.

- question: the question this MVP was meant to answer
  (e.g. does eth_getLogs survive a 10k block span, or must it split?)

- answer: what actually happened
  (e.g. stable to 8k blocks; above that it must shard, and the Card's
       stale_tolerance is now wrong)

- source: where the answer came from, for anything learned from outside this
  repository. Record the coordinates, not just a link — a URL is not
  reproducible for a fact that can change:

      source:       official URL, or the exact command run
      retrieved at: when
      chain id:     which chain
      block:        block number or hash, for anything read from a chain
      code hash:    when the fact is about deployed bytecode

  An `answer` with no coordinates is an assumption, and the reviewer treats an
  uncited claim a test depends on as an ISSUE.

- unknown: anything you could not verify. Write `UNKNOWN` and say what you
  tried. It is a legal answer and it blocks — never guess, and never carry a
  value across from another chain, provider, or module.

- surprised: anything that did not match the Card or the contract
  (e.g. the contract declares only RPC_TIMEOUT, but the node returns
       execution_reverted — the error surface is wider than designed)

- keep: assets the full run may inherit as-is
  (e.g. modules/<m>/sharding.py's split algorithm;
       tests/fixtures_rpc.py's three recorded chain responses)

- discard: code the full run must NOT inherit
  (e.g. every error path returns None; no timeout; no retry)

- known_gaps: what the full run must build that this MVP did not
  (e.g. 3 of the 4 declared error codes are unimplemented)

# consumed by reviewer + dispatcher
```

Notes:

  - The `cross-module imports in new code: NONE` line is the developer's
    signed declaration. Reviewer MUST verify by running
    `./bin/python -m tools.check_imports <module>` independently. A false
    declaration is grounds for `CHANGES_REQUESTED` with reason `boundary`.
  - If `mode: mvp`, dispatcher records
    `mark-mvp --manifest <path>` after Owner accepts the result; the CLI
    rejects a manifest with no `## discovery`. If `mode: full`, dispatcher
    dispatches reviewer after checks pass.
  - `keep` / `discard` are the anti-leak pair. An MVP's code is never
    reviewed, so it has no error handling, no timeouts and no edge cases;
    inheriting it silently is how a prototype becomes production. Say
    explicitly what carries over and what does not.
