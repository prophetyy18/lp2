# Repository policy for AI coding agents

This file is the owner-facing policy for every AI agent that touches this
repository. Product intent, contract surface, and architecture rules live
in their own files (`architecture/`, `framework/architecture/`); this file
defines how agents should work.

## 1. Five roles, one Owner

| Role | When active | What it does |
|---|---|---|
| **Owner** | always (you) | one-line decisions at the three gates; nothing else |
| **ac-designer** | architecture changes | edits `architecture/contracts/`, `architecture/modules/`; never reads implementation |
| **module-designer** | planning a module | writes `docs/implement/<module>/PLAN.md` + Capability Cards; never writes code |
| **developer** | implementing a capability | writes `modules/<module>/**` + tests + Implementation Manifest; one capability per spawn |
| **reviewer** | auditing a capability (full mode) | produces 4-score Review Record; one capability per spawn |

The dispatcher (main session) mediates between Owner and the four
subagents; it is the only role that talks to you. ac-designer is a
prefix-invoked role; module-designer / developer / reviewer are spawned
subagents (see `.claude/agents/<role>.md` for each role's prompt).

## 2. Two modes per capability

  - **mvp** — developer writes the capability; reviewer is skipped;
    state recorded as `mvp_developed`. **Does not count as done.**
    Use when: prototyping, validating the contract surface, or building
    fast to unblock downstream work.
  - **full** — developer writes; reviewer audits; state recorded as
    `fully_approved` on reviewer APPROVED. **Counts as done.**
    Use when: shipping to any consumer or committing to the contract.

Owner decides the mode when the Capability Card is prepared. Default `full`.
A `mvp_developed` capability can later be promoted: Owner triggers
`promote`, reviewer runs on the unchanged implementation.

## 3. Three isolation layers (module boundary is hard)

Modules must not read each other's implementation. Three layers enforce:

  1. **Role prompt read scope.** Each role's `.claude/agents/<role>.md`
     declares an exact allow-list of paths. The dispatcher copies that
     allow-list into the subagent's spawn prompt.
  2. **AST import scanner.** `python -m tools.check_imports <module>`
     walks every `.py` under `modules/<module>/` and reports
     `BOUNDARY_VIOLATION` for any cross-module `import` or `from X import Y`.
     CI / pre-commit hook runs this.
  3. **Implementation Manifest declaration.** Developer must write
     `cross-module imports in new code: NONE` in the manifest; reviewer
     re-runs the scanner and rejects on a false declaration.

## 4. State is recorded, not narrated

Per-capability state lives in `docs/implement/<module>/STATE.yaml` and is
written only by `python -m tools.implement.state <cmd>`. The five states
  and the transitions between them are validated by the CLI; agents and
  Owner never hand-edit STATE.yaml.

States:

  - `pending`              planned, no implementation
  - `mvp_developed`        MVP done (does not count as done)
  - `changes_requested`    reviewer rejected
  - `fully_approved`       reviewer approved (counts as done)
  - `abandoned`            owner closed this capability

The aggregated `module_state` is computed from per-capability states and
written by the CLI on every save.

## 5. Three gates per capability (Owner intervenes three times max)

  1. **Card gate.** Owner reads the Capability Card (~10 lines) and
     chooses: `go / redo / abandon`. This decides mode.
  2. **Developer gate (full mode only).** Owner reads the
     Implementation Manifest path and chooses: `dispatch reviewer / not-yet
     / abandon`.
  3. **Review gate (full mode only).** Owner reads the Review Record
     one-liner (`verdict=APPROVED scores=c=OK b=OK t=OK s=OK`) and chooses:
     `approve / changes / abandon`.

MVP mode skips gates 2 and 3 (one gate total). Promote mode skips gate 1
and adds an additional reviewer dispatch.

In all cases, the Owner-facing prompt is a single line of ≤ 100 words.
Background and rationale stay in the agent prompts and CLI output, never in
Owner-facing messages.

## 6. Authority order

When sources conflict, use this order:

  1. `architecture/contracts/*.yaml` + `architecture/modules/*/module.yaml`
     — public surface, single source of truth
  2. `.claude/agents/<role>.md` — role behavior, hard rules per role
  3. `tools/implement/state.py` + `tools/check_imports/scan.py` — enforcement
  4. `framework/architecture/` — answers the three questions (readable,
     depends, blast_radius); does not know about workflow
  5. `docs/implement/<module>/STATE.yaml` — workflow state; written by CLI
  6. `docs/implement/templates/*` — template shape, not authoritative

If a new requirement contradicts the YAML, escalate to ac-designer. If a
new requirement contradicts a role's hard rules, rewrite the role prompt
through a normal change (this is a governance change, not silent).

## 7. Out of scope for this policy

This file does NOT cover:

  - product intent, product scope, non-goals — those live in
    `architecture/contracts/*.yaml` `description:` fields and in
    (forthcoming) intent docs at `docs/intent/`
  - implementation details (algorithms, data structures, test fixtures)
  - deployment, infrastructure, observability, CI provider

Those are separate surfaces; this file only defines how agents work.

## 8. Quick reference

  - "What may this module read?" → `python -m framework.architecture.cli readable <module>`
  - "What may this module depend on?" → `python -m framework.architecture.cli depends <module>`
  - "Who is affected if X changes?" → `python -m framework.architecture.cli impact <contract>`
  - "What is the state of capability X?" → `python -m tools.implement.state show <module> <cap>`
  - "Does module M violate boundaries?" → `python -m tools.check_imports <module>`
  - "Run all checks" → `python -m unittest discover -s tests -t . && python -m unittest framework.architecture.tests.test_framework`