# 来得及 · Make It

> 通勤不是时长，是分布：用平均值做出门决定，等于用一半的迟到率上班。
> A zero-dependency CLI that treats the daily commute as what it is — a distribution, not a number. Per-route quantile portraits, an on-time probability for "if I walk out now", the last departure that still makes 09:00, and the honest refusals when the ledger is too thin to promise any of it.

---

## 一句话

导航 App 告诉你「40 分钟」，你就在 8:20 出门——可通勤时长不是一个数，是一个分布：P50 是 40 分钟，P90 是 47 分钟，**用中位数做决定意味着约一半的日子你在赌**。迟到之后大脑只记得最近一次，从不记得是哪条线、哪个出门时段在惯犯；而「晚 5 分钟出门」的真实代价被早高峰放大，没有任何工具告诉你放大系数。`make-it` 的立场：**通勤决策的最小可行单元不是「平均多久」，是「我手里的时间，覆盖了这个分布的百分之几」**。工具从一本可手编的通勤账本（CSV，一行一次通勤）算出五本账：**画像**（`stats`：每条路线的 P50/P80/P90/最差、准点率、贴线次数、晚出门通胀）、**裁决**（`now`：「现在走来得及吗」——用经验分布回答概率，SAFE / RISKY / DEAD 三档判定 + exit code）、**反解**（`leave`：「要赶上 9:00，最晚几点出门」——解到出发窗口自洽为止，不收敛就取最保守解；窗口已关时诚实说，不给负时间）、**路线排行**（`routes`：按你的准点分位数排，不按平均排——平均更快的路线在 P80 下现出原形）、**迟到账**（`late`：按路线×星期聚出惯犯组合）；样本不足时拒绝判定（exit 3）而不是发明一个概率。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 每天走固定路线通勤、用「平均时长」估时间而迟过到的人；有固定打卡/站会时刻、想知道「最晚几点出门」的上班族；在「平均快 4 分钟但忽快忽慢」和「平均慢但稳」两条线之间纠结的路线选择者；面试日/赶飞机需要高置信出门时刻的人。 |
| **场景** | 早上出门前（「现在走，9:00 的会来得及吗？」）；前一晚定闹钟（「明天最晚几点出门才稳？」）；换季/搬家/换工作后重新攒路线画像；月底复盘（「这个月迟到三次，都发生在什么时候？」）；朋友问你「该坐地铁还是公交」而你知道答案不该只看平均。 |
| **问题** | ① **时长是分布，决策却按点**：导航给的「40 分钟」是中位/平均，用它出门等于把准点押在抛硬币上，而人对「我今天抽到了分布的哪一段」毫无体感；② **迟到是事件式记忆**：只记得昨天迟到，不记得「周五 + 晚出门」这个组合贡献了一半的迟到——惯犯组合从来不被点名；③ **晚出门的代价非线性**：晚 10 分钟出门，到达往往晚不止 10 分钟，早高峰的通胀系数没有人替你量；④ **路线选择看平均**：均值对抖动 blind，平均更快的路线可能方差大到在你真正在意的分位数上更慢；⑤ **小样本装懂**：新路线才走 3 次，任何「来得及」都是编的——但所有工具都愿意编。 |
| **价值与意义** | ① **画像**：`stats` 把 55 次地铁折成 P50 42m / P80 44m / P90 45m / 最差 49m，准点率 92.7% 旁边站着 21 次贴线到达——「准点靠 buffer 还靠贴线」一目了然；② **概率裁决**：`now` 用经验分布回答「你手里的 36 分钟是 P0 还是 P100」，8:24 出门 = P(on time) 0%，DEAD exit 5——裁决可进脚本，闹钟可以自动化；③ **反解出门线**：`leave` 迭代解到「答案的出发窗口生成它自己」，不收敛取最保守解——9:00 的会，最晚 **08:13** 出门（47m 预算，晚窗 P90）；窗口已关时说「现在走预计迟到 4 分钟」，**不给负时间**；④ **分位数排行**：公交均值 40.7m 比地铁 41.6m 快、P50 也快（36 vs 42），但 P80 是 50 vs 44——`routes` 默认按 P80 把皇冠给地铁，`--quantile 0.5` 时翻给公交，「平均最快 ≠ 准点最稳」第一次可复现；⑤ **晚出门通胀**：8:15 前出门中位 39m，之后中位 44m——**+12.8%**，晚出门比钟表更贵；⑥ **迟到惯犯**：8 次迟到里 4 次是「地铁 × 周五」，50% 集中度——迟到不是天气，是日程；⑦ **反事实**：`simulate --earlier 10` 算出准点 88.1%→97.0%、年迟到 16 次→4 次；⑧ **THIN 拒绝**：骑行才 4 次，`now` 直接 exit 3 拒绝发明概率；⑨ 零依赖 + 纯本地 + `--as-of`/`--at` 钉死逐字节可复现。 |

