# Repository policy for AI coding agents

This file is the owner-facing policy for every AI agent that touches this
repository. Product intent, contract surface, and architecture rules live
in their own files (`architecture/`, `framework/architecture/`); this file
defines how agents should work.

## 1. Five roles, one Owner

| Role | When active | What it does |
|---|---|---|
| **Owner** | always (you) | one-line decisions at the capability gates; nothing else |
| **ac-designer** | architecture changes | edits `architecture/contracts/`, `architecture/modules/`; never reads implementation |
| **module-designer** | planning a module | writes `docs/implement/<module>/PLAN.md` + Capability Cards; never writes code |
| **developer** | implementing a capability | writes `modules/<module>/**` + tests + Implementation Manifest; one capability per spawn |
| **reviewer** | auditing a capability (full mode) | produces 4-score Review Record; one capability per spawn |

The dispatcher (main session) mediates between Owner and the four
subagents; it is the only role that talks to you. ac-designer is a
prefix-invoked role; module-designer / developer / reviewer are spawned
subagents (see `.claude/agents/<role>.md` for each role's prompt).
Only the dispatcher calls the state CLI; developer and reviewer report
artifacts and findings without changing STATE.yaml.

## 2. Two modes per capability

  - **mvp** — developer writes the capability; reviewer is skipped;
    state recorded as `mvp_developed`. Use when: prototyping or validating
    the contract surface before committing to it.
  - **full** — developer writes; reviewer audits; state recorded as
    `fully_approved` on reviewer APPROVED.

Owner decides the mode when the Capability Card is prepared. Default `full`.

**Only `fully_approved` makes a capability usable.** No other module may
build on a `pending`, `mvp_developed`, `changes_requested` or `abandoned`
capability — there is no yellow flag and no warning pass. An MVP is never
promoted in place; there is no edge from `mvp_developed` to
`fully_approved`.

**An MVP is the foreword to the full implementation, not a throwaway.**
Its code is disposable — it was never reviewed, so it has no error
handling and no edge cases — but what it learned is what the full run
inherits. So `mark-mvp` requires a Manifest carrying a `## discovery`
section:

  - `question` / `answer`   what the spike was for, and what turned out
  - `surprised`             anything that did not match the Card/contract
  - `keep`                  assets the full run inherits as-is
  - `discard`               code the full run must NOT inherit
  - `known_gaps`            what the full run still has to build

`keep` and `discard` are a pair on purpose: an unreviewed prototype that
leaks into production is the usual way a spike becomes a liability.

Turning an MVP into something real is a four-step path, and the middle
step is what makes the knowledge survive:

```
retry <m> <cap> --mode full
  → read the Manifest's discovery
  → module-designer folds it into a revised Card   ← the handoff
  → Owner approves → developer builds from the revised Card
```

The MVP ran in a different agent session whose memory is gone. The revised
Card is where its findings have to live, so a developer never inherits
prototype code whose intent nobody wrote down.

Full-mode review keeps four scores: contract conformance (including spec
drift), boundary, test coverage, and implementation quality. Quality covers
explicit errors, bounded timeouts/retries where relevant, cleanup,
readability, and useful types; it does not require unrelated machinery.

## 3. Isolation layers (module boundary is hard)

A module may read its own tree, `architecture/**`, and what its own
`module.yaml` grants through `readable_extra`. Everything else is denied.
Four layers back that up, and they are not equally strong:

  1. **Declared read scope (policy, not enforcement).** Each role's
     `.claude/agents/<role>.md` declares an exact allow-list of paths, and
     the dispatcher copies it into the spawn prompt. This environment does
     not register per-role subagents, so a subagent runs with the ambient
     tool permissions and this layer cannot be mechanically enforced. It is
     a stated obligation the role is held to, not a wall.
  2. **Audited write scope (enforced).** `python -m tools.implement.scope
     <module> --capability <cap> --base <commit>` compares the files the run
     left behind against what that module may write. It is the layer that
     actually holds, because a run that writes outside its own tree is
     visible afterwards even when it was never stopped.
  3. **AST import scanner.** `python -m tools.check_imports <module>`
     walks every `.py` under `modules/<module>/` and resolves each import to
     a repo path, then asks the framework (`check_read`) whether the
     importing module may read it. Denials are reported as
     `CONTRACT_INSUFFICIENT` when the fix is to declare the dependency, and
     `BOUNDARY_VIOLATION` otherwise.
  4. **Implementation Manifest declaration.** Developer must write
     `cross-module imports in new code: NONE` in the manifest; reviewer
     re-runs the scanner and rejects on a false declaration.

### The one legitimate cross-module import

Modules need each other's capabilities, so the boundary cannot be absolute.
The route is a **declared public surface**:

```yaml
# provider: modules/<provider>/api/ holds only the contract surface
depends_on:
  - contract: <provider>-api
    uses: [<capability id>]

# consumer
readable_extra:
  - modules/<provider>/api/**
```

`from modules.<provider>.api.<x> import y` is then legal, and
`modules/<provider>/impl/**` stays locked. Both declarations are required:
a grant without a matching `depends_on` is reported as
`CONTRACT_INSUFFICIENT`, so `readable_extra` cannot become a back door
around the contract. The authoritative allow-list for any module is
`python -m framework.architecture.cli readable <module>`.

## 4. State is recorded, not narrated

Per-capability state lives in `docs/implement/<module>/STATE.yaml` and is
written only by `python -m tools.implement.state <cmd>`. The five states
  and the transitions between them are validated by the CLI; agents and
  Owner never hand-edit STATE.yaml.

States:

  - `pending`              a developer owes work on this
  - `mvp_developed`        MVP done — not usable by any other module
  - `changes_requested`    reviewer rejected
  - `fully_approved`       reviewer approved — **the only consumable state**
  - `abandoned`            owner closed this capability (terminal)

`pending` carries exactly one meaning: a developer owes work. A fresh
registration and a reopened pass both land there, and nothing else does —
so an interrupted run is never ambiguous between "not started" and
"finished, awaiting review".

The aggregated `module_state` is computed from per-capability states and
written by the CLI on every save.

An interrupted developer or reviewer run does not create a new state. To
resume, the dispatcher reads STATE, the approved Card, existing source and
tests, the Manifest, and any Review Record. Incomplete developer work goes
back to developer; incomplete review goes back to reviewer. A complete review
awaiting Owner's decision returns to the review gate, provided the code has
not changed since review. Never approve from a partial Record or reset files
merely because a run was interrupted. `changes_requested` is reopened with
`python -m tools.implement.state retry <module> <cap>`; an MVP that turned
out to be needed for real is reopened with
`retry <module> <cap> --mode full`.

If developer or reviewer finds a contradiction in the approved contract or
Card, it writes `<capability>.design-blocker.md`, returns `DESIGN_BLOCKED`,
and stops the affected work. This is not `changes_requested`; STATE remains
unchanged. Dispatcher routes contract/boundary/dependency issues to
ac-designer and Card/plan issues to module-designer, obtains Owner approval
for changed design, records the resolution, and resumes implementation.
Reviewer audits again after a design change. An open Design Blocker takes
priority over ordinary interruption recovery.

## 5. Two gates per capability (Owner intervenes twice in the normal path)

  1. **Card gate.** Owner reads the Capability Card (~10 lines) and
     chooses: `go / redo / abandon`. This decides mode.
  2. **Completion gate.** In full mode, the dispatcher checks the Manifest
     and automatically dispatches reviewer. Owner then reads the Review
     Record one-liner (`verdict=APPROVED scores=c=OK b=OK t=OK q=OK`) and
     chooses `approve / changes / abandon`. In MVP mode, Owner reads the
     Manifest result and chooses `accept / changes / abandon`.

Promote mode skips the Card gate and dispatches reviewer on the existing
implementation before the completion gate.

In all cases, the Owner-facing prompt is a single line of ≤ 100 words.
Background and rationale stay in the agent prompts and CLI output, never in
Owner-facing messages.

## 6. Authority order

When sources conflict, use this order:

  1. `architecture/contracts/*.yaml` + `architecture/modules/*/module.yaml`
     — public surface, single source of truth
  2. `.claude/agents/<role>.md` — role behavior, hard rules per role
  3. `tools/implement/state.py` + `tools/implement/scope.py` +
     `tools/check_imports/scan.py` — enforcement
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
  - "Register an approved Capability Card" → `python -m tools.implement.state register <module> <cap> --mode <full|mvp>`
  - "Does module M violate boundaries?" → `python -m tools.check_imports <module>`
  - "Did this run write outside its module?" → `python -m tools.implement.scope <module> --capability <cap> --base <commit>`
  - "Run all checks" → `python -m unittest discover -s tests -t . && python -m unittest framework.architecture.tests.test_framework`
