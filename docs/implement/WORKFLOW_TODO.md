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

- [x] The write-scope audit could not be used on a dirty tree, and the
      first real run proved it. `touched_files` merged `git diff <base>`
      with `git ls-files --others`, so **every untracked file in the
      repository** was attributed to the run. Dispatching the first
      developer on a tree carrying this session's own uncommitted work
      produced 19 violations, all of them the dispatcher's edits, and
      reported the developer as having escaped its write set. The
      developer's own files were never among them — the audit was right
      about the run and unusable as a gate at the same time. The two
      sources are now reported separately, and each finding says whether
      it came from a tracked modification (which really is anchored to
      `--base`) or from an untracked file (which is not, and is annotated
      as such). The premise itself is the dispatcher's to guarantee, so
      the protocol now says: commit in-flight work before spawning a
      writing role. Deliberately *not* solved by downgrading untracked
      findings to a warning — a developer that wrote outside its tree and
      left the file uncommitted would then pass, which is a worse failure
      than a false positive because it is silent.
- [x] The Card gate had no prompt. The workflow said "after Owner approves
      the Card" without saying how Owner got to see it, and the Card gate
      was the only gate absent from `DECISION_PROMPT.template.md` — the
      only one where Owner decides *before* spending anything, and so the
      one most worth doing properly. Owner also had no way to see it:
      asked, the honest answer was "go read `docs/implement/<module>/
      <cap>.card.md`", which is a 60-line English document with 30+
      fields. It now has a form (Chinese, since the Owner reads the
      prompts while the agents read the role files), it shows the Card's
      test **plan** rather than tests — nothing is written yet, and a plan
      is far cheaper to judge than finished tests — and it carries a
      `没定的事` list of what the Card refused to decide, which is where
      the Owner's real judgement is. `AGENTS.md`'s claim that the Card is
      "~10 lines" was simply false and is gone.

Review of 2026-09-28 (P0 items that blocked module execution):

- [x] No module had ever been run, and the naming rule could not have worked.
      Module names are hyphenated and every capability id is dotted
      (`market-data`, `series.get`), so neither survives as a Python module
      path, and the test-file convention was spelled in prose in seven places
      and implemented twice. `scope.py` compared against
      `tests/test_market-data_series.get` — a filename no writer can produce,
      so a developer's own test file came back `SCOPE_VIOLATION`. That is the
      layer AGENTS.md calls "the layer that actually holds", so the first real
      capability would have been stopped by it. `state.py` meanwhile asked a
      different question (`test_market_data*`), and the two documented
      `python -m unittest tests.test_<module>_<cap>.py` invocations cannot work
      for any real module: unittest resolves its argument as a module name, so
      the `.py` suffix fails, a hyphen is not an identifier character, and the
      capability's dot is read as attribute access. The translation now lives
      once in `tools/implement/naming.py`; both CLIs call it and
      `python -m tools.implement.naming <module> <cap>` prints the answer, so
      the prompts can ask instead of composing a name. It survived review
      because every fixture used `alpha` / `one` — the one pair of names for
      which the broken rule is accidentally correct; the new tests are written
      against hyphenated and dotted names, and one of them executes the
      command the CLI prints, because a naming rule nothing ever imports can
      drift back into prose unnoticed.
- [x] The consumable state was gated on documents only. `fully_approved` is
      the one state another module may build on, and nothing read the
      contract to ask what a consumer is entitled to assume — even though
      `position.mark` declares three error codes and `idempotent: true` and
      `ordering: total` in `architecture/contracts/pricing-api.yaml`, all of
      it already parsed into `Capability.errors` / `.behavior`. A capability
      could be approved with none of it tested, and the Manifest's
      `errors emitted:` line — which nobody read — was free to say otherwise.
      The MVP path had already learned this; the discovery template's own
      worked example is "3 of the 4 declared error codes are unimplemented".
      `mark-approved` now derives the obligations from the contract, not the
      Card, and requires a `tests by obligation:` block mapping each one to a
      test method that exists in the test file. Deliberately a *mapping*
      rather than a count, and deliberately not a string search for the error
      code: a developer who parametrizes over `cap.errors` has written a
      better test than one who pastes the literal, and refusing that would
      train the worse habit. `mark-changes` does not demand them — a
      rejection may be *because* a guarantee is untested, and refusing to
      record the reviewer's finding would be absurd. Twelve tests, and each
      rule was checked to fail when the rule was removed.
- [x] `test_coverage: OK` was a claim about tests nobody was required to run.
      The reviewer was made to run `check_imports` and never the test file it
      was scoring, so a skipped test still left the file on disk, still read
      as coverage, and still exited 0 — four skipped tests passed every other
      check in the CLI. The Review Record now carries `- tests run: <N>
      passed, <M> skipped`, which `mark-approved` requires with N ≥ 1 and
      M == 0, and the dispatcher is told to re-run the tests and compare
      counts, because the CLI can check the line is present but not that
      anyone counted correctly. Zero skips is the rule because a skip is
      unreviewable, and "we cannot exercise this yet" is what `mode: mvp` is
      for.
- [x] Every documented command was written `python -m ...`, and no `python`
      exists on this PATH. The measurement that settled it: the shell
      running these commands is neither login nor interactive and reads no
      profile, so `conda init` / `conda activate` never reach it — and the
      developer and reviewer subagents run their commands in exactly that
      shell. Activation was therefore not an option. `bin/python` is a shim
      that execs the `robinhood-lp` env (Python 3.12), and every documented
      command is now `./bin/python -m ...`; `LP2_PYTHON` overrides it without
      editing the file, and the shim exits 127 with a message rather than
      failing obscurely. The env was missing PyYAML — the tooling's only
      third-party dependency, previously undeclared — so that is installed
      along with pandas, which the `series.get` signature needs. Three tests
      cover the shim, including one that runs the command the naming CLI
      prints.

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
      `<cap>.mvp-manifest.md` and clears `rec.manifest`. A missing or
      unrecorded Manifest degrades to a loud `WARNING` rather than a
      refusal: `retry` is the way *out* of a stuck capability, and since
      `register` rejects an already-registered capability and there is no
      unregister, refusing would have left hand-editing STATE.yaml — which
      the policy forbids — as the only escape. The warning tells the
      dispatcher the handoff has nothing to read, so module-designer
      rebuilds the Card from source and Owner approves it as a first plan.
      An archive that already exists *is* a refusal: re-archiving would
      overwrite an earlier spike's findings permanently and silently.
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
- [x] A transition could be driven by a document instead of by work. This was
      demonstrated, not theorised: a hand-written Review Record with four
      `OK` scores and an `APPROVED` verdict, over a module with no code in
      it, took `mark-approved` to `fully_approved` — the one state other
      modules may consume. `mark-mvp` already required a Manifest, so full
      mode, the *stronger* path, required the weaker evidence; that was
      backwards. `mark-approved` and `mark-changes` now take `--manifest`
      alongside `--review` and validate it the way `mark-mvp` does; the
      Review Record may not predate the Manifest; and the module's declared
      `source:` tree must hold a `.py` and `tests/` must hold a matching
      `tests/test_<module>*.py`. Eight tests, one per rule, and they were
      checked to fail when the rules are removed. The honest limit is
      recorded in the code: these checks find inconsistency *between
      artifacts*, and an agent that fabricates both documents passes all
      of them, because a document is all this CLI ever sees. The
      write-scope audit (`tools/implement.scope`), which compares the tree
      against the commit recorded before the spawn, is the layer that
      proves a run actually touched files — and it runs before the
      reviewer, not at the state transition, so a refusal here is a
      backstop rather than the primary control.
- [x] `module_state` was a stored copy that nothing read, saying six things
      the capability rows already said. `from_dict` recomputed it on load and
      overwrote whatever the file claimed, so the column on disk was
      decorative: a hand-edited `module_state: complete` over two `pending`
      capabilities was silently ignored and the CLI printed the right answer,
      meaning nobody could ever discover the file had been corrupted. Dropped
      from `to_dict` and made a computed property, so the file holds facts
      only and drift is impossible by construction rather than by
      discipline; `state show` prints it as a comment. Cut from six labels
      to three (`not_started / in_progress / complete`), because six was
      more than the rows beneath can justify: `rework` restated
      `changes_requested` (whose reason codes say more), `partial_mvp`
      restated `mvp_developed`, and `partially_complete` implied that a
      module is partly consumable — a granularity that does not exist, since
      consumption is per capability and `state upstream` is where that is
      decided. The three values each answer a question about *work*, and two
      edge cases follow from the smaller set and are documented as intended:
      an all-abandoned module is `in_progress` (no fourth value for
      "started, then closed"), and adding a capability to a `complete` module
      ratchets it back to `in_progress`. The old six survived a long time
      because they were well tested — the fix that made every rejected
      capability report as `partial_mvp` was a real one — and being
      carefully tested is not a reason to keep a field no consumer needs.
      It is the same failure as `reviewer_run`: attention spent on a
      maintainable artifact that never got a reader.