---

## 核心思想：份额即分位数，拒绝即诚实

通勤分析的全部错误，都来自把**一个数**当**一个分布**。工具的三条诚实原则：

| 概念 | 规则 | 回答的问题 |
|---|---|---|
| **份额即分位数** | P(on time) = 历史时长 ≤ 你手里时间的比例；报告里写「你手里的 36 分钟是 P0」——概率和分位数是同一本账的两个读法 | 「我的余量覆盖了历史的百分之几？」 |
| **窗口条件化** | 出发时刻 ≥ 08:15（可调）的通勤单独成池：晚出门的分布和早出门的不是同一个分布，8:20 的裁决读晚窗的 25 次，不读全池的 55 次 | 「这个点出门的人，历史上经历了什么？」 |
| **THIN 门** | 路线 trip 数 < 8 时 `now`/`leave` 直接 exit 3 拒绝判定；窗口池 < 5 时退回全路线池并在报告里声明出处 | 「这点样本有资格说话吗？」 |
| **保守解** | `leave` 迭代到「答案的出发窗口生成它自己」；窗口离散导致振荡时，取最早候选——它在任何窗口的解释下都安全，**宁早勿险** | 「这条出门线最坏也成立吗？」 |
| **贴线计数** | margin ∈ [0, 5 分钟] 记 close call：准点率和贴线率是两本账，92.7% 准点可以同时 38% 贴线——后者的名字叫「习惯性最晚出门」 | 「我的准点靠 buffer 还是靠运气？」 |

五条边界刻在实现里：**裁决不等宿命**——DEAD 只说统计上的中位结局（预计迟 8 分钟），不阻止你改签会议或发消息预警，报告原话是 "Reschedule, warn ahead, or accept it"；**同日原则**——账本只收当天往返的通勤，跨午夜班次直接拒绝（这不是夜班公交的账本）；**无目标不记准点**——`target` 留空的行（骑行兜风）只进时长分布、不进准点账，休闲不该被 KPI；**窗口只有两个**——手编账本在早晚高峰之外样本稀薄，五个时段就是五条传闻，两个窗口才是两个样本；**exit code 是接口**——SAFE 0 / RISKY 4 / DEAD 5 / THIN 3 / 用法错误 2，`now` 可以直接进 cron 和快捷指令。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash dd:ignore
python3 make_it.py now commutes.csv --route metro-line2 --at 08:24 --by 09:00
```

## 命令速查

```bash dd:ignore
python3 make_it.py stats commutes.csv --as-of 2026-08-29          # 画像：每条路线的分布与晚出门通胀
python3 make_it.py stats commutes.csv --route bus-73              # 单条路线
python3 make_it.py now commutes.csv --route metro-line2 \
        --at 08:24 --by 09:00                                     # 现在走来得及吗（SAFE/RISKY/DEAD）
python3 make_it.py now commutes.csv --route metro-line2 \
        --at 08:10 --by 09:00 --want 0.95                         # 提高置信门槛（面试日）
python3 make_it.py leave commutes.csv --route metro-line2 \
        --by 09:00 --at 08:05                                     # 最晚几点出门（窗口已关 exit 5）
python3 make_it.py routes commutes.csv                            # 按 P80 排行：皇冠给稳的
python3 make_it.py routes commutes.csv --quantile 0.5             # 按 P50 排：皇冠翻给别人
python3 make_it.py late commutes.csv                              # 迟到账：惯犯组合与集中度
python3 make_it.py simulate commutes.csv --earlier 10             # 早 10 分钟出门的年化收益
python3 make_it.py now commutes.csv --route metro-line2 \
        --at 08:24 --by 09:00 --format json                       # 机读（exit code 同步输出）
