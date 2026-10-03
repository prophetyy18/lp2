# Declared type shapes

`architecture/schemas/<contract>.yaml` holds the shape of every type that
contract's capabilities name. The file name is the owning contract; the top
level maps a `TypeName` to a JSON Schema (draft 2020-12). So a type declared
in `example-api.yaml` as `PoolKey` is referenced from anywhere as
`example-api.PoolKey`.

**This directory is currently empty of schemas.** The three that were here
(`robinhood-rpc-api`, `robinhood-protocol-api`, `robinhood-signer-api`) were
withdrawn on 2026-10-03 with the modules they described; see
`CLAUDE.md` for why. The examples below use invented contract names, so that
nothing here points at a file that does not exist — a syntax example that
names a real-looking but absent contract is the same defect in a smaller
package.

## Why this directory exists

A capability can name its types two ways, and until this directory existed only
one of them was even visible to the tooling:

```yaml
input:  { schema: example-api.PoolKey }   # explicit — was never resolved
signature: "replay.state.checkpoint(c: EventCursor) -> PoolCheckpoint"  # prose
```

The explicit form was parsed into an opaque string and never checked.
`archctl validate` passed with 29 references to schemas that did not exist.
The prose form was not parsed at all, and it names 67 more types.

Both are the same defect wearing different clothes: **a name with no shape is
a promise nobody can test.** A tester cannot state an expected value for a
type whose fields are undeclared, and two developers can both be "right" about
what `RunRecord` holds until someone writes it down.

`archctl validate` now reports both:

| code | severity | meaning |
|---|---|---|
| `SCHEMA_DANGLING` | ERROR | an explicit `input`/`output`/`payload` ref resolves to nothing |
| `SCHEMA_UNDECLARED` | WARNING | a `signature:` names a type with no declared shape |
| `SCHEMA_AMBIGUOUS` | WARNING | one bare name is declared by two contracts, so a signature cannot resolve it |

`SCHEMA_DANGLING` is an ERROR because a ref to nothing is not a weaker
promise than a promise kept — it is no promise, stated as though it were one.
`SCHEMA_UNDECLARED` is a WARNING while the shapes are being filled in;
promoting it to ERROR is the signal that the gap is closed.

## Conventions

**Format.** JSON Schema draft 2020-12, written in YAML. A type with no
constraints is still worth declaring — `{"type": "object"}` says "this is a
record, not a number or a list", which is a real (if modest) fact.

**`x-` keywords.** JSON Schema cannot say anything about a fixed-point
encoding or an on-chain width, and both matter here:

```yaml
SqrtPriceX96:
  type: integer
  minimum: 0
  x-encoding: q64.96        # value = real * 2**96
  x-solidity-type: uint160
  x-source: v4-core SqrtPriceMath; Q96 = 2**96
```

Every `x-` keyword carries `x-source`. An encoding asserted without a source
is a guess wearing a citation's clothes, which is the thing `AGENTS.md` §4
exists to prevent. If you cannot cite where the encoding comes from, use
`UNKNOWN` or leave the field out.

**Naming.** Field names are `snake_case`. On-chain field names are *not*
translated: a field that is `sqrtPriceX96` on chain is `sqrt_price_x96` here
only if the contract says so, and where the contract already uses one spelling,
schemas use that same spelling. Two spellings of one thing is a search
failure waiting to happen.

**`$ref` is a JSON Pointer into the same file.** One type referring to
another is `$ref: "#/Address"`, not `$ref: "Address"`. A bare name is a
relative URI pointing at a *document* called `Address`, which resolves to
nothing and fails at validation time rather than at authoring time. Because
the file's top level maps `TypeName` to schema, the pointer to a sibling is
simply `#/<TypeName>` — no `$defs` needed, and each file stays independently
validatable. Every `$ref` today is intra-file; a cross-file one would need a
resolved base URI and is a decision not yet made.

**Every schema is tested against what it refuses.** A schema's entire value is
in the instances it rejects; one that accepts everything turns "this type has
no declared shape" into "this type has a shape that says nothing", which is
harder to notice. `tests/test_architecture_schemas.py` pins the refusals. The
first version of `PoolKey.fee` bounded the fee at the `uint24` range while its
own description said the maximum was 1_000_000 — so a fee V4 would revert on
validated clean, and the mismatch sat in a description nobody was checking
against a constraint. That is the failure this guards, and the test names it.

**Ownership.** A type belongs to exactly one contract — the one that defines
it, not the one that happens to use it most. If a second contract needs the
same shape, it depends on the owning contract; it does not re-declare it. A
name two contracts both declare is reported as `SCHEMA_AMBIGUOUS` rather than
resolved by a guess.

**Do not write a shell.** A schema with `type: object` and no properties,
written only to turn a warning off, is worse than the warning: it makes an
undeclared type look declared. Every schema here should carry at least the
fields its contract's description already names. Where a type's fields are a
genuine open design question, that is an Architecture Designer decision, and
the honest state is no schema yet.
