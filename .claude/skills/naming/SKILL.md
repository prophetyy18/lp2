---
name: naming
description: Repository naming rules. Read before naming anything that outlives the line — a function, a class, a module, a file, a schema field, an error code, a state value, a capability id. Long-term, a name is a comment that cannot go stale.
when_to_use: Any time you are choosing an identifier rather than using one. Most code is already named; the moment you write a new one, this applies.
---

# Naming

Clean Code chapter 2. A name is a comment that cannot go stale: a comment
goes wrong the moment the code changes, a name does not, because changing the
code means renaming it. **A bad name is not a style problem — it is a fixed
cost every later reader pays**, and this repository's readers are agents that
grep.

Most important first:

- **Make it searchable.** Agents find things by grepping, and a name they
  cannot grep for is indistinguishable from one that does not exist. Longer
  names win.
- **Match length to scope.** `i` is fine inside a three-line loop. A name used
  across files has to read at a glance. Do not stretch a local variable into a
  sentence just because long is better.
- **A name that needs a comment to explain it has failed.**
- **Do not let the name mislead.** `account_list` implies it is a list — call
  it `accounts`. Abbreviations that mean something else elsewhere (`hp`,
  `aix`, `spx`) are misinformation, not brevity.
- **One word per concept.** Do not use `fetch` / `retrieve` / `get`
  interchangeably for one job; a reader then has to remember who wrote the
  library. But do not sacrifice accuracy for consistency: if `add` sums in one
  abstraction and inserts in another, the second one is `insert`.
- **Make real distinctions.** `money_amount` and `money` are the same name.
  `account_data` and `account` are the same name. `a1 a2 a3` carry no
  information.
- **Never encode the type in the name.** Especially in Python: no `str_x`, no
  `dict_of_positions`.
- **Nouns for classes, verbs for functions.** Accessors and predicates take
  `get_` / `set_` / `is_`.
- **Context comes from the class, not a prefix.** Put `sqrt_price` inside
  something called `PoolState` rather than writing `position_sqrt_price`.
- **Never abbreviate a domain term.** `sqrt_price_x96`,
  `fee_growth_global0_x128`. These correspond to on-chain fields, and
  abbreviating breaks the path back to the chain.
- **Put the unit in the name.** `fee_wei`, `amount_usdg`, `block_number`. This
  codebase ranges over block numbers, not wall time; a bare `timestamp` or
  `stale_tolerance` is the vocabulary that already went wrong once.

## Test file names have a different rule

They are not this rule. `tools/implement/naming.py` owns them, because module
names and capability ids contain characters that cannot appear in a Python
path. Ask it:

```bash
./bin/python -m tools.implement.naming <module> <capability>
```

It prints the path and the exact command to run it. Composing the name any
other way reads as a scope violation, because the write-scope audit matches on
the same rule.