```

账本格式（`date,route,depart,arrive,target`，target 留空 = 不计时准点）：

```text dd:ignore
date,route,depart,arrive,target
2026-07-31,metro-line2,08:19,09:07,09:00
2026-07-15,bike,08:25,08:52,
```

## 一个真实样例

陈屿，31 岁后端工程师，周一/周三/周五进办公室，3 月到 8 月记了 71 次通勤：地铁 2 号线 55 次、公交 73 路 12 次（地铁故障的备选）、夏天骑行 4 次。8 月 29 日他用 `make-it` 复盘这半年（`python3 examples/build_examples.py` 可从零重建，日期与 `--as-of` 全部钉死，`--check` 逐字节校验）。[`examples/sample-stats.txt`](examples/sample-stats.txt) 的画像：

```text dd:ignore
  route          n   P50   P80   P90  worst  on-time  close
  bike            4   27m   31m   31m    31m      n/a      -  (thin: n=4 < 10)
  bus-73         12   36m   50m   56m    60m    66.7%      1
    ^ departures before vs from 08:15: median 36m (n=7) vs 38m (n=5) — leaving later costs +5.6%
  metro-line2    55   42m   44m   45m    49m    92.7%     21
    ^ departures before vs from 08:15: median 39m (n=30) vs 44m (n=25) — leaving later costs +12.8%
```

读法：地铁「平均 42 分钟」没错，但 8:15 之后出门的中位是 44 分钟——**晚出门通胀 +12.8%**；92.7% 的准点率旁边是 21 次贴线到达（38% 的通勤落在 5 分钟余量内），他的准点靠的不是 buffer，是贴线。早上 8:24 的裁决（[`examples/sample-now.txt`](examples/sample-now.txt)）：

```text dd:ignore
  now       : leave 08:24, arrive by 09:00 on metro-line2 — 36m of margin left
  evidence  : P(on time) = 0% over departures from 08:15 (n=25) — the margin you have
              is your P0 ride; worst day on record 49m
  verdict   : DEAD (exit 5) — the median day already misses by 8m.
              Reschedule, warn ahead, or accept the lateness.
```

读法：36 分钟的余量听着不少，但晚窗 25 次通勤**没有一次**短于 36 分钟——这不是「有点赶」，是统计上已经死了。前一晚的反解（[`examples/sample-leave.txt`](examples/sample-leave.txt)）：

```text dd:ignore
  target    : arrive by 09:00 on metro-line2 at P90 confidence
  solve     : leave at 08:13 — budget 47m (47m ride, departures from 08:15, n=25)
  verdict   : GO (exit 0) — it is 08:05 now, 8m of margin
```

路线排行（[`examples/sample-routes.txt`](examples/sample-routes.txt)）是本件的招牌故事：公交 73 路均值 40.7 分钟**比地铁 41.6 快**，P50 也快（36 vs 42）——但它 12 次里最差 60 分钟、P80 高达 50；按 P80 排行皇冠给地铁，`--quantile 0.5` 立刻翻给公交。**两条路线谁更好，取决于你问的是平均还是你的准点线**。迟到账（[`examples/sample-late.txt`](examples/sample-late.txt)）点名惯犯：8 次迟到里 4 次是「地铁 × 周五」（50% 集中度），周五迟到率 26.1% 是周三（0%）的——周三从不迟到。最后的反事实（[`examples/sample-simulate.txt`](examples/sample-simulate.txt)）：早 10 分钟出门，准点 88.1% → 97.0%，**年迟到 16 次 → 4 次、132 分钟 → 10 分钟**——一个闹钟的价钱。

## dogfood：样例账本即狗粮

```text dd:ignore
$ python3 examples/build_examples.py --check
examples in sync
```

通勤数据天然敏感（它就是你的住址与作息），本件不内置任何真人数据。dogfood 的形式与仓库传统一致：**六份样例报告由交付代码本身渲染**（`examples/build_examples.py` 走与 CLI 完全相同的代码路径），CI 用 `--check` 逐字节校验——报告里的每一个数字都能从钉死的账本与 `--as-of`/`--at` 复现，一份手写的样例都不存在。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_makeit.py`](tests/test_makeit.py)，75 个用例，`unittest` + 合成账本）：

