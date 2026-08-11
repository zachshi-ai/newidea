# 决策债务 · Decision Debt

> 把「悬而未决的决策」当成一笔**会自动计息的债务**来管理。
> A methodology + a zero-dependency CLI that treats postponed decisions as compounding debt.

---

## 一句话

任务有「完成态」、日程有「时间点」，但**决策两者都没有**——它只是一个悬而未决的开放环路，会在你脑子里一直占着内存、持续吃利息，直到你「拍板」那一刻才结清。`decision-debt` 给这种隐性认知成本一个可见的「账本」和一张「催款单」。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 知识工作者、产品经理、技术负责人、创业者、管理者——任何每天要做大量微决策的人。 |
| **场景** | 日常工作中产生大量小决策（选哪个供应商、接口怎么定、要不要现在回这封邮件、这周发不发版）。其中相当一部分被推迟：「我再想想」「下周再说」「让我睡一觉再决定」。 |
| **问题** | 这些**被推迟的决策无处安放**：它们太小，进不了任务清单（没有明确的「完成」）；太不确定，写不进文档；又太重要，不能忘。于是它们只活在脑子里，累积成**「决策债务」**——持续消耗注意力（认知利息），时间久了要么**被遗忘变成危机**，要么**随时间衰减被「默认掉」**（不是你选的，是时间替你选的）。 |
| **价值与意义** | 1) **外化认知负担**：把脑子里的开放环路落到磁盘，腾出工作记忆。<br>2) **防止决策「过期」**：用债务分主动浮出正在变贵、变陈旧的决策。<br>3) **建立「决策日志」**：每次结清都留痕，形成轻量级 ADR，让决策可回溯、可复盘。<br>4) **用财务隐喻让隐性成本可量化**——「你今天背着 407 分的决策债」比「你有几个事没定」更有行动力。 |

---

## 核心思想：决策 = 计息债务

借鉴「技术债务」，我们把一笔开放决策视为一笔债务：

- **本金 × 时间**：决策越大（`weight` 权重）、挂着越久（`age` 年龄），欠的越多。
- **重新打开 = 上调利率**：一个反复「拍板又反悔」的决策（`reopens`），利率更高——它在暗示这个决策风险大、信息不充分。
- **长期不审视 = 高利贷**：一笔决策如果开了之后**你再也不看它**（`staleness` 陈旧度），它最危险——因为你既没结清也没主动管理，它在后台默默复利。

只要决策处于 `open`，每天计息；`commit`（拍板）或 `abandon`（放弃）即结清、停止计息，并写入决策日志。

### 债务分公式（确定性、可测）

```
年龄 AGE           = 今天 − 开启日
基础利率 BASE       = 1 + 0.5 × 重新打开次数
陈旧度 STALENESS   = 1 + min( (今天 − 上次审视日) / 14 , 5 )     # 14 天审视周期，最高 6×
─────────────────────────────────────────────────────────────
债务分 DEBT         = 权重 × AGE × BASE × STALENESS     （四舍五入到 1 位小数）
```

- 关闭的决策（committed / abandoned）债务恒为 0。
- 默认常量（在 `decision_debt.py` 顶部可调）：`DEFAULT_WEIGHT=3`、`REOPEN_RATE=0.5`、`REVIEW_HORIZON_DAYS=14`、`STALENESS_CAP=5.0`。

---

## 安装（零依赖）

只需 Python 3.8+，标准库即可，无需 `pip install` 任何东西。

```bash
# 直接用
python3 decision_debt.py init

# 想用 decision-debt 这个命令名？做个软链（可选）
chmod +x decision_debt.py
ln -s "$(pwd)/decision_debt.py" /usr/local/bin/decision-debt
decision-debt init
```

数据存在当前目录的 `.decision-debt/ledger.json`，也可用 `--ledger 路径` 或环境变量 `DECISION_LEDGER` 指定。

---

## 命令速查

