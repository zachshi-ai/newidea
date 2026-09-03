# 社交时差 · Social Jetlag

> 周一的困，多半不是没睡够——是你每周给自己倒了两次时差，却从没离开过床。
> A zero-dependency CLI that reads a hand-kept sleep log (date / bedtime / wake / work-or-free) and splits "tired" into the two accounts it conflates: **sleep debt** (how long) and **social jetlag** (where on the clock) — MSW, MSF, the 2h red line, the annualized debt, the weekend repay rate, and the counterfactuals that tell you which account is actually bleeding.

---

## 一句话

你的语言里只有一个「困」，但睡眠健康里有**两个独立的变量**：睡了多久（债），和睡在钟面哪里（相）。周一早上的难受，多半被记在第一个账上——「周末没睡好，缺觉了」；于是你开出的药方是「这周早点上床」。可如果问题在第二个账上——你的生物钟在自由日夜里被推后了两小时，周一被闹钟硬拽回来——那么「早点上床」只会在黑暗里干瞪眼，尝试失败一两次，人就永远放弃。`social-jetlag` 的立场：**困是症状，账本才是诊断**。它从一本可手编的睡眠日志（一行一夜：日期、入睡、醒来、这天有没有被闹钟强拉）确定性算出：你的社交钟（MSW）和生物钟（MSF）各指几点、两者错位多大（社交时差 SJL，|SJL| ≥ 2h 是流行病学红线）、把自由日「还债式超睡」扣掉后还剩多少错位（MSFsc）、工作日每晚欠多少睡眠、年化是多少、周末超睡到底够不够还账——以及三个反事实：**周末不再补觉会怎样（flat）**、**自由日整体平移会怎样（anchor）**、**要把时差压到目标需要移动多久（target）**。读完报告你就知道该修哪本账：是债，就还债；是钟，调钟——别再用早睡去治时差。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 长期靠闹钟起床、周末狂补觉的上班族与学生（「为什么周一永远像倒了时差」）；尝试过「早睡早起」并失败过的人（「躺下也睡不着，是不是我废了」）；倒班与跨时区工作者（「我的错位有多严重、往哪边偏」）；对自己睡眠数据感兴趣、但不想上传睡眠给任何 App 的量化自我玩家。 |
| **场景** | 周一早晨的例行自责（先看 SJL 再决定怪谁）；「早睡计划」立项前（先用 target 算清要移动的是入睡端还是起床端）；睡眠 App 报告看不懂时（两个数字替代一条模糊曲线）；与伴侣/室友协商周末作息时（拿账本谈判，不拿感觉吵架）。 |
| **问题** | **「困」把两本账记成了一笔**：① 睡眠不足（时长）与睡眠时相错位（钟面）是两个独立变量，日常语言只有一个词，于是钟的问题被误诊成债的问题，药方（早睡）治不了病（相位后移），失败一次放弃一次；② 补觉看起来是在还债，实际同时在**加深时差**——自由日起得越晚，生物钟越后移，周一的落差越大，没有人算过这笔交换是否划算；③ 睡眠 App 给你一条曲线，不给你一句判决：错位多大？超没超线？该修哪端？全是感觉。 |
| **价值与意义** | 1) **两个数字替代一种感觉**：SJL（+2h50m !! HIGH）与睡眠债（1h20m/工作日 · 年化 346h40m），症状从此有了账本。<br>2) **中点是对的度量**：入睡推迟 1 小时、起床推迟 1 小时，各推中点半小时——「睡到几点」会说错话，中点不会。<br>3) **还债率拆穿补觉的错觉**：周末超睡 ÷ 工作日亏欠 = 还债率。36% 意味着你为还不起的贷款付着时差的利息；120% 意味着债还清了，票价是每周两次穿越自己的时区。<br>4) **反事实分离两本账**：flat（周末不再补觉）消掉多少时差、剩多少——剩下的就是纯相位，说明「别睡懒觉」治不了你；target（压到 1h 内）告诉你自由日要整体提前多久。<br>5) **零依赖 + 纯本地**：Python 3.8 标准库，数据是可手编的 TSV，不上传、不登录、不依赖可穿戴。 |

## 与仓库近邻的边界

- **vs 时区税 timezone-tax**：都借「时差」的修辞，但 timezone-tax 管的是**会议排班在成员之间的公平**（数据 = 会议日历，主体 = 团队），本件管的是**你自己的生物钟与社交钟的错位**（数据 = 睡眠日志，主体 = 个人）。一个向外议价，一个向内诊断。
- **vs 深夜灯火 midnight-oil**：midnight-oil 用 git 时间戳看**工作负荷**（过劳预警），本件用睡眠日志看**睡眠时相**（困倦归因）。过劳的人未必时差，时差的人未必过劳；一个回答「团队是否在燃烧」，一个回答「你的困该怪债还是怪钟」。
- **vs 加量红线 redline**：redline 是训练侧的负荷账（身体的外部压力），本件是恢复侧的时相账（睡眠的内部时钟）。训练量再科学，睡眠时相错位照样让你在周一「无故」崩掉。

