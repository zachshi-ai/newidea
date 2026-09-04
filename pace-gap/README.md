# 赶考线 · Pace Gap

> 学习 App 记的全是**投入**——打卡天数、专注分钟、连击 streak；考试只按**产出**付钱——
> 大纲覆盖、章节闭。两本账之间从来没有人对账：87 天连击可以同时是 40% 的进度，
> 「来得及吗」永远是感觉，不是数字。

## 一句话

把备考抄成一本**章节闭账本**（syllabus.tsv 大纲 + study.tsv 流水），算出三个速率——
**required**（剩余章节 ÷ 剩余天数）、**proven**（近 28 天实测）、**peak**（历史最好 28 天窗）——
对「来得及吗」开庭判级；再把**时长投入**对上**分值权重**算每小时期望分，点名错配科目。

## 角色 / 场景 / 问题 / 价值

| | |
|---|---|
| **角色** | 在职/在校备考者：考研、考公、CPA、法考、教资、语言考试。每天下班学两小时，打卡连击 87 天，感觉良好 |
| **场景** | ① 报名时立了计划，9 月某个晚上想确认「按现在的节奏到底来得及吗」；② 督学营每周发一张进度表，停订之后就没人替你算这道算术——而督学营收你几千块干的也就是这道算术；③ 时间越学越偏：舒服的科目天天学，分值重的科目一直「明天开始」 |
| **问题** | 1. **投入幻觉**：学习 App 度量分钟和连击，考试度量大纲覆盖。87 天连击与 32.5% 覆盖是同一个人的同一本账——两个数字从没被并排放过<br>2. **速率盲区**：剩余章节 ÷ 剩余天数 = 所需日均速率，和你的实测日均速率之差是「来得及吗」的唯一算术答案，但没有任何 App 把这两个数放在一起；更没人告诉你**你证明过的峰值速率**够不够<br>3. **权重错配**：时间流向喜欢的科目（因为爽），分数按大纲权重支付。每小时期望分 = 科目权重 ÷ 累计时长——这个数没人算过，于是「在优势科目上刷题的每一分钟都很 productive」的错觉无从戳破<br>4. **失败的迟到宣告**：所需速率超过你历史峰值的那一刻，这次考试在日历上已经失败——该谈的是换目标、降预期或改方法，不是「再坚持一下」。这个宣告没人敢替你做，自己的直觉永远在拖 |
| **价值** | report 出覆盖/落后/时长三本总账；pace 对「来得及吗」开庭：三个速率并排、赶考倍数判级 ON-PACE/STRETCH/REDLINE/MATH-DEAD；allocation 把时长占比对分值权重占比，算每小时期望分并点名 TILTED 超投/STARVED 饿着/NEVER 空白；simulate 正推完成日或按日期反解所需速率；validate 做章节守恒体检。全部本地计算、不连任何接口；as-of 缺省=账本最大日期，同一本账任何机器任何一天逐字节一致 |

## 验收标准

