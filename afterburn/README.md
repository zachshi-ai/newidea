# 余燃 · Afterburn

> 那杯拿铁下午三点就喝完了，火到半夜还没熄。
> The cup ends at 3 PM. The fire doesn't — a zero-dependency CLI that keeps a pharmacokinetic ledger of your caffeine, and tells you what's still burning in your blood at bedtime.

---

## 一句话

咖啡因是全世界最广泛使用的精神活性物质，而人对它的心智模型是错的：直觉把它当成**饮用事件**——喝完就结束了；身体把它当成**持续存在的浓度**——按半衰期消除，健康成人约 5 小时减半。于是下午 3:30 的拿铁（126mg）到晚上 11:30 还剩 42mg，20:10 顺手的那罐可乐到就寝还剩 21mg——它们安静地叠在你的血液里，而躺在床上的你只会说「我今天也没喝多少啊」。`afterburn` 的立场：**咖啡因管理的最小可行单元不是「今天喝了几杯」，是「就寝时刻血液里还剩多少毫克」**。工具从一本可手编的摄入账本（TSV）里，用单室一级消除模型确定性算出：此刻谁还在烧（逐杯贡献分解）、就寝残留与红绿灯、今天最晚几点前还能喝这一杯（`cutoff` 反解，不是查表）、天天照这个节奏喝的稳态晨基线（你醒来时带着谁的余燃）、以及戒断推演（残留何时归零、头痛达峰落在周几）。「戒咖啡」是个错误的目标，**「掐时刻」才是对的**——半衰期给了一扇确定的窗，工具只负责告诉你窗几点关。

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 每天喝咖啡/茶/奶茶/可乐的上班族与开发者——尤其午后仍有摄入习惯的人；睡不好又「找不到原因」的人；尝试戒咖啡屡败、以为是意志力问题的人。 |
| **场景** | 睡前那一刻（「今晚又睡不着，我今天明明没喝多少」）；下午三点犹豫要不要拼单时（「这杯会不会影响睡觉」）；尝试早睡的一周（「为什么一到床就精神」）；决定戒断前（「戒的话会难受几天、什么时候最难熬」）。 |
| **问题** | **决策与代价在时间上被切断**：① 咖啡因的作用峰值在喝下后 30–60 分钟，直觉在峰值过去后就「结案」，但消除以半衰期进行——下午的摄入到就寝仍剩 25–45%，这段「余燃」没有任何体感对应物，它是不可感知的；② 多杯**叠加**：早上的美式、下午的拿铁、晚上的可乐各自衰减、彼此相加，直觉只数「今天 3 杯」从不做加法；③ 咖啡因是**延迟归因**的睡眠干扰因子——它不让你「睡不着」这么简单，它推迟睡眠时相、压浅深睡眠，而第二天早上的你把疲惫归因于「昨晚想事情」，于是再喝一杯，进入闭环；④ 现有工具止步于「记录摄入量」，没有回答唯一重要的问题：**几点之后不能喝**。 |
| **价值与意义** | 1) **就寝残留**是本件的中心量：`残留 = Σ 各杯剂量 × 2^(−经过时长/半衰期)`，逐杯贡献分解让「谁在烧」一目了然；② **cutoff 反解**：给定就寝时间与阈值，闭式解出「最晚几点前喝完这杯」——额度耗尽时诚实报告「窗口已关」，而不是给一个负数；③ **个体化**：半衰期（快代谢 3h / 均值 5h / 慢代谢 8h）与阈值全部可调——同一杯拿铁，快代谢者绿灯、慢代谢者红灯，基因不是道德问题，是参数；④ **稳态视角**：天天固定节奏的人，醒来时带着昨天的余燃，「没醒透」由此有了解释；⑤ **戒断时间表**：把「戒咖啡难」从意志力问题翻译成时间表问题——头痛达峰落在哪一天，安排在周末它就只是「有点困」；⑥ 零依赖 + 纯本地 + `--now` 钉死逐字节可复现。 |

## 核心思想：把「饮用事件」换成「消除账本」

