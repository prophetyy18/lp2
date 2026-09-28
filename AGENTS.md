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
  → archives the MVP Manifest to <cap>.mvp-manifest.md
  → module-designer reads that discovery and folds it into a revised Card  ← the handoff
  → Owner approves → developer builds from the revised Card
```

The MVP ran in a different agent session whose memory is gone. The revised
Card is where its findings have to live, so a developer never inherits
prototype code whose intent nobody wrote down. The prototype's code does
stay in the tree, so the developer is told what it is: the Card is the
specification, the prototype is not, and existing tests are evidence rather
than requirements.

An MVP is optional. `full` is the default mode and a fresh full
implementation never looks for one.

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
  2. **Audited write scope (enforced).** `./bin/python -m tools.implement.scope
     <module> --capability <cap> --base <commit>` compares the files the run
     left behind against what that module may write. It is the layer that
     actually holds, because a run that writes outside its own tree is
     visible afterwards even when it was never stopped.
  3. **AST import scanner.** `./bin/python -m tools.check_imports <module>`
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
`./bin/python -m framework.architecture.cli readable <module>`.

## 4. State is recorded, not narrated

Per-capability state lives in `docs/implement/<module>/STATE.yaml` and is
written only by `./bin/python -m tools.implement.state <cmd>`. The five states
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

A module also carries a three-value summary, and it is a **summary, never a
gate**:

  - `not_started`  nothing worked on yet (all `pending`, or none declared)
  - `in_progress`  work has started and has not landed
  - `complete`     every capability is `fully_approved`

It is computed from the capability rows and printed as a comment by
`state show`; it is deliberately **not stored** in `STATE.yaml`. Three
values, because three is what it can say without repeating the rows
underneath it. Its old six-value form encoded details the rows already
carried — `rework` restated `changes_requested` (whose reason codes say
more), `partial_mvp` restated `mvp_developed` — and `partially_complete`
claimed a granularity that does not exist: **consumption is per capability,
so a module is never a consumable unit.** Whether another module may
depend on this one is answered by `state upstream`, per capability.

Two consequences of the three-value set, so they are not mistaken for
bugs: a module whose capabilities were all abandoned reports
`in_progress` (there is no fourth value for "started, then closed"), and
adding a capability to a `complete` module drops it back to `in_progress`.

An interrupted developer or reviewer run does not create a new state. To
resume, the dispatcher reads STATE, the approved Card, existing source and
tests, the Manifest, and any Review Record. Incomplete developer work goes
back to developer; incomplete review goes back to reviewer. A complete review
awaiting Owner's decision returns to the review gate, provided the code has
not changed since review. Never approve from a partial Record or reset files
merely because a run was interrupted. `changes_requested` is reopened with
`./bin/python -m tools.implement.state retry <module> <cap>`; an MVP that turned
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

Because STATE deliberately has no blocker state, the file is the whole
record, and the state CLI enforces it: `mark-mvp`, `mark-changes` and
`mark-approved` all refuse while `<capability>.design-blocker.md` exists, so
a fixed-but-forgotten blocker cannot silently keep a capability from ever
completing. Resolution is recorded in the file's `resolution:` field, then
the file is **renamed** to `<capability>.design-blocker.resolved.md` — never
deleted, so the reasoning stays readable. `retry` is not gated, so a blocker
cannot deadlock the work it is blocking.

## 5. Two gates per capability (Owner intervenes twice in the normal path)

  1. **Card gate.** Before any code exists. The dispatcher presents the Card
     in the form `docs/implement/templates/DECISION_PROMPT.template.md`
     gives — signature, the four test-plan lines, and what the Card refuses
     to decide — and Owner chooses `go / redo / abandon`. This decides mode,
     and it is the only place mode is decided. Owner sees the Card's test
     **plan**, not tests: nothing has been written yet, and the plan is far
     cheaper to judge than a pile of finished tests. The Card itself is
     30+ fields and is the subagent's input, not the Owner's reading.
  2. **Completion gate.** In full mode, the dispatcher checks the Manifest
     and automatically dispatches reviewer. Owner then reads the Review
     Record one-liner (`verdict=APPROVED scores=c=OK b=OK t=OK q=OK`) and
     chooses `approve / changes / abandon`. In MVP mode, Owner reads the
     Manifest result and chooses `accept / changes / abandon`.

Both transitions are recorded by the state CLI and neither is a hand-edit:
`mark-approved` validates an APPROVED Review Record, `mark-changes`
validates a CHANGES_REQUESTED one plus its reason codes, and `mark-mvp`
validates a Manifest with a `## discovery` section. All three refuse while
a design blocker for the capability is open.

