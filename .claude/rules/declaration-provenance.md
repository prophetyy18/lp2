---
paths:
  - "architecture/**"
  - "docs/implement/**"
---

# Before you add or change a declaration here

**Existence is a hypothesis, not a warrant.** A capability, type, module or
vocabulary that no current consumer needs is a claim waiting to be tested, and
the test is cheap. Ask before you write:

1. **Trace it to the terminus.** Follow the value or call forward. If it ends
   in nothing, or ends in something already derivable, it has no job.
2. **Find the load-bearing consumer, not the declaring one.** An itemised
   `uses:` is still a claim. Which *capability* has a field that requires this?
3. **Quote the justification sentence.** Every unjustified declaration has
   one, and it is usually the only support. If the justification is itself a
   declaration ("it exists over there"), it is circular.
4. **Check the justification resolves.** `T0xx`, `ADR-xxx` and `G-*-xx`
   citations point at documents that must exist *here*. There is no task list
   and no ADR file in this repository.
5. **Classify the source.** Vocabulary from another domain is *wrong here* —
   retire it. A future capability in the right domain is not automatically
   wrong, but it may not hang on a gate nobody can check.

Then ask what would make it true, and whether that thing exists. Signer
justified itself with live execution; live execution needs a broadcaster, and
no contract declares one — so the hole was one level down.

**This is not a style note.** Three retirements in this repository were this
one shape — `Bar` inheriting a shape from a capability with zero consumers, the
whole `market-data` contract, and 35 borrowed task numbers. None of them
tripped a tool, because none of them changed anything.

Full method, worked examples, and why each step cannot be automated (step 2
misses 97% of healthy dependencies, structurally): `docs/design/DECLARATION-PROVENANCE.md`.