| 概念 | 规则 | 回答的问题 |
|---|---|---|
| **消除 elimination** | 单室一级消除：每杯剂量 D 在 t 小时后剩 `D·2^(−t/t½)`；缺省半衰期 5h，`--half-life` 可调 | 「那杯现在还剩多少？」 |
| **叠加 superposition** | 多杯残留线性相加，**跨夜连续**（昨天的咖啡计入今晨底座） | 「我血里现在一共多少？」 |
| **就寝残留 bedtime residual** | 就寝时刻的总残留；> 阈值（缺省 50mg，约半杯滴滤）红灯 exit 4 | 「今晚的睡眠被谁动了？」 |
| **cutoff 最晚时刻** | `t* = 就寝 + ln(剩余额度/剂量)/k` 的闭式反解；回代恰好落在线上 | 「这杯几点前喝完没事？」 |
| **稳态 steady state** | 每日固定节奏 → 几何级数收敛出晨起基线 | 「天天这么喝的我，醒来时是什么状态？」 |
| **戒断窗 wean window** | 残留归零时刻是计算；症状起病 12–24h、头痛达峰 20–51h、消退 2–9 天是文献标注（Juliano & Griffiths 2004） | 「停喝会难受几天？最难熬落在周几？」 |

三条诚实条款刻在实现里：**模型是估计，不是血液检测**——单室一级消除是咖啡因药代动力学的标准一级近似，但个体半衰期横跨 2–10h，饮品毫克数波动巨大，本件给的是「有账可查的估计」，不是临床结论；**缺省宁可保守**——饮品表取粗略中位、行级毫克永远可以覆盖，「宁可贵在覆盖，不贵在精确」；**戒断窗是标注不是计算**——症状时间来自流行病学综述，工具只把它排到你的日历上，到达那几个小时会发生什么因人而异。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

## 命令速查

```bash dd:ignore
python3 afterburn.py now ledger.tsv --now "2026-09-04 16:00"     # 此刻血里还剩多少
python3 afterburn.py bedtime ledger.tsv --at 23:30               # 就寝判灯（红 → exit 4）
python3 afterburn.py cutoff ledger.tsv --at 23:30 --drink latte  # 今天最晚几点喝完这杯
python3 afterburn.py day ledger.tsv --date 2026-09-03            # 当天残留曲线
python3 afterburn.py week ledger.tsv --end 2026-09-04            # 近 7 晚红绿灯
python3 afterburn.py steady 08:40 drip 15:30 latte               # 稳态：醒来的余燃
python3 afterburn.py wean ledger.tsv                             # 戒断推演
python3 afterburn.py drinks                                      # 饮品缺省表
python3 afterburn.py validate ledger.tsv                         # 账本体检
python3 afterburn.py bedtime ledger.tsv --at 23:30 --half-life 8 # 慢代谢者视角
```

账本是一份可手编的 TSV（Tab 分隔），第 4 列毫克可覆盖缺省表：

```
2026-09-04  08:40  drip
2026-09-04  15:30  milk-tea  120
```

## 一个真实样例

开发者小张，就寝 23:30，一周账本见 [examples/week.tsv](examples/week.tsv)（15 条记录）。周五下午 16:00 他顺手看了一眼：

```
此刻 2026-09-04 16:00
血液残留  154.4 mg   ████████████████████████

谁在烧：
  2026-09-04 15:30  milk-tea         120 mg → 还剩 112.0 mg（93%）
  2026-09-04 08:40  drip              95 mg → 还剩  34.4 mg（36%）
  2026-09-03 15:30  latte            126 mg → 还剩   4.2 mg（3%）
```

（完整输出：[examples/sample-now.txt](examples/sample-now.txt)）

当晚 23:30 的就寝判定：

```
就寝 2026-09-04 23:30（23:30）
就寝残留  54.6 mg   ██████████████··········
判定      RED   越线 9%（阈值 50mg）

谁在烧：
  2026-09-04 15:30  milk-tea          还剩  39.6 mg
  2026-09-04 08:40  drip              还剩  12.1 mg
```

（完整输出：[examples/sample-bedtime-red.txt](examples/sample-bedtime-red.txt)，退出码 4）

一周全景（[examples/sample-week.txt](examples/sample-week.txt)）说出了模式：

