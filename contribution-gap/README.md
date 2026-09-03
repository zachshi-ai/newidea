# 贡献错觉 · Contribution Gap

> 「这个家总是我在撑」——两个人的感觉加起来是 130%，但一个家只有 100% 的活。
> A zero-dependency CLI that turns "I always do the dishes" into a ledger: real shares, a fairness gini, chore monopolies, and a perception audit — because both of you honestly overclaim, and the total always exceeds the household.

---

## 一句话

每个共同生活的家庭里都有过同一场争吵：「总是我在洗碗」。双方都真诚地相信自己做得更多——社会心理学的经典结论（Ross & Sicoly, 1979）是：让夫妻各自估计自己的贡献占比，**两个数字加起来常年超过 100%**，因为高频可见的活（洗碗、接送）容易被记住，低频漫长的活（大扫除、采购、修东西）容易被遗忘。争吵的悲剧在于：**双方都没撒谎，双方都在描述自己的记忆，而记忆不等于账本**。日历记着会议，Jira 记着工单，唯独没有一本账记着「这个家上周谁做了什么、做了多久」。`contribution-gap` 就是这本账：每次做完家务记一行（谁、什么活、多少分钟），账本给出四个读数——**实测份额**、**公平基尼**（0.033 的总账可以同时挂着 5 个「领地」）、**部门垄断**（总量公平但「她拥有厨房、他拥有户外」）、**感知对账**（自报 70% vs 实测 53.3%，以及全家感知盈余 +30 分）——外加 28 天趋势（下滑通常先于争吵被看见）。它不裁判谁更爱这个家，它只回答一个问题：**你们吵的到底是同一个家吗？**

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 共同生活的伴侣/夫妻（「总是我洗碗」专业户）；合租室友（轮值表名存实亡的flat）；家庭会议主持人（想用数据代替争吵的那一位）。 |
| **场景** | 又一次「总是我做」争吵后的冷静期（跑 `report` 摊数据）；每月一次的家庭对账（28 天趋势告诉你公平在改善还是恶化）；轮值表重谈（领地清单告诉你哪几个部门需要轮换）；「你根本看不见我做的事」时刻（感知对账让双方第一次看见自己的记忆偏差）。 |
| **问题** | **家务没有账本，贡献全凭记忆**：① 记忆有系统性偏差——各人自报贡献之和常年超 100%，双方都真诚高估，争吵无解因为「证据」本身就是两份矛盾的记忆；② 总量公平掩盖结构垄断——就算总分钟数接近，「谁拥有哪几个部门」的不平衡完全不可见（碗、灶、采购、垃圾、修理）；③ 下滑不可见——一方工作变忙、悄悄少做，是从「感觉不对」到「爆发争吵」之间数周的真空期，没有任何仪表盘亮灯。 |
| **价值与意义** | 1) **贡献第一次有了实测值**：份额按分钟统计，不是按「谁嗓门大」；记账 5 秒一条，比争吵便宜三个数量级。<br>2) **感知偏差从指责变成读数**：感知盈余 +30 分意味着「你们各自活在两个家里」——这不是谁的错，是 availability bias 的数学必然；把「你撒谎」变成「我们都高估，差值在这」。<br>3) **结构垄断现形**：总账 0.033 的基尼（balanced）可以同时挂 5 个领地——「公平」不是总量问题，是部门所有权问题；轮值表该轮的是那 5 个领地。<br>4) **下滑先于争吵被看见**：28 天基尼从 0.040 漂到 0.107，趋势读数在人提「分开」之前亮灯。<br>5) **零依赖 + 纯本地**：Python 3.8+ 标准库，账本就是一个 JSONL 文件——家事数据不属于任何云端。 |

---

## 核心思想：账本 → 四个读数 + 一次对账

每条家务是一行 JSONL：`{"kind": "chore", "date": "2026-08-30", "person": "maya", "chore": "dishes", "minutes": 20}`。每份自我认知也是一行：`{"kind": "claim", "person": "maya", "pct": 70}`（「我觉得我做了 70%」）。账本在其上算出五个数：

| 概念 | 定义 | 回答的问题 |
|---|---|---|
| **实测份额** | 每人分钟数 ÷ 总分钟数 | 这个家的活，实际是怎么分的？ |
| **公平基尼** | 每人总分钟分布的 Gini 系数（0 = 绝对平，两人上限 0.5） | 总量上有多不公平？≤0.10 balanced / ≤0.20 tilted / >0.20 lopsided |
| **部门垄断（领地）** | 某项家务 ≥80% 的分钟在同一人手里（且总量 ≥60 分钟） | 总量公平的下面，藏着哪几个「谁的活」？ |
| **感知盈余** | Σ 各人自报份额 − 100% | 你们的自我印象加起来，超出了多少个现实？ |
| **28 天趋势** | 最近 28 天基尼 vs 前 28 天 | 公平在改善、持平，还是正在下滑？ |