---

## 核心思想：两本账，六个数

从每夜一行（`date / sleep / wake / kind`，kind = 这天有没有被闹钟强拉）确定性导出：

| 度量 | 定义 | 回答的问题 |
|---|---|---|
| **MSW** | 工作日（alarm day）睡眠中点的中位数 | 我的社交钟指几点？ |
| **MSF** | 自由日（free day）睡眠中点的中位数 | 我的生物钟指几点？ |
| **SJL** | MSF − MSW；\|SJL\| ≥ 2h 进红线 | 我每周给自己倒多久的时差？ |
| **MSFsc** | 扣掉自由日「还债式超睡」后的校正中点 | 把还债的成分剔掉，钟还偏多少？ |
| **睡眠债** | 每工作日欠的时长 → 周 → 年化 | 这笔贷款滚到多大了？ |
| **还债率** | 自由日总超睡 ÷ 工作日总亏欠 | 周末到底是在还债，还是在白付利息？ |

三条判定线：**ALIGNED**（|SJL| < 1h，钟和社交时间基本一致）/ **DRIFTING**（1–2h，自由日活在另一个时区）/ **HIGH**（≥ 2h，流行病学红线）。2 小时这条线不是拍脑袋：社会时差研究里它反复出现在与主观困倦、情绪低落、体重等指标的相关性分析中（谱系见 METHODOLOGY §4）——但它是**人群统计的相关线，不是临床诊断线**，本工具只记账，不开药。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash dd:ignore
python3 social_jetlag.py report sleep.tsv      # 我的困，该怪债还是怪钟？
```

日志格式（TSV，`#` 注释，首行表头可选）：

```text dd:ignore
date        sleep   wake    kind    alarm
2026-08-17  00:20   07:10   work    yes
2026-08-22  02:30   10:40   free    no
```

`kind` 由**当天有没有强制起床**决定，不是星期几——调休加班的周六记 `work`，放假的周三记 `free`。

## 命令速查

```bash dd:ignore
python3 social_jetlag.py report sleep.tsv               # 两本账的核心报告
python3 social_jetlag.py report sleep.tsv --format json # 机读
python3 social_jetlag.py report sleep.tsv --mean        # 均值口径（MCTQ 问卷惯例；默认中位数抗离群夜）
python3 social_jetlag.py report sleep.tsv --fail-over 120  # 门禁：|SJL| 超过 120 分钟则 exit 4
python3 social_jetlag.py simulate sleep.tsv flat        # 反事实：周末不再补觉
python3 social_jetlag.py simulate sleep.tsv anchor 60   # 自由日整体提前 60 分钟（负数 = 推后）
python3 social_jetlag.py simulate sleep.tsv target 60   # 要把 |SJL| 压到 60 分钟，需移动多久
python3 social_jetlag.py validate sleep.tsv             # 日志体检：行数、单侧、小样本警告
```

## 两个真实样例

同一个三周窗口（2026-08-17 .. 09-06），两位居民，两种诊断（`python3 examples/build_examples.py` 可从零重建，逐字节可复现）。**mia** 是猫头鹰：闹钟日 07:10 结束，自由日漂到 10:40——[`examples/sample-report-mia.txt`](examples/sample-report-mia.txt) 的判决：

```text dd:ignore
  nights logged          : 21  (15 work / 6 free · 2026-08-17 .. 2026-09-06)
  sleep duration         : work 6h50m · free 8h10m
  sleep midpoint         : work 03:45 (MSW) · free 06:35 (MSF)
  MSFsc (debt-corrected) : 06:06
  social jetlag          : +2h50m   !! HIGH   (red line = 2h)
  debt-corrected SJL     : +2h21m   !! HIGH
  sleep debt             : 1h20m per work night · 6h40m per week · 346h40m per year
  weekend repay rate     : 32%  (430 repaid of 1350 owed)

Your free nights end 2h50m later on the clock than your work
nights. Every week you fly twice: forward every free day,
back with every alarm day — the commute your bed makes.
The free-day oversleep repays only 32% of the work debt —
you are paying jetlag for a loan you are not repaying.
```