```bash
python3 -m unittest discover -s make-it/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 账本解析：中英文表头别名、最小四列、额外列忽略、空行跳过、非法日期/时刻拒绝、到达≤出发拒绝、跨午夜拒绝、空路线拒绝、无数据行/缺列报错、target 留空 = 不计时、星期自动推导 | `ParserTests`（12 例） |
| 分位数：最近邻秩手算一致、向上取整、中位数先排序（回归：未排序迟到中位数错值）、单值、上界钳制 | `QuantileTests`（5 例） |
| now 裁决：SAFE（最差日也装得下，给 slack）/ RISKY（中位装得下最差日超支，给 shortfall）/ DEAD（中位已迟到，给预计迟到分钟）/ THIN exit 3 拒绝判定 / 截止已过单独口径 / 窗口池压过全池 / 池太薄回退全池并声明 / P==want 边界判 SAFE / P=0.5 边界判 RISKY / 不计时行计入时长证据 / 未知路线 exit 2 / 缺 `--at` exit 2 / want 越界 exit 2 | `NowTests`（13 例） |
| leave 反解：迭代解到窗口自洽（08:13 / 47m / 晚窗 n=25）、窗口已关 exit 5 给预计迟到与预计到达、THIN 拒绝、精化池太薄回退全路线分位数（保守解语义）、无 `--at` 照常解、目标越晚出门线越晚、置信越高出门线越早（0.8/0.9/0.95 三档 08:15/08:13/08:12） | `LeaveTests`（7 例） |
| routes 排行：P80 皇冠给地铁、P50 翻给公交（「平均最快 ≠ 准点最稳」可复现）、THIN 路线排序可领先但永不加冕、全员 THIN 不给皇冠、不计时路线 on-time 显示 n/a、quantile 越界 exit 2、报告点名均值陷阱 | `RoutesTests`（7 例） |
| late 迟到账：总数/贴线计数、按路线的率与中位迟到（排序后中位）、按星期的集中度、惯犯组合（地铁×周五 50%）、零迟到账本「nothing to confess」、贴线窗口 = 5 分钟边界 | `LateTests`（7 例） |
| simulate 反事实：早 10 分钟 88.1%→97.0%（8→2 次、65→5 分钟）、年化数字（16→4 次、132→10 分钟）、路线过滤、改钟后仍 ≥10% 迟到率给 advisory exit 4、不计时路线报错、非正 --earlier exit 2、未知路线 exit 2 | `SimulateTests`（7 例） |
| stats 画像：账本头（71 次·3 线·67 计时）、两行路线画像逐字符、两条晚出门通胀行、THIN 标注、`--route` 过滤、纯不计时路线 n/a、未知路线 exit 2 | `StatsTests`（7 例） |
| JSON：now 载荷（verdict/expected_late/p）、stats 载荷（P50/P80/inflation）、late 载荷（offender/share）、leave 载荷（leave_by 渲染为 HH:MM）、simulate 载荷（before/after） | `JsonTests`（5 例） |
| **dogfood：`--check` 逐字节同步、账本形状（71 行）、六份样例钉死 `--as-of`、CLI 子进程退出码端到端、同命令逐字节复现、零依赖审计（仅标准库 import）** | `DogfoodTests`（7 例） |

## 项目结构

```
make-it/
├── make_it.py             # 单文件零依赖 CLI（Python 3.8+ 标准库）
├── METHODOLOGY.md         # 方法论与 FAQ：分位数、窗口条件化、保守解的边界
├── README.md              # 本文件：问题定义 / 设计 / 验收标准
├── tests/test_makeit.py   # 75 个验收测试
└── examples/build_examples.py   # 从零重建账本与全部样例报告
    examples/commutes.csv        # 陈屿的半年通勤账本（71 行）
    examples/sample-stats.txt    # 六份样例报告（由 make_it.py 渲染）
    examples/sample-now.txt
    examples/sample-leave.txt
    examples/sample-routes.txt
    examples/sample-late.txt
    examples/sample-simulate.txt
```

## License

MIT © 2026
