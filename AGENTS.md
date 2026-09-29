# Repository policy for AI coding agents

**Constraints that hold for every role, in every session.** Loaded beside
`CLAUDE.md` as project instructions, and inherited by spawned subagents.

`CLAUDE.md` says what to do in this repository and how work is routed here.
This file says what is true regardless of who is doing it. The split is not
cosmetic: a rule that appears in both files will drift, because editing one
does not touch the other. `tests/test_instruction_files.py` fails if it does.

**Role-specific process is not here.** How the dispatcher runs the gates, what
a Manifest must contain, what a reviewer scores — that is the role's own file
under `.claude/agents/`, and putting it here as well meant maintaining it
twice. This file is loaded into every subagent, including ones that must never
touch that process; a 200-line copy of it costs the tester as much as the
dispatcher.

Product intent, contract surface, and architecture rules live in their own
files (`architecture/`, `framework/architecture/`).

## 1. Who does what

| Role | What it does | Prompt |
|---|---|---|
| **Owner** | one-line decisions at the capability gates; nothing else | — |
| **dispatcher** (main session) | mediates between Owner and the subagents; the only role that talks to you | — |
| **ac-designer** | edits `architecture/contracts/`, `architecture/modules/`; never reads implementation | `.claude/agents/ac-designer.md` |
| **module-designer** | writes the module PLAN and Capability Cards; never writes code | `.claude/agents/module-designer.md` |
| **tester** | writes the tests, from the Card; **never reads or writes implementation** | `.claude/agents/tester.md` |
| **developer** | writes `modules/<module>/**` + Manifest; never writes or edits tests | `.claude/agents/developer.md` |
| **reviewer** | audits a capability (full mode); one capability per spawn | `.claude/agents/reviewer.md` |

The order is **tester → developer → tester (if needed) → reviewer**, and the
tester runs first for a structural reason, not a stylistic one: a developer who
writes its own tests asserts what it built rather than what was specified. The
tester's read scope excludes `modules/<module>/**`, and the developer cannot
edit the test file, so neither can revise the specification to fit the result.
Both halves are enforced by the audited write-scope layer with `--role`.

Only the dispatcher calls the state CLI. Every other role reports artifacts
and findings without changing `STATE.yaml`.

## 2. Modes, states, and who may consume what

Two modes per capability, and the Owner decides which at the Card gate:

  - **mvp** — developer writes; reviewer is skipped; state is `mvp_developed`.
  - **full** — developer writes; reviewer audits; state is `fully_approved` on
    APPROVED. This is the default.

Capability states are `pending`, `mvp_developed`, `changes_requested`,
`fully_approved`, `abandoned`. Two of those are load-bearing beyond this file:

- **Only `fully_approved` is consumable.** No other module may build on a
  `pending`, `mvp_developed`, `changes_requested` or `abandoned` capability.
  There is no yellow flag and no warning pass.
- **An MVP is never promoted in place.** There is no edge from `mvp_developed`
  to `fully_approved`; reopening for real is `retry <m> <cap> --mode full`,
  which walks both gates again.

An MVP is optional, and its code *and its tests* are disposable — that is the
premise of the mode. What survives is its `## discovery` section, which the
module-designer folds into a revised Card; that handoff is the whole reason the
mode is cheap rather than wasteful.

The transitions, the evidence each one demands, and the gates themselves are
in `.claude/agents/dispatcher.md` and enforced by the CLI. An agent that needs
to know what a gate requires reads that file; it does not need the rule in its
context to respect it.

**`STATE.yaml` is written only by the state CLI, and by no hand.** Five states
and the transitions between them are validated; agents and Owner never
hand-edit it. Every command in this repository is `./bin/python -m ...`.

## 3. Isolation layers (module boundary is hard)

A module may read its own tree, `architecture/**`, and what its own
`module.yaml` grants through `readable_extra`. Everything else is denied.
Four layers back that up, and they are not equally strong:

  1. **Declared read scope (policy, not enforcement).** Each role's
     `.claude/agents/<role>.md` declares an exact allow-list of paths. This
     environment does not register per-role subagents, so a subagent runs with
     the ambient tool permissions and this layer cannot be mechanically
     enforced. It is a stated obligation the role is held to, not a wall.
  2. **Audited write scope (enforced).** `./bin/python -m tools.implement.scope
     <module> --capability <cap> --role <tester|developer> --base <commit>`
     compares the files the run left behind against what that role may write.
     It is the layer that actually holds, because a run that writes outside
     its own tree is visible afterwards even when it was never stopped.
     `--role` is what keeps the two halves apart: the tester may write the
     test file but not the source, the developer the reverse. Neither can
     revise the other's.
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

