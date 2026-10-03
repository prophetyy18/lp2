# CLAUDE.md

@AGENTS.md

**What to do in this repository, and how work is routed here.** The
constraints that hold regardless — module isolation, external facts, the
interpreter, the authority order — are in `AGENTS.md`, imported above. They are
not repeated below; a rule stated in both files is a rule that will drift.

**State of the architecture: nothing is declared.** The directories
`architecture/contracts/` and `architecture/modules/` do not exist, and
`architecture/schemas/` holds only its README, so every command below answers
about an empty architecture and `validate` passes vacuously.
This is deliberate as of 2026-10-03, not a broken checkout. The twelve
`robinhood-*` modules that used to be here were mapped in from a different
repository, had no implementation, and cited 35 task numbers that resolve to
no task list; they were withdrawn rather than repaired. The measured chain
reads that survived are in `docs/design/ROBINHOOD-CHAIN-OBSERVATIONS.md`.

So there is nothing to develop inside yet. **Establishing what this repository
is for comes before the first module**, and that is an Owner decision this
file cannot make. When declarations do exist they are the source of truth:

- `architecture/contracts/<name>.yaml` — public contracts
- `architecture/modules/<name>/module.yaml` — modules and their declared dependencies
- `architecture/schemas/<name>.yaml` — the shape behind a declared type

When you need to know what is allowed, ask the framework; do not infer it.
Run from the repo root (`ARCHCTL="./bin/python -m framework.architecture.cli"`):

```bash
$ARCHCTL readable <module>                 # what may I read?
$ARCHCTL check-paths <module> <path>...    # is this path allowed?
$ARCHCTL depends <module>                  # what may I depend on?
$ARCHCTL consumers <contract>              # who depends on this?
$ARCHCTL impact <contract|module>          # who breaks if this changes?
$ARCHCTL validate                          # is the architecture still sound?
```

Add `--json` for machine-readable output. Design rationale:
`framework/architecture/README.md`.

## Repository policy

Read `AGENTS.md` — it is already in your context. The short version, so you
know what you are reading:

- **A module may not read another module's implementation.** If you need
  something no contract provides, you get `CONTRACT_INSUFFICIENT` /
  `BOUNDARY_VIOLATION`, and the fix is to extend the contract — never to read
  the other module's code. (`AGENTS.md` §3)
- **Most of what a contract asserts about the outside world is a mutable
  fact, and failing to verify one is an allowed outcome, not a gap to fill.**
  Never guess, never copy a value from another chain or provider, and never
  cite a test input as evidence about the world. (`AGENTS.md` §4)
- **Never hand-edit `STATE.yaml`**, and run every command as
  `./bin/python -m ...`. (`AGENTS.md` §2, §5)

Isolation bounds what you may read **in this repository**. It does not bound
what you may know — public documentation cannot tell you what a Card in this
repo says, so reading it cannot leak the answer you are being measured on.

> **`AGENTS.md` reaches you through the `@AGENTS.md` import at the top of this
> file.** An earlier version of this note pointed at a user-level plugin
> setting instead; no such plugin exists, so those constraints were in no
> context at all. Two things follow, both measured rather than assumed:
>
> - **A subagent that receives this file receives `AGENTS.md` with it.** A
>   `general-purpose` subagent does. The built-in `Explore` agent receives
>   neither this file nor a `git status` snapshot, so a dispatch that relies on
>   inherited rules must name the subagent type it needs.
> - **Verify after restarting.** The import is read when the session's
>   instructions are assembled; a session already running will not pick it up.
>   `/context` shows what actually loaded.

## When to stop and use the Architecture Designer role

Do **not** silently redesign. Stop, explain what would need to change, and
recommend entering the Architecture Designer role if the request involves:

- creating or removing a module
- changing a module boundary, or its source root
- adding a cross-module dependency
- changing a public contract (adding, removing, or redefining a capability)
- a refactor that changes system structure
- **a contract whose vocabulary belongs to a different domain than this
  system**, or two contracts that appear to cover the same capability