```bash
decision-debt init                                  # 在当前目录建空账本（重复执行会拒绝，--force 才覆盖）
decision-debt add --title "定价模式" --weight 5 \
    --option "按席位" --option "按用量" --option "包档"   # 开启一笔新决策
decision-debt list [--status open|committed|abandoned] [--json]
decision-debt review --top 5                        # 列出最烫手的 N 笔（还债仪式用）
decision-debt touch <id>                            # 今天审视过了，重置陈旧度
decision-debt commit <id> --outcome "选 Postgres"   # 拍板结清
decision-debt abandon <id> --reason "不再需要"      # 放弃结清
decision-debt reopen <id>                           # 反悔，重新打开（利率 +50%）
decision-debt report                                # 总览：计数 / 总债务 / 最烫 / 账龄分布
decision-debt export                                # 导出 markdown 决策日志（ADR-lite）
```

---

## 一个真实样例

见 [`examples/`](examples/)。一个创业团队在 `2026-08-12` 的账本快照：

```text
Decision Debt Report  (as of 2026-08-12)
================================================

Inventory:
  open        : 5
  committed   : 1
  abandoned   : 1
  total       : 7

Total open debt: 407.5
Hottest: pricing-model = 160.0  (Pricing model)

Open decisions by age:
  0-7d   : 1
  8-30d  : 4
```

`pricing-model`（定价模式）一笔就占了 160 分——权重 5、挂了 28 天、是全队最贵的开放决策，正是 `review` 该优先处理的。完整台账见 [`examples/sample-ledger.json`](examples/sample-ledger.json)，决策日志见 [`examples/sample-export.md`](examples/sample-export.md)。可用 `python3 examples/build_examples.py` 重新生成。

---

## 还债仪式（每周一次）

1. `decision-debt review --top 5` —— 看最烫手的 5 笔。
2. 对每一笔，逼自己三选一：
   - **能定** → `commit <id> --outcome "..."`（拍板，停息）。
   - **不该你定 / 已无意义** → `abandon <id> --reason "..."`（结清止损）。
   - **还缺信息** → 写下「还差什么」补进 context，然后 `touch <id>`（重置陈旧度，承认你在管它）。
3. `decision-debt report` 看总债务是否在下降。**目标是趋势下降，不是清零**——永远有开放决策很正常，让它在可控、被审视的状态才是目的。

详见 [`METHODOLOGY.md`](METHODOLOGY.md)。

---

## 验收标准与测试

12 条验收标准已全部转成自动化测试（`tests/test_debt.py`，23 个用例，`unittest` 标准库）：

```bash
python3 -m unittest discover -s tests -v
```

覆盖：公式确定性（年龄 / 陈旧度 / 重开利率 / 陈旧度上限 / 关闭归零）、`init` 幂等保护、`add` 字段与唯一 id 与权重校验、`list` 按债务降序与 JSON 输出、`review --top N`、`touch` 降低次日债务、`commit`/`abandon` 排除出 open、`reopen` 累加并抬高利率、`report` 计数与总额、`export` 合法 markdown，以及一条端到端子进程 smoke 测试。

---

## 项目结构

```
newidea/
├── decision_debt.py          # 核心 CLI（单文件，纯标准库）
├── tests/
│   └── test_debt.py          # 验收测试套件
├── examples/
│   ├── build_examples.py     # 用真实工具复现样例的脚本
│   ├── sample-ledger.json    # 样例台账
│   ├── sample-report.txt     # 样例报告
│   └── sample-export.md      # 样例决策日志
├── METHODOLOGY.md            # 方法论、仪式与 FAQ
├── README.md
└── LICENSE
```

---

## 设计取舍

- **为什么用 JSON 而不是 markdown 做存储**：要确定性计分、要排序、要测试，JSON 可靠解析；人类可读的视图用 `list` / `report` / `export` 现生成。
- **为什么是 CLI 而不是 App**：决策记录要像 `git` 一样轻、快、可在任何目录就地起账本；零依赖保证随处可跑。
- **为什么债务分能含小数 / 不是整数**：它是一个**相对排序信号**，不是绝对预算；精确到 0.1 足够区分，又避免「正好 100 分」这类伪精确感。

---

## License

MIT © 2026