读法：mia 自以为「周末补了两小时，还了一部分债」。账本说：你还了 32%——剩下 68% 是白欠的，而你为这点还债付的票价是每周两次 2h50m 的时差跳跃。更扎心的是 MSFsc：把还债的成分剔掉，钟还偏 **2h21m**——你的问题大头是相位，不是缺觉，「早点上床」这剂药大概率治不了你。反事实把话说死（[`examples/sample-simulate-flat.txt`](examples/sample-simulate-flat.txt)）：周末不再补觉只消掉 40 分钟时差、剩 **2h10m**——那部分就是纯相位。要压到 1 小时内，自由日两端（不只闹钟）得整体提前 **1h50m**（[`examples/sample-simulate-target.txt`](examples/sample-simulate-target.txt)）。

对照组 **lee** 是云雀（[`examples/sample-report-lark.txt`](examples/sample-report-lark.txt)）：SJL 只有 +0h15m，ALIGNED——但别急着羡慕，他的睡眠债年化 **43h20m**。两本账独立记账的意义就在这：**时差小不等于债小，债小不等于时差小**，只有一个数字的睡眠报告都是 half-truth。

## dogfood：数字从哪来，就由谁验证

睡眠工具没法像 git 工具那样审计自己的出生仓库，所以本件的 dogfood 是**同源性**：本 README 与样例里的每一个数字（03:45、06:35、+2h50m、346h40m、32%、1h50m……）都由同一个 CLI 生成，`python3 examples/build_examples.py --check` 保证提交的样例日志与四份样例报告逐字节可复现，验收套件里的 `DogfoodTests` / `ExamplesSyncTests` 每次跑测试都重新验证这条链。工具不说自己治失眠——它只保证账本上的每个数字都能重算。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_socialjetlag.py`](tests/test_socialjetlag.py)，60 个用例，`unittest`，夹具数字全部手工验算）：

```bash
python3 -m unittest discover -s social-jetlag/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 钟面算术：严格 HH:MM 解析（拒绝 7:10/24:00/07:60）、跨午夜时长与中点、HH:MM 往返格式化（含绕回与负数） | `ClockArithmeticTests`（4 例）、`NightTests`（3 例） |
| 日志解析：注释/表头/空行、可选第 5 列、乱序日期容忍、六类坏行报错且带行号、空日志与缺文件 | `LogParseTests`（6 例） |
| 统计口径：中位数奇偶、抗离群夜（11×410 中混 3×350+440 中位数不动均值动）、`--mean` 口径 | `MedianTests`（2 例）+ 统计用例 |
| 核心指标：mia 夹具 MSW 03:45 / MSF 06:35 / SJL +2h50m 手工钉死；SJL ≡ MSF−MSW 恒等式 | `MetricsTests`（11 例） |
| MSFsc 校正：方向朝 MSW 回拉、数值钉死 06:06、无超睡时严格不校正 | `MetricsTests` |
| 睡眠债：日/周/年化三级、按日志实际 work:free 比例年化（不假设 5:2）、还债率三态（<100%、=100%、无债 n/a） | `MetricsTests` |
| 负 SJL（云雀/倒班方向）与三档判定边界（59.9/60/119.9/120、绝对值对称） | `MetricsTests`、`GradeTests`（3 例） |
| 小样本警告：work<3、free<3、跨度<14 天各自触发；满 21 夜零警告 | `WarningsTests`（2 例） |
| simulate：flat 中点手工钉死 05:55（相位剩余 +2h10m）、anchor 刚性平移线性、target 反解恰落在目标、target 已达标零移动、负值 anchor | `SimulationTests`（5 例） |
| 报告与叙事：九行关键数字快照、四种判决分支（deadbeat / fare / aligned / lark）逐字钉死、JSON 结构与数值 | `ReportTextTests`（4 例）、`JsonTests`（1 例） |
| CLI 契约：text/json/--mean、门禁 exit 4 与放行、三个 simulate 场景、坏场景/缺值 exit 2、单侧/缺文件/坏行 exit 3、无子命令 exit 2、validate | `CliTests`（14 例） |
| 样例同步：[`examples/build_examples.py`](examples/build_examples.py) `--check` 逐字节 | `ExamplesSyncTests`（1 例） |
| dogfood：提交的 TSV 重跑 CLI 必须逐字节复现提交的四份样例报告；JSON 数字满足恒等式与界 | `DogfoodTests`（4 例） |

## 项目结构

```
social-jetlag/
├── social_jetlag.py
├── tests/test_socialjetlag.py
├── examples/build_examples.py
├── examples/wooly-week.tsv          # mia：猫头鹰，+2h50m HIGH
├── examples/lark-week.tsv           # lee：云雀，+0h15m ALIGNED
├── examples/sample-report-mia.txt
├── examples/sample-report-lark.txt
├── examples/sample-simulate-flat.txt
├── examples/sample-simulate-target.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
