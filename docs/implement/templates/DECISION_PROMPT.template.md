# Decision Prompt templates

The ONLY thing the Owner sees in normal operation. Four normal forms and one
exceptional design blocker form.

An `mvp_developed` capability is not usable by any other module. Nothing
downstream may build on it; there is no yellow flag.

Owner-facing prompts are in Chinese. The role files and this repository's
other prose stay in English: the Owner reads the prompts, the agents read the
role files, and neither has to read the other's language.

## Card gate — before any code is written

The first gate, and the only one where the Owner is asked to decide something
they have not yet paid for. Everything after this point is cheaper to stop.

```
<module> / <capability>   mode=<full|mvp>

做什么   <signature, one line>
怎么测   正常  <one line>
         边界  <one line>
         异常  <one line>
         失败  <one line, or "无法写：契约未声明 error code">
没定的事 <each thing the Card refuses to decide, one line each>

[go / redo / abandon]
```

Rules for filling it in:

  - **The Owner sees the Card's test *plan*, not tests.** No test exists at
    this gate — the developer has not run. What the Owner is checking is
    whether the plan is the right plan, which is far cheaper to judge than a
    pile of finished tests.
  - **`没定的事` is not padding.** It is the list of things the contract does
    not decide and the Card therefore will not invent. If it is empty, say
    so. A Card that silently fills those gaps has widened the design from
    inside the module, which is the one thing it must never do.
  - **Name the consequences, not the mechanism.** "排序 backtest 能观察到"
    is a fact the Owner can rule on; "建议用 fixture 播种" is a
    recommendation they must first understand.
  - Never paste the Card. It is 30+ fields and the Owner will not read it.
    The Card is the subagent's input; this is the Owner's view of it. Point
    at the path if they want the whole thing.
  - `mode` is decided here, and it is the only place.

## MVP path — after developer

```
✓ <module>/<capability> MVP ready (manifest OK, imports clean, <N> tests pass).
 记为 mvp_developed？[y / not-yet / abandon]
```

## Full path — after reviewer

```
✓ <module>/<capability> reviewer: <VERDICT>  scores: c=<X> b=<X> t=<X> q=<X>
 批准并记为 fully_approved？[y / changes / abandon]
```

## Reopen path — Owner turns an MVP into a capability other modules may use

```
⚠ <module>/<capability> 从 MVP 重开为 full。在 fully_approved 之前其他模块
  不可消费；已有源码和测试保留。
```

## Design blocker — exceptional path

```
⚠ <module>/<capability> DESIGN_BLOCKED (<contract|card>)：<一句话冲突>。
  需要裁决：<一句话>；blocker: docs/implement/<module>/<capability>.design-blocker.md
```

---

Notes for the dispatcher:

  - Never show the Owner anything longer than ~100 words in a single message.
  - Background / history / spec stays in the agent prompts and CLI output.
  - The ~100-word ceiling applies to the *prompt*, not to the reasoning
    behind it. When a decision needs context, put the context in your own
    message to the Owner and keep the prompt itself short.
  - When Owner answers `not-yet` / `changes` / `redo`, ask one short
    follow-up: "what specifically needs to change?" Capture the answer
    and pass it back to the relevant subagent on the next loop.
  - When Owner answers `abandon`, call
    `./bin/python -m tools.implement.state abandon <module> <cap>` and move to
    the next capability without further ceremony.