`mark-approved` and `mark-changes` take **both** artifacts, not just the
Review Record. Full mode is the only path to `fully_approved` — the one
state another module may consume — so it used to have the weaker evidence
requirement, which was backwards. They now also require:

  - a Manifest (canonical path, header tied to the capability, same as
    `mark-mvp` checks it);
  - a Review Record no older than that Manifest, so a review cannot speak
    for code written after it. This is an mtime ordering check, not proof
    that the code is unchanged;
  - **every guarantee the contract declares is mapped to a test that
    exists.** `mark-approved` reads the capability's `errors[]` and
    `behavior` from the contract — not from the Card, and not from the
    Manifest — and requires the Manifest's `tests by obligation:` block to
    name a test method for each one, with that method present in the test
    file. A declared error code is a promise to a consumer module that
    does not exist yet; an untested one is the commonest way that promise
    is broken, and it is invisible to every check that only reads documents.
  - **a test run the reviewer performed**: `- tests run: <N> passed,
    <M> skipped`, with `N ≥ 1` and `M == 0`. A skipped test still leaves
    the file on disk, still reads as coverage, and still exits 0, so four
    skipped tests passed every other check here. Zero skips is the rule
    because a skip is unreviewable — "we cannot exercise this yet" is what
    `mode: mvp` is for;
  - a non-empty tree: at least one `.py` under the module's declared
    `source:` and at least one test file for the module under `tests/`. Four
    `OK` scores over a module with no code describe nothing.

Test file names come from one rule, not from prose: hyphens and dots both
become underscores, so `market-data` / `series.get` is
`tests/test_market_data_series_get.py`, and `./bin/python -m tools.implement.naming
<module> <capability>` prints the path and the exact command to run it. Ask
that rather than composing the name — the write-scope audit matches on the
same rule, so a name assembled any other way reads as a scope violation.

None of that catches an agent that fabricates both documents. A document is
all this CLI ever sees, so its checks find *inconsistency between artifacts*,
not a work that did not happen. `tools/implement.scope` — the write-scope
audit run before the reviewer — is the layer that proves a run actually
touched files.

The two checks that read the *contract* rather than a document are the
closest this comes to the code itself, and they are the reason
`fully_approved` is not just a filing convention: what a consumer is entitled
to assume is what the contract declares, and `mark-approved` holds the
implementation to that list. The remaining gap is unchanged and is recorded
in the code: an agent that writes a consistent contract, Manifest, test file
and Review Record — all four, all agreeing, none of it tested — still passes.

`abandon` covers the fourth reviewer outcome, but distinguishes two cases
that share the command: with `--review` it records a reviewer's `ABANDON`
verdict (the work is fundamentally off-target, which may point at the Card
rather than the code); without it, it is purely Owner's decision. The flag
stays optional because closing a capability that was never reviewed is an
ordinary thing for Owner to do.

There is no promote mode. An MVP is not usable by another module and is
never promoted in place: the Owner reopens it with
`retry <module> <cap> --mode full`, which keeps the existing source and
tests, and it must then walk the full Card and completion gates.

In all cases, the Owner-facing prompt is a single line of ≤ 100 words.
Background and rationale stay in the agent prompts and CLI output, never in
Owner-facing messages.

## 6. The interpreter

Every command in this repository is `./bin/python -m ...`, never `python -m
...`. That is not a style preference:

  - There is no `python` on this machine's PATH.
  - The shell that runs these commands is neither a login nor an interactive
    shell and reads no profile, so `conda init` and `conda activate` do not
    reach it — and the developer and reviewer subagents run their commands
    in exactly that shell. An interpreter that only exists after activation
    is an interpreter the workflow cannot rely on.

`bin/python` is a two-line shim that execs the `robinhood-lp` environment
(Python 3.12). Run commands from the repository root: `-m` resolves `tools.*`
and `framework.*` from the working directory. To use a different interpreter,
set `LP2_PYTHON` rather than editing the shim:

```bash
LP2_PYTHON=/path/to/python ./bin/python -m tools.implement.state ...
```

The shim exits 127 with a message rather than failing obscurely if the
environment is missing.

The workflow tooling itself needs only PyYAML. The `robinhood-lp` environment
additionally carries what module code needs (pandas, numpy, pydantic), so a
developer implementing a capability is working against the same interpreter
the tooling runs on.

## 7. Authority order

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

## 8. Out of scope for this policy

This file does NOT cover:

  - product intent, product scope, non-goals — those live in
    `architecture/contracts/*.yaml` `description:` fields and in
    (forthcoming) intent docs at `docs/intent/`
  - implementation details (algorithms, data structures, test fixtures)
  - deployment, infrastructure, observability, CI provider

Those are separate surfaces; this file only defines how agents work.

## 9. Quick reference

  - "What may this module read?" → `./bin/python -m framework.architecture.cli readable <module>`
  - "What may this module depend on?" → `./bin/python -m framework.architecture.cli depends <module>`
  - "Who is affected if X changes?" → `./bin/python -m framework.architecture.cli impact <contract>`
  - "What is the state of capability X?" → `./bin/python -m tools.implement.state show <module> <cap>`
  - "May I start this capability?" → `./bin/python -m tools.implement.state upstream <module> [<cap>]` (exit 0 = green)
  - "Who does capability X block?" → `./bin/python -m tools.implement.state dependers-of <cap>`
  - "Register an approved Capability Card" → `./bin/python -m tools.implement.state register <module> <cap> --mode <full|mvp>`
  - "Does module M violate boundaries?" → `./bin/python -m tools.check_imports <module>`
  - "Did this run write outside its module?" → `./bin/python -m tools.implement.scope <module> --capability <cap> --base <commit>`
  - "What files does this capability use?" → `./bin/python -m tools.implement.naming <module> <cap>`
  - "Run all checks" → `./bin/python -m unittest discover -s tests -t . && ./bin/python -m unittest framework.architecture.tests.test_framework`