| # | 验收项 | 判据 |
|---|---|---|
| 1 | 章节守恒 | 样例账本：closed 13 + opened-only 3 + untouched 24 = 40（残差 0）；分钟恒等残差 0.00 |
| 2 | 落后位置线 | start 2026-03-02 → exam 2026-12-19 共 292 天，elapsed 187 天（64.0%）：匀速应到 25.6 章，实闭 13，**落后 12.6 章**；`--start` 可调（钉 24.0） |
| 3 | 速率三线钉值 | proven = 3/28 = 0.1071 ch/day（8/12、8/20、8/30 三闭）；peak = 8/28 = 0.2857（最好窗 2026-03-02..03-29，8 章）；required = 27/105 = 0.2571 |
| 4 | 赶考倍数 | multiple = 2.40x → **REDLINE exit 4**；按峰值还剩章需 95 天、日历给 105 天——「每一周都必须是峰值周」 |
| 5 | 判级边界 | multiple 恰 1.0 → ON-PACE exit 0；恰 1.5 → STRETCH exit 0（1e-9 容差）；required **恰等于** peak → REDLINE 而非 MATH-DEAD；required > peak → MATH-DEAD exit 4；`--stretch-line` 可调（5.0 时同一本账 STRETCH exit 0） |
| 6 | 算术豁免薄账 | 考日已到/已过还有剩章 → MATH-DEAD exit 4，不受薄账门禁拦截（纯日历算术）；其余统计判级：覆盖 < `--min-days`(7) 或闭章 < 3 → exit 3 拒答 |
| 7 | 薄账分层 | 统计判级拒答时 report 的覆盖/落后/时长**照常出账** exit 0；6 个有行天拒、第 7 天起判 |
| 8 | 错配账钉值 | 时长 4,925 分钟：english 55.7% vs 权重 20% → **TILTED +35.7pp**；major 2.3% vs 30% → **STARVED −27.7pp** 且 **78.3 pts/hour 全场第一只拿 2.3% 的时长**；politics 权重 20% × 0 分钟 → **NEVER**；math +11.9pp 不亮灯 → exit 4 |
| 9 | 权重诚实条款 | syllabus 无 weight 列 → 只出时长/覆盖分布，**不发明权重** exit 0；部分科目给部分不给 → exit 2；同科目内混给 → exit 2；`--tilt-line` 可调（0.40 时 TILTED 熄灭，NEVER 仍点名——空白永远值得点名） |
| 10 | simulate 正推 | `--rate 0.3` → 27 章 ÷ 0.3 = 90 天 → 2026-12-04，**BEFORE 考日 15 天 exit 0**；`--rate 0.1` → 270 天 → 2027-06-02，AFTER 165 天 exit 4 |
| 11 | simulate 反解 | `--finish-by 2026-12-19` → 反解 required 0.2571，与 pace 判级**交叉一致**（REDLINE exit 4）；finish-by 早于 as-of → exit 2 |
| 12 | 账本体检 | 幽灵章（study 引用 syllabus 没有的章）/重复章节行/坏日期/负分钟/order<1/坏 status/权重口径混/缺文件 → exit 2；study 无数据行 → exit 2 |
| 13 | open 语义 | 仅 open 行的章**永不闭**（烂尾章诚实登记）；open 行不撤销已闭章；章时长含 open 行的分钟（投入是事实） |
| 14 | 零锚定可复现 | as-of 缺省 = study.tsv 最大日期；`--as-of` 显式钉回与缺省**逐字节一致**；报告只打印 basename；源码无任何系统时钟调用（无 date.today、无 datetime.now、无 time.time） |
| 15 | 无考日不判级 | pace 不给 `--exam-date` 只出速率三线账 exit 0——数字自己会说话，账本不发明考日 |

## 快速开始

```bash
# 覆盖/落后/时长总账（示例账本：考研人小北，40 章 4 科）
python3 pace-gap/pace_gap.py report pace-gap/examples/syllabus.tsv pace-gap/examples/study.tsv --exam-date 2026-12-19

# 速率法庭：来得及吗
python3 pace-gap/pace_gap.py pace pace-gap/examples/syllabus.tsv pace-gap/examples/study.tsv --exam-date 2026-12-19

# 错配账：时间都喂给了谁
python3 pace-gap/pace_gap.py allocation pace-gap/examples/syllabus.tsv pace-gap/examples/study.tsv

# 反事实：从今天起每天 0.3 章来得及吗 / 赶在考日要多少速率
python3 pace-gap/pace_gap.py simulate pace-gap/examples/syllabus.tsv pace-gap/examples/study.tsv --rate 0.3 --exam-date 2026-12-19
python3 pace-gap/pace_gap.py simulate pace-gap/examples/syllabus.tsv pace-gap/examples/study.tsv --finish-by 2026-12-19

# 账本体检
python3 pace-gap/pace_gap.py validate pace-gap/examples/syllabus.tsv pace-gap/examples/study.tsv
```

