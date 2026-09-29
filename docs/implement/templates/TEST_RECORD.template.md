# Test Record template

Copy to `docs/implement/<module>/<capability>.tests.md`. Written by the
**tester**, who does not write implementation and does not read it.

```markdown
# tests: <module> / <capability_id>

- mode: <mvp | full>
- pass: <1 | 2>                    # 1 = before implementation, 2 = after
- card: docs/implement/<module>/<capability>.card.md
- tests written: <N>
- test file: tests/<the stem tools.implement.naming prints>.py

## card test plan coverage

Every line of the Card's `test plan`, and the test that covers it. A plan
line with nothing against it is a gap in the Card, not a gap you may leave.

- normal:    <test_method> — <what it pins>
- boundary:  <test_method> — <what it pins>
- invalid:   <test_method> — <what it pins>
- failure:   <test_method> — <what it pins>

## tests by obligation

REQUIRED when the contract declares `errors` or `behavior` for this
capability. `mark-approved` reads this list **from this file**, and requires
the named test method to exist in the test file. A capability whose contract
declares neither omits this section.

- <ERROR_CODE>: <test_method>          # one line per declared error code
- idempotent: <test_method>            # if behavior.idempotent is true
- ordering: <test_method>              # if behavior.ordering is total/partial

## discovery

REQUIRED in every mode. Not only for MVPs any more: the tester writes no
implementation, so none of what it learns is disposable, and the
implementation's session will not remember any of it.

- looked at: <the real thing you actually went and examined — the data
  source, the chain, the upstream contract's edge. Not "the code">
- source: <REQUIRED for anything learned from outside this repository. Not
  just a link — a URL is not reproducible for a fact that changes. Record
  the coordinates:

      source:       official URL, or the exact command run
      retrieved at: when
      chain id:     which chain
      block:        block number or hash, for anything read from a chain
      code hash:    when the fact is about deployed bytecode

  A claim with no coordinates is an assumption and belongs under
  `unratified choices` instead. The reviewer checks this, and an uncited
  claim that a test now depends on is an ISSUE.>
- found: <what it actually returns: column names, types, timezone, which
  parameter values work, what a bad input does. What you saw, not what you
  assumed>
- unknown: <anything you could NOT verify. Write `UNKNOWN` and say what you
  tried. This is a legal, expected answer and it blocks the work — it is not
  a gap for you to paper over. Never guess a value, and never carry one
  across from another chain, provider, or module>
- contradicts the Card: <anything the Card or the contract got wrong, or
  "none">
- unratified choices: <any case the Card left open that you had to resolve to
  write a test, and the most conservative reading you took. State that Owner
  has not ratified it.>

## scenarios proposed by the developer

Pass 2 only. The developer cannot add tests; they propose cases in their
Manifest and you rule on them. A rejection is a signal, not a cleanup — the
reviewer reads this column, because a case the developer thought was real and
you dismissed is a design question.

- <their question, quoted>: accepted | rejected (<why>) | escalated
```

Notes:

  - `tests by obligation` moved here from the Implementation Manifest. It
    used to sit in a file the implementer wrote, describing the coverage of
    code it had just written. Same self-certification `_require_work_exists`
    is built to refuse; the fix is to ask the party that did not write the
    code.
  - `discovery` is not the MVP section with the label moved. In an MVP it
    recorded what a disposable prototype found; here it records what the
    tester went and looked at *before* writing a single assertion. That is
    the moment the information still exists in the world rather than in
    someone's head.
  - Do not claim coverage you did not exercise. `mark-approved` checks that
    the named test methods exist; it cannot check that they assert anything.
    A test that cannot fail is the one failure mode no mechanism here
    catches.
