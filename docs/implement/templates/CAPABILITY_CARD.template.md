# Capability Card template

Copy this file to `docs/implement/<module>/<capability>.card.md` and fill in.

```markdown
# card: <module> / <capability_id>

- mode: full                      # or mvp
- contract: architecture/contracts/<module>-api.yaml
- capability: <capability_id>     # must id in contract.provides
- signature: "<full signature string>"
- input schema:  <contract>.<name>      # ref only; schema in architecture/schemas/
- output schema: <contract>.<name>      # ref only
- payload schema: <contract>.<name>     # only when kind=event
- behavior:
   unit: <usdg | q64_96 | q128_128 | wei | block_height | seconds | symbol | decimal | bytes | address | tick | liquidity | token_base_unit>
   time:  <event_time | wall_clock>
   timezone: <tz_aware_utc | naive_utc | naive_local>
   idempotent: <bool>
   ordering: <total | partial | none>
   stale_tolerance: <human readable, optional>
- errors:
   - code: <CODE>
     recoverable: <transient | permanent | user_input>
   - code: <CODE>
     recoverable: <transient | permanent | user_input>
- test plan:
   - normal:    <e.g. happy-path signature returns declared output schema>
   - boundary:  <e.g. min/max tick, empty input, max block range>
   - invalid:   <e.g. malformed pool key, wrong chain id>
   - failure:   <e.g. transient network error, permanent rejection>
- reads allowed:
   - modules/<module>/**
   - architecture/**
   - framework/architecture/__init__.py
- reads denied:
   - modules/<other>/**
   - framework/architecture/_internals/**
- notes: <anything Owner should know before dispatching developer>

# filled by module-designer; consumed by developer / reviewer / dispatcher
```

Notes:

  - The `mode` field is the Owner's choice. Default `full`. If `mvp`, the
    reviewer is skipped — the developer's manifest stands and is recorded as
    `mvp_developed`, which no other module may consume. If it turns out
    another module needs it, Owner reopens it with
    `retry <module> <cap> --mode full` and it goes through the reviewed path.
  - `errors[*].code` strings are stable identifiers; renaming is breaking.
  - `behavior.{unit, time, idempotent, ordering}` are machine-checked by
    `framework.architecture`; deviations raise `INVALID_METADATA`.