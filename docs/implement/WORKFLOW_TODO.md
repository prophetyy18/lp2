# Module implementation workflow TODO

Review date: 2026-09-28. Discuss and handle these items one at a time.

- [x] 1. Make the workflow executable: register approved capability records and their modes through the CLI; fix the import scanner CLI's optional module argument (`nargs="?"`).
- [x] 2. Make state changes reflect completed gates: validate approval evidence in the state CLI, and update state after the Owner's decision.
- [x] 3. Add a production code quality criterion to developer and reviewer instructions, using the existing four-score review format.
- [x] 4. In full mode, dispatch the reviewer automatically after the developer gate checks pass; keep the Owner's card and final review decisions.
- [x] 5. Assign all STATE.yaml writes to the dispatcher and remove developer state CLI instructions.

Additional request:

- [x] Document how to resume interrupted developer, reviewer, and Owner gates without adding a new state; provide `retry` for a rejected capability.
- [x] Add a persistent design blocker report and routing for contract or Card defects discovered during development or review.

Review of 2026-09-28 (P0 items that blocked module execution):

- [x] Unblock cross-module consumption. `depends_on` was declared on 14 of 16
  modules but `check_imports` denied the only import that could satisfy it,
  so no cross-module capability could be implemented. The scanner now asks
  the framework (`check_read`) instead of re-implementing the boundary, and
  allows `modules/<upstream>/api/**` when the consumer both declares
  `depends_on` on a contract that upstream owns and grants the path via
  `readable_extra`. A grant without a matching `depends_on` is reported as
  `CONTRACT_INSUFFICIENT`, so `readable_extra` is not a way around the
  contract. No architecture YAML had to change: `check_read` already honoured
  these grants, and the validator only rejects grants covering a whole
  module tree.
- [x] Stop the scanner reporting a phantom pass. With no `modules/` tree the
  repo scan returned no findings and exit 0. A missing tree, a missing module
  source, and an undeclared implementation directory are now INFO notes
  (`--strict` promotes them); only real boundary findings are ERROR.
- [x] Make the reviewer spawn resolve to a genuinely different model.
      `MiniMax-M3[1m]` is the real 1M-context model id (picker label
      "MiniMax-M3"), not terminal markup. The Agent tool accepts only the
      `sonnet`/`opus`/`haiku`/`fable` aliases, which map through
      `ANTHROPIC_DEFAULT_*_MODEL` to M2.7 / M3 / M2.7-highspeed. So reviewer
      spawns with `model: "opus"` (-> `MiniMax-M3[1m]`) while developer and
      module-designer pass no `model` at all and inherit the session model
      `MiniMax-M3.1-Flash-Preview`, which no alias points at. Verified by
      real spawns: a raw MiniMax id is rejected, inheritance and `opus` both
      work.
- [x] Replace the unenforceable read-scope layer with an audited write-scope
  layer (`python -m tools.implement.scope`). Read scope stays declared policy
  because this environment does not register per-role subagents; write scope
  is measurable after the fact and is now checked before the reviewer runs.

Still open from the same review (P1, not started):

- [x] `promote` is gone. An MVP is not usable by any other module and is
      never promoted in place: there is no edge from `mvp_developed` to
      `fully_approved`, only `pending` (reopen) or `abandoned`. Owner reopens
      with `retry <module> <cap> --mode full`, which keeps the existing
      source and tests. This also removed the ambiguity that made `pending`
      two-valued — it now means only "a developer owes work", so an
      interrupted run is never confused between "not started" and "finished,
      awaiting review". The upstream gate is binary as a result: only
      `fully_approved` is green, `mvp_developed` is red, and the yellow-flag
      pass-through is gone from dispatcher, developer and the Card template.
- [x] `mark-mvp` now requires evidence, and the evidence has a purpose. It
      validates `--manifest` exactly as `mark-approved` validates `--review`
      (canonical path, file exists, header ties it to the capability) and
      additionally requires a `## discovery` section. An MVP is the foreword
      to the full implementation, so what it records is question / answer /
      surprised / keep / discard / known_gaps: the code is disposable, the
      findings are the reusable part. `retry --mode full` now routes through
      module-designer, which folds that discovery into a revised Card before
      any developer is dispatched — the MVP ran in an agent session that no
      longer exists, so the Card is the only place its findings can live.
      `keep`/`discard` are an explicit anti-leak pair. The dead `mark-mvp
      --mode` flag was removed, and the duplicated artifact-validation code
      is now one `_require_artifact` helper.
- [x] The full pass could not find the MVP's findings, and could not tell
      prototype code from its own. Two causes. First, `retry` left
      `rec.manifest` pointing at `<cap>.manifest.md`, which is the same path
      the full developer writes — so the full Manifest overwrote the
      `## discovery` section by the pass it was written for, and STATE then
      pointed at a file with no discovery in it. `retry` now archives to
      `<cap>.mvp-manifest.md`, clears `rec.manifest`, refuses if the MVP
      Manifest has gone, and refuses to clobber an existing archive.
      Second, developer.md only knew about *interrupted* runs; it had no
      rule for a tree holding an unreviewed prototype, so the three
      reasonable reactions (extend it / ignore it / be confused by its
      tests) were all compliant. It now distinguishes a prior reviewed pass,
      a disposable prototype, and an empty tree, and states that the Card —
      not the code — is the specification. It is also barred from reading the
      archived discovery, which is module-designer's input; reading it would
      route a prototype's raw intent around the Card Owner approved.
      Dispatcher's resume rules now separate a *first* implementation from an
      *interrupted* one, so the common case reads as the common case: most
      capabilities never have an MVP, and a fresh `full` run expects no prior
      traces.