**阈值是家庭约定，不是自然法则**：两人家庭基尼 = |2p−1|/2，所以 60/40 → 0.10、70/30 → 0.20——档位线（0.10 / 0.20）就钉在这里：60/40 以内叫 balanced，70/30 以内叫 tilted，超过 70/30 叫 lopsided。**垄断线 80% 是「所有权」的门槛**：一项家务八成以上永远是你做，它就不再是「分工」，是「你的活」；60 分钟的最低门槛把一次性的 5 分钟小活排除在部门之外。**感知对账刻意温和**：gap 是「你的记忆 vs 账本」，不是「你 vs 对方」——工具假设所有人都会高估，包括记日志的那个人。

四条诚实条款刻在实现里：**孤家寡人不评分**——窗口里只有一个人有家务记录，基尼显示 n/a 并提示「账本只听得见一方」（exit code 里的 SOLE PLAYER 红旗）；**样本薄不判趋势**——28 天对另一半不足 6 条记录或只有一方记录，趋势显示 unknown 而不是硬猜；**坏行跳过且计数**——残缺记录永远不致命，账本头行如实报「N broken lines skipped」；**一人家庭不领地化**——窗口内只有一方时跳过垄断检测，避免把「独居」检测成「100% 垄断」。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。账本默认是当前目录的 `ledger.jsonl`。

```bash dd:ignore
python3 contribution_gap.py log --person maya --chore dishes --minutes 20   # 记一条家务
python3 contribution_gap.py claim --person maya --pct 70                    # 记一份自我认知
python3 contribution_gap.py report                                          # 摊牌
```

## 命令速查

```bash dd:ignore
python3 contribution_gap.py log --person maya --chore dishes --minutes 20 \
       --date 2026-08-30 --note "after dinner"      # 谁在几号做了什么活，几分钟
python3 contribution_gap.py claim --person maya --pct 70   # 「我觉得我做了 70%」
python3 contribution_gap.py report                   # 份额 / 基尼 / 领地 / 感知对账 / 趋势 / 红旗
python3 contribution_gap.py report --window 28       # 只看最近 28 天（下滑通常在这里现形）
python3 contribution_gap.py report --format json     # 机读
python3 contribution_gap.py report --fail-under 0.20 # 门禁：基尼 > 0.20 则 exit 4
python3 contribution_gap.py report --file flat.jsonl # 换一本账（合租的公共账本）
```

## 一个真实样例

两人家庭八周账本（`python3 examples/build_examples.py` 可从零重建，100 条家务 + 2 份 claim，全部数字钉死，输出跨机器逐字节可复现）。maya 与 noor，总账看着相当健康（[`examples/sample-report.txt`](examples/sample-report.txt)）：

```text dd:ignore
shares (by minutes):
  maya                  :  53.3%  2240 min / 54 chores
  noor                  :  46.7%  1960 min / 46 chores

  gini                : 0.033  balanced
  chore monopolies    : 5 fiefdoms (>= 80% of a chore in one pair of hands)
    cooking        -> maya       87.5% of 640 min
    dishes         -> maya       83.3% of 480 min
    groceries      -> noor       87.5% of 480 min
    fixing         -> noor       100% of 240 min
    trash          -> noor       87.5% of 160 min
  trend               : worsening — 28-day gini 0.107 vs 0.040 (prior 28 days)

perception audit (latest claim vs the ledger):
  maya                  : claims 70%   actual 53.3%   gap +16.7 pts   <- overclaim
  noor                  : claims 60%   actual 46.7%   gap +13.3 pts
  perception surplus  : +30.0 pts — together you claim 130% of one household
```

