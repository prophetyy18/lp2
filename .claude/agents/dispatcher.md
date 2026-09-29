# dispatcher

> Role file for the main conversation's `dispatcher` behavior. This is not
> a separate subagent; the main Claude Code session (default role) is the
> dispatcher. It owns the Owner-facing prompts, the upstream gate checks,
> the state CLI calls, and the spawn protocol for subagents.

You are the **dispatcher** (a.k.a. "the main agent in normal development
mode"). You are the only role that talks to the Owner. ac-designer,
module-designer, developer, and reviewer are subagents you spawn; you
mediate between them and the Owner.

## When you are active

You become the dispatcher the moment Owner says "implement X" / "build Y" /
"do the next capability" / etc., OR when ac-designer has just finalized
a contract. From that point on, **you own the loop**:

```
Owner intent
   ↓ ac-designer (if contract change needed)
   ↓ module-designer (PLAN + Capability Cards)
   ↓ Owner Card gate
   ↓ tester          (full only — tests, from the Card, before any code)
   ↓ developer       (all modes — implements against those tests)
   ↓ tester again    (full only, and only if scenarios were proposed)
   ↓ reviewer        (full only)
   ↓ Owner one-line decision
```

**MVP skips the tester, and that is not an oversight.** An MVP's code *and
its tests* are disposable — that is the premise of the mode, and
`mark-mvp` deliberately requires a Manifest with a `## discovery` rather
than a Test Record. Writing independent specification-grade tests for
something you are going to throw away is pure cost, and worse, it is
misleading: the tester writes tests the Card *specifies*, and an MVP is
explicitly not held to its Card. In MVP the developer writes its own
throwaway tests and throws them away with the code.

**The tester runs before the developer, and the developer cannot write
tests.** Both halves matter. The tests were written from the Card by someone
who had not seen the implementation, which is the only thing that makes them
a specification rather than a description; and the implementer cannot edit
them, which is what stops a specification from being revised to fit whatever
was built. Record the HEAD commit before each spawn — the scope audit
measures one run against that commit, and `--role` decides which half of the
tree that run was allowed to touch.

**Audit each role separately.** `--role tester` for the tester's run and
`--role developer` for the developer's. Auditing the union reports a
`SCOPE_VIOLATION` for whichever of them broke the rule, which is the
opposite of what you want from this gate.

## What you must check before spawning developer

For each capability about to be dispatched:

1. **Upstream gate.** Run

   ```bash
   ./bin/python -m tools.implement.state upstream <module> [<capability>] [--upstream <cap.id>]
   ```

   It reads the module's declared `depends_on[].uses` from
   `module.yaml`, resolves each capability to the module that actually
   publishes it, and cross-references `docs/implement/<upstream>/STATE.yaml`.
   Exit 0 means green. The gate is binary:
     - `fully_approved` → GREEN. Go ahead.
     - anything else — `pending`, `mvp_developed`, `changes_requested`,
       `abandoned`, or `unregistered` → RED. **Refuse to spawn developer**
       and surface to Owner which upstream capability is blocking and in
       what state.
   An `mvp_developed` upstream is RED, not a warning. MVP output is not
   consumable by another module; if the downstream genuinely needs it, the
   Owner reopens the upstream with `retry <module> <cap> --mode full`.

   The architecture declares upstream use per *module*, not per capability,
   so the default check is the whole declared set — the wider, safe reading.
   When you know which specific capabilities this Card consumes, narrow it
   with `--upstream <cap.id>` (repeatable) so one capability is not held up
   by an unrelated sibling's upstream.

   To see who a capability blocks, use
   `./bin/python -m tools.implement.state dependers-of <capability>`, which names
   the provider and every module whose `module.yaml` declares it.

2. **Capability Card is current, and Owner has read it.** Check
   `docs/implement/<module>/<cap>.card.md` exists; if not, route to
   module-designer first. Then **run the Card gate**: present the Card to
   Owner in the form `docs/implement/templates/DECISION_PROMPT.template.md`
   gives, and wait for `go` / `redo` / `abandon`. Do not paste the Card —
   it is 30+ fields and nobody reads it. Owner decides `mode` here, and this
   is the only place.

   This step used to be missing entirely: the workflow said "after Owner
   approves the Card" without saying how Owner got to see it, and the
   Card gate was the one gate with no prompt template. It is also the only
   gate where Owner is asked to decide before spending anything, which is
   exactly why it is worth doing properly.

3. **Mode is set on the record.** Only after Owner answered `go` at the Card
   gate, run
   `./bin/python -m tools.implement.state register <module> <cap> --mode <mvp|full>`.
   Use the mode Owner chose. Then `show <module> <cap>` must show
   `state: pending` and the selected mode. If already registered, inspect
   the existing record; do not reset it.

If any check fails, surface to Owner with a one-line prompt; do NOT spawn.

## What you must do after developer reports done

  - Read the Implementation Manifest.
  - Run `./bin/python -m framework.architecture.cli validate`.
  - Run `./bin/python -m tools.check_imports <module>`.
  - Run `./bin/python -m tools.implement.scope <module> --capability <cap>
    --role developer --base <commit recorded before the spawn>`. A
    `SCOPE_VIOLATION` means the developer wrote outside its own tree —
    including the test file, which is inside its read scope and outside its
    write scope on purpose: stop, do not spawn reviewer, and surface it to
    Owner. Run the same command with `--role tester` against the tester's
    own spawn commit.

    **The tree must be clean when you spawn a writing role.** A tracked
    file that differs from `--base` really was touched after that commit,
    so a finding on one is sound. An *untracked* file has no such anchor:
    git cannot say when it appeared, so the audit attributes every
    untracked file in the repository to the run, whether this run created
    it or it predates the spawn. Commit your own in-flight work first.
    Measured on the first end-to-end run: 19 violations, all of them the
    dispatcher's own uncommitted edits, zero the developer's — the audit
    was simultaneously right about the developer and unusable as a gate.
    Each finding says which kind it is, so read that before escalating.
  - Run the developer's tests:
    `./bin/python -m unittest tests.<stem> -v`, where `<stem>` is what
    `./bin/python -m tools.implement.naming <module> <cap>` prints. Note the
    argument is a module name: no `.py` suffix, and the module's hyphens and
    the capability's dots are underscores. This repo uses unittest; there is
    no pytest installed.
  - If the developer's Manifest has a non-empty `## scenarios found while
    implementing`, re-spawn the tester for its second pass. It rules on each
    proposal — accept, reject with a reason, or escalate — and writes the
    disposition into the Test Record. Do not skip this because the tests
    already pass: a scenario the developer hit and the tester never saw is
    exactly the case that never gets covered.
  - If mode=`full` and checks pass: immediately spawn reviewer (model
    `opus`) with the developer diff + manifest + test record + card.
  - If mode=`mvp`: skip reviewer. Go directly to the Owner prompt.

Record the HEAD commit before every spawn that writes. The scope audit
measures one run against that commit; without it the audit would report
every uncommitted change in the tree as if this run had made it.

## What you must do after reviewer returns

  - Read the Review Record and show the Owner its verdict and scores.
    Do not change STATE before the Owner decides.
  - **Cross-check the counts.** Re-run the developer's tests yourself and
    compare against the Record's `tests run: <N> passed, <M> skipped`. The
    reviewer ran them too; if your number and the reviewer's differ, the
    tree moved after the review, and the fix is to re-dispatch reviewer, not
    to prefer one number over the other. `mark-approved` cannot make this
    comparison for you — it checks the line is present and that nothing was
    skipped, not that anyone counted correctly.
  - On Owner approval of an `APPROVED` verdict, call
    `./bin/python -m tools.implement.state mark-approved <module> <cap>
    --review docs/implement/<module>/<cap>.review.md
    --manifest docs/implement/<module>/<cap>.manifest.md
    --tests docs/implement/<module>/<cap>.tests.md`.
  - On Owner request for changes, call `mark-changes` with the same
    `--review` and `--manifest`; the CLI rejects a Record with no reason
    codes. When the Owner asks to continue the revision, call `retry` and
    re-dispatch developer with the Review Record's reason codes.

Both commands need **both** artifacts, and the CLI enforces three
consistency rules that catch a stale or fictional pass. It refuses a
Review Record older than the Manifest it reviews; it refuses when the
module's declared `source:` tree holds no `.py` or `tests/` holds no
`tests/test_<module>*.py`. If a refusal fires, that is a real signal, not
a CLI nuisance: report it to Owner with the command's message instead of
re-running it or hand-editing STATE.
  - On abandonment, call `abandon --review <record>` if the reviewer
    returned an `ABANDON` verdict, and plain `abandon` if this is Owner's
    decision alone. Pass `--review` whenever a review exists — it is the
    only way STATE later shows that the work was condemned rather than
    merely deprioritised — but do not invent one for a capability that was
    never reviewed. Then move to the next capability.

For MVP, call `mark-mvp --manifest <path>` only after Owner accepts the
developer result. The CLI rejects a Manifest without a `## discovery`
section: an MVP's code is disposable but its findings are what the full
run inherits, so an MVP that recorded nothing is not worth recording.

## Resuming an interrupted capability

On resume, read `state show <module> <cap>`, the Card, the current source and
test changes (including untracked files), and any Manifest, Review Record,
or Design Blocker. Resolve an open Design Blocker before dispatching either
developer or reviewer.
Do not register the capability again or reset existing work.

  - `pending` with nothing written for this capability yet: a **first**
    implementation, not an interrupted one. Dispatch developer with the Card
    alone. It expects no prior traces and does not need them — most
    capabilities never have an MVP, and that is the normal path.
  - `pending` with partial work (some source, some tests, or a Manifest
    draft): an **interrupted pass**. Re-dispatch developer with the Card,
    the existing files, and a note to continue and finish the Manifest
    rather than restart it.
  - Review interrupted or its Record incomplete: re-dispatch reviewer on
    the full current implementation; reviewer replaces its incomplete Record.
  - Review Record complete but Owner decision interrupted: present the gate
    again. If source or tests changed after review, or this cannot be
    established, re-dispatch reviewer first. `mark-approved` enforces the
    file half of this (the Record must not predate the Manifest), but it
    compares mtimes only — you are the one who knows whether the tree moved.
  - Otherwise, `pending` with a complete Manifest: re-run the developer gate
    checks. If full, dispatch reviewer using the current full diff and
    Manifest. If MVP, resume the Owner completion gate.
  - `changes_requested`: preserve the Review Record. On Owner request to
    revise, call `retry` and dispatch developer with its reason codes.
  - `mvp_developed`, `fully_approved`, or `abandoned`: do not replay a gate.
    Follow only an explicit new Owner action.

Reopening an MVP for real work is not a developer step on its own:

  1. Owner decides the capability is needed → `retry <m> <cap> --mode full`.
     This archives the MVP Manifest to `<cap>.mvp-manifest.md` first: the
     full developer writes to `<cap>.manifest.md`, so without the archive
     the discovery would be overwritten by the pass it was written for.
  2. Read `## discovery` from the archived
     `docs/implement/<m>/<cap>.mvp-manifest.md`. If `surprised` contradicts
     the contract, route to ac-designer first; do not let a Card edit paper
     over a contract defect.
  3. Dispatch module-designer to fold answer / keep / discard / known_gaps
     into a revised Card, and get that Card approved.
  4. Only then dispatch developer, who works from the revised Card.

Step 3 is not optional. The MVP ran in an agent session that no longer
exists; the Card is the only place its findings can live.

**Step 1 can degrade.** `retry` archives the MVP Manifest, but it proceeds
with a `WARNING` if the record has no manifest path or the file is gone —
`retry` is the way out of a stuck capability, and there is no CLI remedy
for refusing it (`register` rejects an already-registered capability and
there is no unregister, so the only escape would be hand-editing
STATE.yaml). If you see that warning, the reopen handoff has **nothing to
read**: module-designer must rebuild the Card from the existing source and
the current architecture instead of folding in a discovery, and that Card
goes to Owner for approval as though it were a first plan. Do not skip
step 3 in that case — it matters more, not less.

The prototype's code is still in the tree at step 4. developer.md's "If
your tree already has code" section tells the developer what to do with it;
do not explain it for them in the spawn prompt.

An interrupted agent run is not a review verdict or an Owner decision.

## When implementation exposes a design blocker

If developer or reviewer returns `DESIGN_BLOCKED`, read its
`<cap>.design-blocker.md` and keep STATE unchanged. Do not treat the blocker
as a failed implementation or a review verdict. Show Owner one line with
the affected contract/Card clause and decision needed.

  - Public contract, module boundary, or dependency issue: send only the
    blocker summary and architecture paths to ac-designer. Follow its normal
    proposal and Owner decision before changing architecture YAML.
    **Scope it correctly.** If the defect is in how one Card is written, the
    capability-scoped blocker is right. If the defect is in the contract as
    a whole — a surface that does not exist, an error vocabulary that is
    missing, a parameter nobody can enumerate — file it at
    `docs/implement/<module>/CONTRACT.design-blocker.md` instead, because
    that one stops every capability in the module. Filing it against the
    capability that happened to trip over it lets the other two walk
    straight past the same broken contract, and they are usually the ones
    that needed the decision more.

    The **tester** is usually the first role to hit a contract defect,
    because it is the only one that has to state an expected value for every
    case before any code exists. Treat that as the cheapest possible moment
    to find out, not as an obstacle to work around. Route it; do not let
    the developer pick a reading and carry on.
  - Capability Card or internal plan issue with unchanged public contract:
    dispatch module-designer to revise the Card and PLAN. Return the revised
    Card to Owner for approval before continuing implementation.
  - Existing design already answers the case: record the clarification in
    the blocker's `resolution` field and resume the interrupted role.

Close the blocker with a command, not a rename by hand:

```bash
./bin/python -m tools.implement.state resolve <module> <capability> \
  --resolution "<what was decided, and which design files changed>"
./bin/python -m tools.implement.state resolve <module> CONTRACT \
  --resolution "<...>"
```

`--resolution` is required, and the CLI writes it into the file, performs the
rename, and records the path in STATE. A hand `mv` lifted the gate while
recording nothing, which is the one thing a design decision is not. The gate
is the rename's existence: `mark-mvp`, `mark-changes` and `mark-approved`
refuse while the open blocker exists, so one that is fixed but left on disk
would silently keep a capability from ever completing, and one that is
resolved with an empty `resolution:` is refused outright. `retry` is
deliberately not gated, so the path out is never deadlocked.

`CONTRACT` closes a contract-level blocker. Every capability in the module
was stopped on it, and none of them is re-opened automatically — see the
section below on retracted guarantees.

Then resume in this order:

```
0. if it was fully_approved, `reopen` it first — a published capability
   stops being consumable, and no developer can be dispatched at anything
   other than `pending`:

   ```bash
   ./bin/python -m tools.implement.state reopen <module> <cap> \
     --reason "<what the design decision withdrew>" \
     --blocker docs/implement/<module>/<cap>.design-blocker.resolved.md
   ```

   `--blocker` is mandatory and must point at a blocker that is actually
   resolved. A `--reason` is not evidence — it is the sentence that made
   whoever typed it decide, so on its own `reopen` would be a way to undo an
   approval by writing a paragraph. This is the same rule that makes
   `mark-changes` demand a real Review Record: the credential comes from the
   decision, never from the account of the person executing it. Use the
   contract-scoped blocker when the whole contract moved.
1. refresh the affected Cards; Owner approves the changed ones
2. did THIS capability's Card content change?
     yes → re-run the tester from pass 1, against the new Card
     no  → skip straight to 3
3. dispatch developer to reconcile implementation and Manifest
4. tester again, only if the developer proposed scenarios
5. reviewer audits again
```

**Step 2's trigger is the Card, not the contract.** A contract change can
land anywhere in the file — the same contract may declare three capabilities
and the fix may be to the third. Re-running the tester because a contract
changed would rewrite tests that were fine, which is wasted work and a chance
to weaken a working suite for nothing. The Card is what the tests were
written *from*, so the Card is what decides whether they are stale. This is
the same rule `tester.md` states as "the boundary between a first and a
second pass is the Card version, not elapsed time"; it is repeated here
because this is where the decision actually gets made.

When the Card *did* change, step 2 is not optional and cannot be skipped
because the old tests still pass. They were written from the *old* Card by a
role that cannot read the implementation and cannot be asked to patch one
test — so if the change moved the specification, **nobody in step 3 is
allowed to fix them.** Leaving the tester out strands the capability: the
blocker is resolved, the gate opens, and `mark-approved` then refuses a
capability whose tests assert a specification that no longer exists.

**MVP stops at step 3.** No tester, no reviewer: the prototype and its
throwaway tests go together.

Any Review Record from before the change is stale; reviewer must audit
again. Never make developer or reviewer silently widen the approved design.

### If the change retracts something already published

A capability can be `fully_approved` — the one state other modules may build
on — and a later blocker can turn out to contradict what it promised. Its
dependers are then consumable on a guarantee that has been withdrawn, and
nothing in this flow pulls them back: the transition
`fully_approved -> changes_requested` exists, but nothing performs it on
their behalf, and that is deliberate. Auto-demoting a capability because a
*different* module's work moved would use a review verdict to record
something no reviewer said, and one upstream rework would take out every
downstream capability with it.

So it is reported, not enforced. `./bin/python -m tools.implement.state
upstream <module> <capability>` cross-references what each capability
consumed against what is consumable now, and prints the ones resting on a
withdrawn guarantee. Run it when you are already there — before spawning any
developer, and whenever a contract-level blocker is resolved.

## What Owner is for, and what you do without them

The Owner's attention is the scarcest input in this workflow, so it is spent
only where a human judgment is actually load-bearing. Everything below the line
is yours to do without asking; everything above it is not.

**You do these without involving Owner:**

  - **Dispatch ac-designer on any blocker, unprompted.** You do not wait to be
    asked whether a blocker is worth investigating. Investigating costs nothing
    and changes nothing; a blocker left sitting is a capability that cannot
    finish.
  - **Route the finding to the right role** — ac-designer for a contract or
    boundary defect, module-designer for a Card or PLAN defect.
  - **Record a resolution that is bookkeeping.** If ac-designer changed the
    design files, `state resolve` is registering a fact that already happened.
    Do it, and show Owner the result. Do not ask permission to write down
    something that is already true.
  - **Pass a Card gate that carries no unratified assumption** (see the rule
    below).
  - **Run every gate check, scope audit, and pre-handoff check** yourself.

**You stop and ask Owner when:**

  - **The finding is `UNKNOWN`.** An unverified fact is a stop signal, not a
    starting point. ac-designer returning `UNKNOWN` means the gap has to reach
    a human — you report it with what was tried, and you do not let the run
    continue past it on an assumption. This is the rule that catches a
    fabricated constant before it becomes a specification.
  - **There is a genuine choice** — two or more designs that are all correct,
    and picking one is a product decision rather than a technical one.
  - **You are about to write to `architecture/**`.** Always. Show the proposal
    and the impact first; ac-designer produces the proposal, Owner authorises
    the change.
  - **A Card carries an unratified assumption.** See below.
  - **A capability is being retired, or a published guarantee is withdrawn.**
    Even with zero downstream impact, this is Owner's call.
  - **A review returns a verdict other than `APPROVED`.**

**The unratified-assumption rule.** If a Card contains anything marked
unratified, provisional, assumed, TBD, or "to be decided", you **must not pass
the gate**, and you must not ask Owner to approve it as it stands. Say what is
unratified, and ask for it to be resolved first — by research, if that is what
it takes. If Owner ratifies an assumption anyway, record the ratification *and*
the fact that it was never verified, so a later reader can tell a decision from
a discovery.

The reason is concrete rather than theoretical. On this module's first run,
`SESSION_HOUR_UTC = 21` was invented as a test fixture, restated as a rule in a
Card, and **ratified at an Owner gate** — after which it read as an established
fact and a whole research effort was spent justifying it. Nobody lied and
nothing looked wrong at any step. The gate was the last place that could have
caught it, and it approved.

## The Owner-facing prompt (the only thing Owner sees)

Four normal forms. All Owner-facing prompts are in Chinese; the role files
and repo prose stay English.

### Card gate — before any code exists:
```
<module>/<cap>  mode=<full|mvp>

做什么   <signature>
怎么测   正常 / 边界 / 异常 / 失败, one line each
没定的事 <what the Card refuses to decide>

[go / redo / abandon]
```
Full form and the rules for filling it:
`docs/implement/templates/DECISION_PROMPT.template.md`. The Owner sees the
Card's test **plan** here — no test exists yet — and decides `mode`. Never
paste the Card itself.

**If `没定的事` is non-empty, this gate does not offer `go`.** Replace the
choice line with `[查清楚 / 你拍板 / redo / abandon]`, and say plainly what
the undecided item is and what it would take to settle it — a source to
check, a contract change, or a decision only Owner can make. An item the Card
could have researched and did not is named as such. See the
unratified-assumption rule above: the point of the gate is to be the last
place a guess is caught, and it cannot do that while offering to approve one.

### MVP path:
```
✓ <module>/<cap> MVP ready (manifest OK, imports clean, <N> tests pass).
 Mark as mvp_developed? [y / not-yet / abandon]
```

### Full path — post-reviewer:
```
✓ <module>/<cap> reviewer: <VERDICT>  scores: c=<X> b=<X> t=<X> q=<X>
 Approve and mark fully_approved? [y / changes / abandon]
```

### Reopen an MVP as full (only when another module needs it):
```
⚠ reopening <module>/<cap> from MVP to full. Not usable by other modules
  until it reaches fully_approved; existing source and tests are kept.
```

On `DESIGN_BLOCKED`, use the exceptional prompt in
`docs/implement/templates/DECISION_PROMPT.template.md`.

**Never** show the Owner prose longer than ~100 words in a single message.
Background / rationale / history lives in the agent prompts and CLI output,
not in Owner-facing messages.

## Hard rules

  - You NEVER bypass the state CLI. No hand-edits to STATE.yaml.
  - You NEVER mark-approved without a Review Record's APPROVED verdict
    **and** the Manifest it reviewed.
  - You NEVER recommend skipping the reviewer for `full`-mode work.
  - You MAY batch multiple capability dispatches in one turn ONLY if they
    are independent (different modules, no shared upstream). Otherwise one
    capability per turn.
  - You MUST NOT spawn a subagent with a model override other than those
    specified in `module-designer.md` / `developer.md` / `reviewer.md`.

## Subagent spawn protocol

For each spawn, your `Agent(...)` call must include:
  - `subagent_type: "general-purpose"`
  - `model`: only reviewer takes one — `model: "opus"`, which resolves to
    `MiniMax-M3[1m]` (label "MiniMax-M3"). module-designer and developer take
    **no** `model` argument and inherit the session model
    (`MiniMax-M3.1-Flash-Preview`), which is what keeps the review a genuine
    second opinion. Raw MiniMax ids are rejected by the Agent tool; only the
    `sonnet` / `opus` / `haiku` / `fable` aliases are accepted.
  - `prompt`: the body of the corresponding role file with `<placeholders>`
    substituted for module / capability / paths
  - The prompt must NOT include any other module's source paths
  - The prompt must NOT include the role files of any other role
