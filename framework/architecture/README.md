# Architecture Framework (V0)

独立的架构子系统。它只回答三个问题，不含任何 workflow 概念。

```
future workflow
    ↓  (调用)
architecture framework     framework/architecture/
    ↓  (只读)
project metadata           architecture/
```

**依赖方向是单向的**：framework 不 import、不引用、不包含任何 workflow。
它只提供 `query.*` 函数和 `archctl` CLI，等待未来的 workflow 调用。

## 1. Source of truth

唯一事实来源是 YAML metadata，不是 Markdown：

| 路径 | 内容 |
|---|---|
| `architecture/contracts/<name>.yaml` | contract 定义（公开 interface） |
| `architecture/modules/<name>/module.yaml` | module 定义与显式依赖声明 |
| `modules/<name>/**` | module 的实现代码（私有） |
| `framework/architecture/*.py` | 本框架本身 |

**实现代码不是 source of truth。** 一个 module 的公开行为只由它发布的
contract 决定；实现只能佐证，不能被读取来补足 contract 的不足。

## 2. Module dependency 怎么表示

只存在两种边，都在 YAML 里显式声明：

```yaml
# architecture/modules/backtest/module.yaml
name: backtest
provides_contracts: [backtest-api]        # 我实现哪些 contract
depends_on:
  - contract: pricing-api                 # 我依赖哪个 contract
    uses: [position.mark, pricing.quote]   # 我具体用它的哪些 capability
    reason: value the simulated portfolio
```

```yaml
# architecture/contracts/pricing-api.yaml
requires: [market-data-api]               # 我建立在哪之上
provides:
  - id: position.mark
    kind: function
    signature: "position.mark(portfolio: Portfolio, at: datetime) -> Decimal"
```

**不存在 `module → module` 边。** module 之间只经由 contract 连通；
validator 会把直接依赖另一个 module 报成 `ILLEGAL_DEPENDENCY`。
module 级的边是**推导**出来的（`graph.direct_module_edges`），只读，不可手写。

```
module backtest ──uses──▶ pricing-api ◀──requires── market-data-api ◀──uses── module market-data
                          (contract)          (contract)                     (contract)
```

## 3. Boundary 怎么判断

允许读取（allow-list，除此一律拒绝）：

```yaml
modules/<self>/**          自己的实现
architecture/**            全部 metadata：所有 contract + 所有 module 声明
readable_extra: [...]      module.yaml 里显式授予的额外路径
```

`architecture/**` 可读是刻意的：contract 和 module 声明**就是**公开面。
读 `architecture/modules/pricing/module.yaml` 合法，读 `modules/pricing/*.py` 不合法。

不可读：其他任何 module 的实现、`framework/**`（方向反了——是 framework 调用
module）、仓库外的路径。

读不到时的返回不是「放宽权限」，而是：

- `BOUNDARY_VIOLATION` — 路径越界，附 `remedy: ARCHITECTURE_CHANGE_REQUIRED`
  和该 module 已声明的 contract 列表，指出应该改哪个 contract。
- `CONTRACT_INSUFFICIENT` — 需要的 capability 在 contract 里不存在。
  修法是补 contract，**不是**去读对方的实现。

`readable_extra` 想覆盖别的 module 的树，validator 直接报 `BOUNDARY_VIOLATION`：
授予权限不能绕过边界，只能放大边界。

## 4. Contract 修改后怎么 impact analysis

```bash
archctl snapshot --out architecture/.snapshots/baseline.json
# ... 改 contracts ...
archctl diff architecture/.snapshots/baseline.json
```

diff 得到 changed contract 集合（以及是否 breaking：删除 capability 或
`requires` 即为 breaking），再对每个 changed contract 跑影响分析：

- **direct** — 发布该 contract 的 module（要改实现）+ 显式声明依赖它的
  module（要重新读 contract）。
- **indirect** — 沿 `requires` 反向闭包 BFS：消费了建立在该 contract 之上的
  contract 的 module，距离 = 闭包距离 + 1。

两个距离分开报，因为补救方式不同：direct 要重新读接口，indirect 要确认
「我用的那个 capability，语义是不是还一样」。

## 5. Error codes

| code | 含义 |
|---|---|
| `BOUNDARY_VIOLATION` | 读了不在 allow-list 里的路径 |
| `ILLEGAL_DEPENDENCY` | 直接依赖 module / contract 多发布者 / 重复声明 |
| `CONTRACT_INSUFFICIENT` | 需要的 capability 不在 contract 里（不是去读实现） |
| `ARCHITECTURE_CHANGE_REQUIRED` | 补救方向：改架构，不是放宽边界 |
| `UNKNOWN_MODULE` / `UNKNOWN_CONTRACT` | 引用解析不到 |
| `CYCLE_DETECTED` | contract requires 成环 |
| `INVALID_METADATA` | YAML 本身不可用 |

## 6. 用法

```bash
# Q1 能看什么
archctl readable backtest
archctl check-paths backtest modules/pricing/engine.py

# Q2 能依赖什么
archctl depends backtest
archctl consumers pricing-api

# Q3 改了谁受影响
archctl impact pricing-api
archctl impact market-data-api --capability series.get

# 图与校验
archctl graph
archctl graph --dot > arch.dot
archctl validate            # 有 ERROR 时 exit 1
```

Python 调用（未来的 workflow 会走这个）：

```python
from framework.architecture import load, query

arch = load()
query.readable(arch, "backtest")            # Q1
query.dependencies(arch, "backtest")       # Q2
query.blast_radius(arch, "pricing-api")    # Q3
query.check_paths(arch, "backtest", paths) # Q1 应用到具体路径
query.validation_report(arch)              # CI gate
```

全部命令支持 `--json`。

## 7. 测试

```bash
python3 -m unittest discover -s framework/architecture/tests -t .
```

26 个用例，覆盖三个问题各自的正例和必须失败的负例。

## 8. 故意没做

- **Task / Spec / Reviewer / Handoff / Workflow state / Bug lifecycle** — 不属于架构层。
- **插件系统、注册表、provider 抽象** — V0 不需要。
- **状态机** — 没有 workflow 状态可言。
- **自动读取源码生成 contract** — 那会让实现重新变成 source of truth，正是要避免的。
- **能力协商 / 版本兼容矩阵** — 有 `version` 字段和 breaking 判定，但没做 semver 求解。
- **强制执行机制（hook / sandbox）** — 本框架只做**判定**。真正的强制应该由未来
  workflow 调用 `check_paths` 后自行执行；框架不接管进程。
- **`contracts/` 顶层目录** — metadata 目前统一在 `architecture/` 下。

## 9. 依赖

Python 3.10+ 与 PyYAML。除此之外没有第三方依赖，不 import 项目任何代码。
