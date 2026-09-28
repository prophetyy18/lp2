# Implementation Manifest template

Copy to `docs/implement/<module>/<capability>.manifest.md` after developer
finishes; dispatcher reads this before firing the reviewer.

```markdown
# manifest: <module> / <capability_id>

- mode: <mvp | full>
- new files:
   - modules/<module>/<file>.py
   - tests/test_<module>_<capability>.py
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
   - import-isolation:           OK / FAIL   # python -m tools.check_imports <module>
   - tests passing:              <N> unit, <M> contract-conformance
- test plan coverage:
   - normal:    YES / NO
   - boundary:  YES / NO
   - invalid:   YES / NO
   - failure:   YES / NO
- cross-module imports in new code: NONE   # if non-NONE, dispatcher rejects
- risk notes: <e.g. chose to fail closed on missing upstream capability>
- upstream state at dispatch: <state of each upstream capability consumed>

# consumed by reviewer + dispatcher
```

Notes:

  - The `cross-module imports in new code: NONE` line is the developer's
    signed declaration. Reviewer MUST verify by running
    `python -m tools.check_imports <module>` independently. A false
    declaration is grounds for `CHANGES_REQUESTED` with reason `boundary`.
  - If `mode: mvp`, dispatcher records `mark-mvp` directly after the
    manifest lands. If `mode: full`, dispatcher fires reviewer.