Every read scope in this repository is a list of **paths in this repo**. It
bounds what a role may learn *from the artifact it is being measured against*,
and it says nothing about the rest of the world — see §4.

## 4. External facts

This repository describes a system that talks to a blockchain, so most of what
a Card or a contract asserts about the outside world is a **mutable fact**:
chain IDs, deployment addresses, ABIs, pool keys, Hooks, Tokens, RPC
capabilities, block timing, event shapes, and anything a vendor documents.
Those rot. A contract that states one without saying how it was established is
a contract that will be quietly wrong later.

### The read scope does not forbid research

**Public material is in scope for every role**, without asking and without
listing it: official documentation, a protocol specification, a chain's own
reference, a vendor API reference, a published postmortem. Use `WebSearch` and
`WebFetch`.

This is not a loophole, and the test for it is exact: the isolation rule exists
so a role **cannot learn the answer from the thing it is being measured
against**. Public documentation cannot leak that answer, because the publisher
does not know what your Card says. `modules/<m>/impl/calendar.py` can. If
reading it hands you the answer to what you are building or specifying, it is
forbidden; if it hands you facts about the outside your specification has to
survive contact with, it is required.

### Source hierarchy

Not all sources are equal, and the difference is recorded:

  - **Verification** — official source, official documentation, and
    block-pinned chain reads. A chain read means a read at a named block, not
    at `latest`.
  - **Cross-check only** — third-party pages, aggregators, forums, tutorials,
    blog posts. Useful for finding the official page. Never sufficient alone.
    A forum answer from a vendor employee is a cross-check unless the vendor
    documents it.

### Record the coordinates, not just the link

A URL is not a citation for a fact that can change under you. Record, in the
same place the fact is written down:

```
source:        the official URL or the exact command run
retrieved at:  when
chain id:      which chain
block:         block number or hash the read was pinned to
code hash:     when the fact is about deployed bytecode
```

For a fact read from a chain, `block` is not optional. The same query at
`latest` tomorrow may return something else, and without the block the claim
cannot be re-checked by anyone — including you, next week.

### `UNKNOWN` is a legal answer

**If verification fails, return `UNKNOWN` or block the work. Never guess, and
never copy another chain's value, another provider's convention, or a
plausible-looking number.**

This is the rule that matters most, and it exists because of what happens
without it. A role that is told to research but has no legal way to fail will
fill the gap with a guess — and a guess that gets written into a fixture, a
Card, or a contract becomes **permanently indistinguishable from a fact**. On
the first real run of this workflow, `SESSION_HOUR_UTC = 21` was invented as a
test fixture, restated as a rule in a Capability Card, and ratified at an Owner
gate — three documents later it was an apparent fact with no source anywhere,
and a whole exchange calendar was researched to justify it. It had no origin
at all. `UNKNOWN` is a terminal state that forces the gap to a human; a guess
is a terminal state that hides it.

So: **a fixture is a test input, never evidence about the world.** Synthetic
data is legitimate and often necessary — it is what makes a test hermetic. It
stops being legitimate the moment anyone cites it as a reason to believe
something about the outside world, and no number of passing tests changes that.
Tests prove the implementation matches the specification. They do not prove the
specification matches reality.

### Two more rules that came with the research rule

  - **Names are not evidence.** Symbols, tickers, display names and IDs are
    metadata. Verify the underlying thing — the address, the code hash, the
    chain — and treat an unknown settlement behaviour as ineligible rather than
    assuming the friendly name tells you anything.
  - **Absence of evidence is not a pass.** Missing credentials, an unreachable
    endpoint, or unavailable integration evidence is a failure state to report,
    never a condition to work around by assuming.

### Where a finding goes

Research never widens a role's authority. If looking things up shows the
contract is silent, wrong, or under-specified, that is a **Design Blocker** to
ac-designer — the same route as any other discovery. Finding a gap is not
permission to fill it yourself.

## 5. The interpreter

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

This file and `CLAUDE.md` are both project instructions and neither is
authoritative over the other: they are partitioned by subject, and a rule
belongs in exactly one. If a new requirement contradicts the YAML, escalate to
ac-designer. If a new requirement contradicts a role's hard rules, rewrite the
role prompt through a normal change (this is a governance change, not
silent).

## 7. Out of scope for this policy

Not covered here, and deliberately: product intent and non-goals
(`architecture/contracts/*.yaml` `description:` fields), implementation
details, and deployment or CI. Those are separate surfaces.

## 8. Quick reference

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
