# CLAUDE.md

Repository instructions for Claude Code.

## Default: use the existing architecture

Normal development happens **inside** the architecture that is already
defined. Do not redesign it while implementing a feature.

The architecture is declared in YAML and is the source of truth:

- `architecture/contracts/<name>.yaml` — public contracts
- `architecture/modules/<name>/module.yaml` — modules and their declared dependencies

When you need to know what is allowed, ask the framework; do not infer it.
Run from the repo root (`ARCHCTL="python3 -m framework.architecture.cli"`):

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

## Module isolation is enforced, not advisory

- You may read your own module's implementation and `architecture/**`.
- You may **not** read another module's implementation, and you may not read
  `framework/**` from module code.
- If you need something that no contract provides, you get
  `CONTRACT_INSUFFICIENT` / `BOUNDARY_VIOLATION`. **The fix is to extend the
  contract — never to read the other module's code.**

## When to stop and use the Architecture Designer role

Do **not** silently redesign. Stop, explain what would need to change, and
recommend entering the Architecture Designer role if the request involves:

- creating or removing a module
- changing a module boundary, or its source root
- adding a cross-module dependency
- changing a public contract (adding, removing, or redefining a capability)
- a refactor that changes system structure

Small, local changes — a new function inside a module, an internal
refactor that keeps the module's contract and read set unchanged, a bug fix,
a new test — need no architecture review. Just make them.

## Architecture Designer role

Enter this role **only** when explicitly invoked for the events listed above.
It is a design role, not an implementation role.

This environment cannot register custom subagents (the subagent enum is
injected at session start from system context, not read from
`.claude/agents/`). To invoke: prefix your prompt with the role name - for
example "用 ac-designer 处理这个" or "enter ac-designer role" - and the
default agent will read `.claude/agents/ac-designer.md` and behave as that
role for the rest of the conversation.

When invoked:

1. Read the current contracts, module declarations, and relevant public docs.
2. Understand the requested change and why it is needed.
3. Decide whether an architecture change is actually required. **If the
   existing architecture is sufficient, say so instead of redesigning it.**
4. If a change is required, identify affected modules, affected contracts,
   dependency changes, boundary changes, and downstream impact — using
   `$ARCHCTL impact`, not guesswork.
5. Discuss the smallest reasonable design with the user before editing.
6. Prefer adapting the existing architecture over new abstractions.

Constraints in this role:

- The Architecture Framework must stay independent: `future workflow → framework`.
  The framework never depends on or contains workflow logic.
- Do not introduce task, spec, reviewer, handoff, or workflow-state concepts
  into the Architecture Framework. It models modules, contracts, dependencies,
  boundaries, and impact — nothing else.
- Do not implement normal business features in this mode.

Optimise for isolated AI-agent development, and keep asking:

- Does this make implementation easier for an agent working on one module?
- Does it reduce how much unrelated code that agent must inspect?
- Does it make dependency and impact analysis clearer?
- Is this abstraction actually necessary for *this* project?

Keep architecture changes minimal, explicit, and traceable in the YAML.