- [x] `mark-changes` now records its evidence. It was a bare state flip: no
      Review Record path and no reasons, while the dispatcher was instructed
      to "re-dispatch developer with its reason codes" — pointing at
      something nothing had ever recorded, so the next developer was sent
      back to guessing. It now validates the Review Record exactly as
      `mark-approved` does, requires a `CHANGES_REQUESTED` verdict, and
      requires at least one reason code from the closed set. The codes are
      defined once in `state.REASON_CODES` so the template, the reviewer
      prompt and the validator cannot drift.
- [x] Design blockers are now enforced. STATE deliberately carries no
      blocker state, which was right, but it also meant a fixed-but-forgotten
      `<cap>.design-blocker.md` could coexist with `fully_approved` forever.
      `mark-mvp`, `mark-changes` and `mark-approved` now refuse while the
      open file exists. Resolution fills in the file's `resolution:` field and
      renames it to `.design-blocker.resolved.md` — a rename, not a delete,
      so the reasoning stays readable and the lift is a recorded act. `retry`
      is deliberately ungated so a blocker cannot deadlock its own work.
- [x] The upstream gate has a tool now. `dependers-of` could not answer its
      own question — it took the text before the first dot of a capability id
      as the module name, so `series.get` reported a module called `series`
      (which does not exist; the provider is `market-data`) and found zero
      dependers as a result. It now resolves the provider from the
      architecture and lists the modules whose `module.yaml` actually
      `uses:` the capability, with their declared reason.
      `state upstream <module> [<cap>]` is the gate the dispatcher used to
      have to perform by hand: it reads the module's declared
      `depends_on[].uses`, resolves each id to its real provider, and
      cross-references STATE, printing green/red per capability and exiting
      nonzero on any red. Only `fully_approved` is green — `unregistered`
      included, since a capability nobody has worked on is not consumable
      either. Because the architecture declares upstream use per module and
      not per capability, the default is the wider safe reading; `--upstream
      <cap.id>` narrows it when a Card knows better, and the output says
      which granularity it used.
- [x] The four review scores were three spellings; the real split was two
      surfaces. Inside the Review Record the names are
      `contract_conformance / boundary / test_coverage /
      implementation_quality`, and that spelling was already consistent
      across the template, reviewer.md and the `mark-approved` validator —
      so it stays, and is now the single constant the docs point at. The
      drift was in the *handoff one-liner*: reviewer.md told the reviewer to
      emit `contract= boundary= test= quality=`, while the dispatcher, the
      decision-prompt template and AGENTS.md all told the Owner
      `c= b= t= q=`. reviewer.md now emits the compact form, and both
      surfaces say why they differ — the Record is machine-validated, the
      handoff is the ≤100-word summary Owner reads. The handoff also now
      carries the reason codes, which the dispatcher needs on a rejection.
- [x] `compute_module_state` fell through to `partial_mvp` for anything it
      did not recognise, so a module whose every capability had been
      rejected was reported as holding MVPs — a label that had just stopped
      meaning "work in progress", since an MVP is no longer a path to
      completion. It also contained an unreachable branch (a
      `fully_approved`-and-`abandoned` case guarded by a condition that had
      already excluded `abandoned`). Rewritten most-conclusive-first, and a
      `blocked` value added for rejected work. The test suite now checks
      every state pair maps to a real label, which is what let the old
      default survive unnoticed.
- [x] The reviewer's `ABANDON` verdict was write-only, and `--reviewer-run`
      was never read at all. The `ABANDON` verdict was documented in
      reviewer.md and the Record template, but no command consumed it, so a
      review that condemned a capability left only a bare `abandoned` in
      STATE — indistinguishable from the Owner changing their mind, which
      matters because the two point at different things (a bad Card vs a
      scheduling change). `abandon` now takes an optional `--review`: with
      it, the ABANDON verdict is validated and the path recorded; without
      it, the closure is plainly an Owner decision. Optional on purpose —
      closing a never-reviewed `pending` capability is ordinary and must not
      require inventing a review. `reviewer_run` was deleted outright: it
      was written, serialised, read back into the dataclass, and consumed by
      nothing, and the Review Record already carries the reviewer model.
- [x] `blocked` was the wrong word for a rejected module, and said so. In
      workflow tooling "blocked" means waiting on something external — an
      approval, a person, a dependency. But this state means a reviewer
      named reason codes and someone owes a fix: nothing is waiting, `retry`
      is available, and the work is actionable now. The condition that
      genuinely *is* blocked — an upstream that is not `fully_approved` — is
      a different one, reported by `state upstream`, not by this field.
      Renamed to `rework`.