读法：**总量 0.033，几乎完美——但这本账挂着 8 面红旗**。① 领地：总量公平是假象，家里按部门瓜分了——厨房（dishes 83%、cooking 88%）属于 maya，户外（groceries 88%、trash 88%、fixing 100%）属于 noor，谁也没「多干」，但谁也没法替对方干；② 感知盈余 +30：maya 自报 70%（实测 53.3%），noor 自报 60%（实测 46.7%）——**双方都在真心的状态下多报了**，130% 的自我认知塞不进 100% 的现实，这就是那场争吵的数学结构；③ 趋势在恶化：28 天前两人还是 48/52（noor 略多），最近 28 天滑到 61/39——基尼从 0.040 漂到 0.107，窗口视图里最近六次洗碗、六次做饭全是 maya（[`examples/sample-report-window.txt`](examples/sample-report-window.txt)），overclaim 甚至换了人：近 28 天 noor 的 gap 达到 +20.7 分。争吵发生时通常已经太晚——账本在四周前就看见了。

## dogfood：样例账本就是端到端自证

这本点子需要的输入是一本需要真人 8 周日复一日记录的账——和乐观税的收据一样，**工具出现之前，没有人记这本账**，作者也不例外。所以 dogfood 采取端到端形态：`examples/build_examples.py` 用本工具的 CLI 全流程（`report`、`--window`）从钉死的账本生成全部样例输出，CI 每次推送逐字节校验（`--check`）——工具在自己生成的数据上被完整消费，`DogfoodTests` 把 8 个头条数字（份额 53.3/46.7、基尼 0.033、5 个领地、盈余 +30、趋势 0.040→0.107、窗口 60.7%）钉进测试。真实家庭的账本，从你家记下第一只碗开始。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_contributiongap.py`](tests/test_contributiongap.py)，96 个用例，`unittest` + 临时账本文件，CLI 全流程集成）：

```bash dd:ignore
python3 -m unittest discover -s contribution-gap/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 份额按分钟聚合；pct = 分钟占比；按分钟降序同名按名字；人名归一化（trim + lower） | `TestShares`（4 例） |
| 基尼：绝对平 = 0；两人公式 = \|2p−1\|/2（60/40→0.1、90/10→0.4）；n 人上限 (n−1)/n；尺度不变性 | `TestGini`（9 例） |
| 档位边界 0.10 / 0.20；单方窗口 n/a；报告档位与基尼一致 | `TestBands`（3 例） |
| 领地：≥80% 且家务总量 ≥60 分钟才触发；排序按总量；报告计数 | `TestMonopolies`（5 例） |
| 连击：同一人连续 ≥3 次触发；轮换即断；回看窗口 6 次；按家务独立 | `TestStreaks`（5 例） |
| 趋势：28 天 vs 前 28 天，worsening / improving / flat（±0.05）/ unknown 四判；半边样本薄（<6 条或单方）拒判；锚定账本最大日期，与墙钟无关 | `TestTrend`（8 例） |
| 感知对账：gap = 自报 − 实测；>15 分才标 overclaim；每人取**最新**一份 claim；盈余 = Σ自报 − 100，且需 ≥2 份可对账 claim；0% 与 100% 合法 | `TestPerception`（8 例） |
| 窗口：`--window N` 限定份额/基尼/领地/连击；锚点 = 账本最大日期而非今天；退化窗口拒绝 | `TestWindow`（5 例） |
| 红旗：盈余 >20、个人 overclaim、≥2 个领地、连击、趋势恶化各自触发；干净账本**零误报**；单方 SOLE PLAYER | `TestRedFlags`（7 例） |
| 账本解析：非 JSON / 缺 kind / 未知 kind / 坏日期 / 空人名 / 空活名 / 零负分钟 / bool 与 NaN 分钟 / 越界与 bool pct 全部拒收；坏行跳过且计数；空行免费；乱序账本按日期排；小数分钟合法 | `TestLedgerParsing`（18 例） |
| CLI：log 追加并校验、claim 记录并校验、report 全流程 + json + `--fail-under` exit 4、缺账本 exit 2、空账本 exit 3、输出确定性 | `TestCLI`（13 例） |
| 零依赖：AST 级检查 import 不出标准库白名单 | `TestZeroDependencies`（2 例） |
| **dogfood：样例账本 100 条 + 2 claim；53.3/46.7；基尼 0.033；5 领地归属；盈余 +30（gaps +16.7/+13.3）；连击 cooking/dishes ×6；趋势 0.040→0.107；窗口 60.7% + tilted；文本渲染含全部头条** | `DogfoodTests`（8 例） |
| 样例同步：账本与两份样例输出可从零重建且逐字节一致 | `ExamplesSyncTests`（1 例） |

## 项目结构

```
contribution-gap/
├── contribution_gap.py
├── tests/test_contributiongap.py
├── examples/build_examples.py
├── examples/ledger.jsonl
├── examples/sample-report.txt
├── examples/sample-report-window.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