- **a module that declares no dependencies but whose data can only come from
  somewhere** — an ingestion module that cannot say where its data comes from
  is missing a dependency, not declaring independence
- **a declaration that no current consumer needs** — a capability, type,
  vocabulary or citation whose only support is another declaration. Existence
  is a hypothesis, not a warrant; the method is in
  `docs/design/DECLARATION-PROVENANCE.md`, and it is loaded automatically when
  you open anything under `architecture/` or `docs/implement/`.

The last three survive review unnoticed, because nothing is being changed — a
contract is simply wrong about the world, duplicated, or borrowed from
somewhere else, and every Card built on it inherits the error. Four
retirements in this repository were exactly that shape (`Bar`, the whole
`market-data` contract, 35 borrowed task numbers, and the twelve
`robinhood-*` modules, which were mapped in from a different repository on
2026-10-03 and had zero implementation) and none of them tripped a tool.
Worked examples are in the method document.

Small, local changes — a new function inside a module, an internal refactor
that keeps the module's contract and read set unchanged, a bug fix, a new
test — need no architecture review. Just make them.

## Architecture Designer role

Enter this role **only** when explicitly invoked for the events listed above.
It is a design role, not an implementation role. **It may not write
`architecture/**` without Owner authorisation.**

  - **Spawned as a subagent** — `ac-designer` is registered in this
    environment's agent list, so `Agent(subagent_type: "ac-designer", ...)`
    works. The dispatcher uses this for blocker investigations, because a
    contract decision made in the dispatcher's own context is not independent:
    the dispatcher is the role that has been reading implementation-adjacent
    material. Independence comes from not inheriting the conversation, which
    is already guaranteed — **not** from omitting instruction files.
  - **Prefix-invoked, in-conversation** — type "用 ac-designer 处理这个" or
    "enter ac-designer role" and the default agent reads
    `.claude/agents/ac-designer.md` and behaves as that role.

A spawned agent already receives this file, `AGENTS.md`, and a `git status`
snapshot. Do **not** paste their rules into the dispatch prompt — name the
specific rule a stage needs, if any. It is loaded; re-sending it costs context
and creates a second copy that can drift from the first.

When invoked: read the current contracts and module declarations; understand
what is being asked and why; **decide whether an architecture change is
actually required, and if the existing architecture is sufficient, say so
instead of redesigning it**; use `$ARCHCTL impact` for the blast radius rather
than guesswork; discuss the smallest reasonable design with the Owner before
editing; prefer adapting what exists over new abstractions.

Constraints: the Architecture Framework stays independent — it models modules,
contracts, dependencies, boundaries and impact, and never gains a workflow,
task, spec, reviewer or handoff concept. Do not implement business features in
this mode. Keep changes minimal, explicit, and traceable in the YAML.

## Chinese writing

Write in Chinese, but **rewrite, do not translate sentence by sentence.**
Decide what a sentence has to say, then write it in Chinese order.

- **Terms.** Translate what has a settled Chinese word: 契约 (contract),
  能力 (capability), 依赖 (dependency), 边界 (boundary), 退役 (retired).
  Keep what has none: prompt, token, schema, fixture. Never translate on-chain
  field names (`sqrt_price_x96`, `feeGrowthGlobal0X128`) or code identifiers
  (`readable_extra`, `BEHAVIOR_UNITS`).
- **Forbidden.** 「对……进行 X」,「作为……」,「不仅……而且……」; the 「被」
  passive; 「进行了 / 实现了 / 完成了」; an abstract noun as subject with an
  adjective as the conclusion; a closing summary paragraph; a dash enclosing a
  list of English identifiers; overuse of 「因此 / 然而 / 此外 / 另外」.
- **One bold span per paragraph, at most.**
- **Check before finishing.** Translate the Chinese back to English. If it
  lands on `runs on` / `is compatible with` / `for use in` — a flavour the
  original did not have — it is translationese, so rewrite it.
- **Accuracy outranks fluency.** Version numbers, commands, error codes, file
  paths and block heights do not change. Do not invent first-hand experience.
  When accuracy and casual tone conflict, accuracy wins — and do not
  over-correct into slang, which is its own failure mode.
