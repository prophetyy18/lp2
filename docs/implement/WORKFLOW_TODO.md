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

- [ ] `promote` resets state to `pending`, which is indistinguishable from a
      fresh registration; a promoted capability with no Manifest is routed
      back to developer instead of the reviewer.
- [ ] `mark-mvp` takes no evidence: it succeeds with no `--manifest`, and does
      not check the file exists (`mark-approved` does both).
- [ ] `mark-changes` records no review path or reason codes, so
      `changes_requested` cannot say which Record caused it.
- [ ] Design blockers are unregistered: `mark-approved` does not check for an
      open `<cap>.design-blocker.md`, so a stale blocker can coexist with
      `fully_approved`.
- [ ] `dependers-of` cannot answer its own question; the dispatcher's
      YELLOW/RED upstream gate has no tool. `archctl depends` already reports
      `[OK]` / `[?]` per dependency and is the missing primitive.
- [ ] Four review scores have three spellings across AGENTS.md, dispatcher.md,
      reviewer.md and the template; `mark-approved` regex-matches only one.
- [ ] `compute_module_state` misclassifies all-`changes_requested` as
      `partial_mvp` and contains an unreachable branch.
- [ ] `--reviewer-run` has no defined source; `mark-mvp --mode` is parsed and
      ignored.