```
  日期         摄入  最后一杯       就寝残留   判定
  2026-08-30    95 mg  09:00        13.3 mg  GREEN
  2026-08-31   221 mg  15:30        54.2 mg  RED
  2026-09-01   255 mg  20:10        77.1 mg  RED
  2026-09-02    95 mg  08:40        14.9 mg  GREEN
  2026-09-03   286 mg  20:10        79.6 mg  RED
  2026-09-04   215 mg  15:30        54.6 mg  RED

7 晚里 4 晚红灯。红灯是常态还是偶然，答案就在上面。
```

规律不需要统计学位：**只喝早杯的日子全绿，15:30 之后还有摄入的日子全红**。而 `cutoff` 把改进翻译成时刻表（[examples/sample-cutoff.txt](examples/sample-cutoff.txt)）：

```
就寝 2026-09-04 23:30   目标饮品 latte            126 mg
不喝这杯，就寝底座也已有 15.0 mg → 剩余额度 35.0 mg

最晚 2026-09-04 14:15 喝完这一杯。
```

下午的拿铁不是不能喝，是 **14:15 之前**喝。同一个周四 14:00 的窗口、换慢代谢者视角（`--half-life 8`），答案变成「额度只剩 7.9mg，窗口昨天 15:32 就关了」（[examples/sample-cutoff-halflife.txt](examples/sample-cutoff-halflife.txt)）——同一杯咖啡，基因决定了它是不是你的问题。

## 与哪些点子不混淆

- 与 **rebrew**（冲煮实验设计）：rebrew 管杯子里的事——参数怎么影响出品；afterburn 管杯子进身体后的事——什么时候喝不偷觉。一个是厨房物理，一个是血液化学。
- 与 **social-jetlag**（社交时差）：社交时差管「你的睡眠落在钟面哪里」的时相账；afterburn 管「血液里还剩多少毫克」的浓度账。一个治钟的病，一个治火的病，互补而不重叠。
- 与 **midnight-oil**（深夜工作）：深夜灯火测的是「谁在深夜燃烧自己」的工作负荷；余燃测的是「白天那杯咖啡如何在深夜继续烧你」。

## 验收标准（已全部转成自动化测试）

| # | 标准 | 测试 |
|---|---|---|
| A1 | 单室一级消除：95mg 半衰期 5h，5h 后恰为 47.5mg | `test_a1_half_life_math` |
| A2 | 线性叠加：多杯残留 = 各自残留之和 | `test_a2_superposition*` |
| A3 | 跨夜连续：昨天的摄入计入今晨底座 | `test_a3_overnight_carryover` |
| A4 | 就寝判灯：越线 → RED + exit 4；未越 → GREEN + exit 0 | `test_a4_bedtime_*` |
| A5 | cutoff 反解：解回代后恰好落在线上；额度尽返回 None 而非负时间 | `test_a5_*` |
| A6 | 稳态闭式解 == 逐日暴力模拟 40 天（<0.1% 误差） | `test_a6_closed_form_matches_simulation` |
| A7 | 坏行带行号 exit 2；未知饮品无毫克 exit 2；空账本 exit 3 | `test_a7_*` |
| A8 | 行级毫克覆盖优先于饮品表缺省 | `test_a8_row_level_override_beats_table` |
| A9 | 戒断：残留单调降至安静线、时刻可定位 | `test_a9_quiet_crossing_monotone` |
| A10 | 00:00–05:59 的就寝时间视为次日凌晨 | `test_a10_after_midnight_bedtime_is_next_day` |

```bash dd:ignore
python3 -m unittest discover -s afterburn/tests   # 56 tests
python3 afterburn/examples/build_examples.py      # 重建全部样例（含 exit 4 的红灯样例）
```

## 仓库结构

```text dd:ignore
afterburn/
├── README.md            # 本文件：问题定义 / 设计 / 验收标准
├── METHODOLOGY.md       # 方法论：药代动力学、证据边界、FAQ
├── afterburn.py         # 零依赖 CLI（Python 3.8+ 标准库）
├── tests/
│   └── test_afterburn.py  # 56 个验收测试
└── examples/
    ├── week.tsv               # 示例账本：开发者小张的一周
    ├── build_examples.py      # 样例重建器（钉死 --now，逐字节可复现）
    └── sample-*.txt           # 11 份子命令真实输出
```

## License

MIT © 2026