## 账本格式

两份手编 TSV（示例由 `pace-gap/examples/build_examples.py` 生成，`--check` 逐字节校验）。
首行为表头，`#` 开头行跳过。

`syllabus.tsv`——大纲（每章一行）：`subject / order / chapter / weight`
weight 是你选的度量（分值、页数、历年占比都行），账本只对账它的**分布**；整本不给
weight 就只出时长分布（不发明权重）。weight 要么全体科目都给、要么都不给。

`study.tsv`——学习流水（每天每章一行）：`date / subject / order / minutes / status`
status 缺省 `done`（该章此日**闭章**），`open` 表示翻过但没学完（烂尾章照实登记）。
一章的闭章日 = 最晚的 done 行日期；章时长 = 全部行分钟之和（含 open 行）。

## 判级与门禁

| 判级 | 条件 | exit |
|---|---|---|
| ON-PACE | multiple ≤ 1.0 | 0 |
| STRETCH | 1.0 < multiple ≤ `--stretch-line`(1.5) | 0 |
| REDLINE | multiple > 1.5 且 required ≤ peak：可追，但每一周都得是峰值周 | 4 |
| MATH-DEAD | required > peak：按你证明过的速度也追不平——日历问题，不是意志力问题 | 4 |
| DONE | 剩余 0 章 | 0 |
| （拒答） | 薄账：< 7 个有行天或闭章 < 3 | 3 |

exit 约定全仓一致：0 正常 / 2 账本坏 / 3 拒答或薄账 / 4 门禁红。
唯一不受薄账拦截的判级是「考日已到还有剩章」的 MATH-DEAD——它是日历算术，不是统计。

## 与近邻的边界

- **leave-debt 欠休**：同为「deadline 前的节奏账」，但那边管的是**假期债权**（授予/消耗/作废，额度守恒），本件管**学习产出**（章节闭，大纲守恒）——一个回答「额度来得及用完吗」，一个回答「进度来得及赶完吗」。
- **midnight-oil 深夜灯火**：量投入端（加班时长）。本件的立场恰恰是**投入不是产出**——分钟只作为错配账的分母进入，87 天连击在本件里没有半分信用。
- **year-like-a-day 度年如日**：初事密度是无截止日的速率（生活的新鲜感），本件的一切速率都被考日钉死（备考的倒计时）。
- **later-never 稍后永不**：注意力库存的消化半衰期，没有 deadline、没有必答清单；本件有硬考日、有既定大纲，问的是「按此速率能否覆盖」。
- **optimism-tax 乐观税**：估算 vs 实际的任务收据（估时膨胀率）；本件不问你估了多少，只问你跑出了多少、还差多少。
- **deficit-illusion 赤字幻觉**：精神同源（自报 vs 实测的对账），那边是能量守恒（摄入 vs 体重），本件是章节守恒（时长 vs 闭章）——是同一面镜子照两个房间。
- **filial-desk 孝心工单**：教**别人**的效果审计（复发链），本件是**自己学**的进度审计（速率线）。
- **border-budget 窗期 / expiry-cliff 到期悬崖**：日期窗口与凭证到期，无速率账；本件的核心量是**单位时间的产出**。

## 诚实条款

账本只算它有权算的东西：它不连任何学习 App、不猜你的考纲、不发明考日（不给
`--exam-date` 就只出速率账不判级）、不发明权重（syllabus 不给 weight 就只出时长
分布）、不发明你的峰值（闭章不足 3 个就拒绝谈速率）。MATH-DEAD 宣告的是「按你
证明过的速度追不平」这个日历事实，不是「你不行」——换目标、换方法、换考期，
永远是人的决定。判级线是先验不是真理：`--stretch-line`、`--min-days`、
`--tilt-line`、`--peak-window` 全部可调，参数永远赢。
