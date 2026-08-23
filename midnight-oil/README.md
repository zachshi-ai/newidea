# 深夜灯火 · Midnight Oil

> 过劳不会出现在周报里，但它写在每一个凌晨 1 点的提交时间戳上。
> A zero-dependency CLI that reads the author-local clock inside every commit: who is shipping at 1 a.m., working every weekend, and going weeks without a day off — measured from git, not from surveys.

---

## 一句话

每个关心团队健康的负责人都依赖两样不可靠的东西：问卷（有表演性）和 1:1（都说「还行」）。而 git 历史里躺着几千个**精确到秒的作者本地钟点**——凌晨的、周末的、连轴转的——从没人去看，因为手工重建「工作时间分布」不现实。`midnight-oil` 把它变成一条命令：深夜比例、周末比例、最长无休 streak、周末深夜同现，以及杀手锏**趋势对比**（最近 13 周 vs 更早）——因为绝对值不定罪，**一个白天型选手搬进凌晨并持续数周，才是燃烧开始的信号**。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 工程负责人 / TL（季度团队健康回顾、冲刺后复盘）；以及想客观审视自己工作节奏的开发者（年终自省、和经理谈工作量之前先看数据）。 |
| **场景** | 「这个 sprint 大家是不是撑得太狠了」的复盘会；有人提离职后的「为什么没早发现」；个人想确认「我最近是不是睡得太晚」。 |
| **问题** | **过劳是隐性的，且自报数据系统性失真**：问卷有社会期许偏差，1:1 里没人会说「我连续三周没有休息日」。等到信号明确（离职、病假、事故率），损失已经发生。而证据一直在 git 里——`%aI` 的钟点字段就是作者当时墙上钟的钟点——只是从来没有人把它读出来。 |
| **价值与意义** | 1) **观察数据而非自报数据**：时间戳不会表演。<br>2) **时区正确**：按每个提交自带的作者本地钟点计算，分布式团队里北京凌晨 1 点和洛杉矶傍晚 5 点不会被混为一谈。<br>3) **夜猫子辩护有解**：稳定夜型是作息，不是事故——`trend` 对比自身基线，只有**模式改变**才亮黄灯。<br>4) **防误报优先**：比例类信号要求 ≥10 个提交，样本不足宁可沉默。<br>5) **伦理内建设计**：纯本地、零上传、`--anonymize` 一键脱名；信号用于开启对话，不是绩效证据。<br>6) **`audit` 健康预算**：团队自我约定的红线（非管理层监控）。 |

---

## 核心思想：作者挂钟 → 多信号交叉 → 趋势定罪

git 的 author date（`2026-08-24T01:30:00+08:00`）里的钟点**就是作者提交那一刻所在地钟面上的时间**——无需任何时区换算，读出来的就是「他几点在写代码」。本工具只基于这一事实重建信号：

| 概念 | 定义 | 直觉 |
|---|---|---|
| **late-night** | 作者本地 22:00–04:59 | 大家都睡了，他还在 ship |
| **weekend** | 作者本地日期为周六/日 | 日历上的休息日在提交 |
| **streak** | 最长连续提交天数 | 连续 17 天没有一天歇过 |
| **weekend-late day** | 同一天既是周末又出现深夜提交 | 强信号：休息日燃到凌晨 |
| **level** | ok（0 flag）/ watch（1）/ alert（≥2） | 信号越多越值得谈话 |
| **trend** | 最近 N 天（默认 91）vs 更早的自身对比 | **绝对值不定罪，模式改变才是信号** |

四位 flags（比例类要求 ≥10 个提交才参与判定）：

| flag | 阈值 | 含义 |
|---|---|---|
| `LATE_NIGHT` | 深夜占比 ≥ 15% | 每周都有一两个深夜在常态化 |
| `WEEKENDS` | 周末占比 ≥ 20% | 每周一天休息日出勤 |
| `NO_BREAK` | 最长 streak ≥ 14 天 | 两周以上无休息日 |
| `WEEKEND_LATE` | 周末深夜日 ≥ 3 个 | 休息日燃到凌晨，且不止一次 |

## 安装（零依赖）

只需 Python 3.8+ 和 `git`，无需 `pip install` 任何东西。

## 命令速查

```bash
python3 midnight_oil.py scan                            # 仓库总览: 深夜/周末/streak
python3 midnight_oil.py authors                         # 每人画像: 24h 直方图 + flags
python3 midnight_oil.py trend                           # 最近 91 天 vs 更早(自身对比)
python3 midnight_oil.py trend --author "Bob" --window 60
python3 midnight_oil.py scan --exclude-author "bot"     # 排除 CI/依赖机器人
python3 midnight_oil.py authors --anonymize             # 分享前脱名
python3 midnight_oil.py scan --since 2026-06-01 --author alice
python3 midnight_oil.py audit                           # 健康门禁: 超预算 exit 1
python3 midnight_oil.py audit --max-late 20 --max-weekend 10 --max-streak 21
```

公共参数（`--author` / `--exclude-author` / `--since` / `--until` / `--as-of` / `--anonymize` / `--format`）跟在子命令之后；`--as-of` 钉死「今天」，报告可复现。

## 一个真实样例

见 [`examples/`](examples/)。三人迷你仓库（`python3 examples/build_examples.py` 可从零重建，日期、钟点、时区全部钉死）——同一个月里三种完全不同的燃烧方式：

```text dd:ignore
Bob Wu  [ALERT]
    commits 97     active days 86    span 2026-03-02 -> 2026-08-21
    late-night  50.5%   weekend  23.7%   streak 17d   weekend-late 8d
    flags: LATE_NIGHT, WEEKENDS, NO_BREAK, WEEKEND_LATE
```

Bob 的 [`examples/sample-trend.txt`](examples/sample-trend.txt) 是本工具的核心论点：baseline 段 0% 深夜 / 0% 周末，最近 13 周 **80.3% 深夜 / 37.7% 周末**——双 WORSENING。而 Carol（`-0500` 时区，全程凌晨提交）深夜比例 100% 却只有 `LATE_NIGHT` 一个 flag，且 trend 判定 **STABLE**：她一直是夜猫子，这是作息，不是事故。**同一个工具，两种深夜，两种读法。** 完整报告见 [`examples/sample-authors.txt`](examples/sample-authors.txt)。

## dogfood：工具出生的第一天就照了镜子

对本仓库（newidea）自身：

```text dd:ignore
  commits         : 5
  late-night 22-05: 100.0%  ##########
  weekend         :  40.0%  ####
  flags: none        <-- 样本 < 10, 工具拒绝下结论
  late-night : INSUFFICIENT (trend, baseline 为空)
```

诚实的双重曝光：本仓库 5 个点子全部诞生于凌晨 1 点、2 点和晚上 10 点（40% 落在周末）——工具说的第一句真话就是「这个实验室本身是深夜灯火照亮建起来的」；同时它拒绝给作者任何 flag，因为 5 个提交撑不起统计结论。**看见信号，但不诬陷小样本**——这正是它被设计出来的样子。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_midnightoil.py`](tests/test_midnightoil.py)，59 个用例，`unittest` + 真实临时 git 仓库，日期与偏移全部钉死、`--as-of` 钉死「今天」）：

```bash
python3 -m unittest discover -s midnight-oil/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 解析：`%aI` 严格 ISO、空格式与无偏移兜底、垃圾拒绝、**钟点字段不做任何时区换算**、`\x1f` 字段分隔（作者名带竖线不炸）、坏行跳过 | `TimeparseTests`（7 例） |
| 信号：深夜窗口边界（21 点否/22 点是/5 点否）、已知日期的周末判定、Commit 派生属性 | `SignalTests`（4 例） |
| streak：空/单日/连续/断档重置/同日去重/乱序输入 | `StreakTests`（6 例） |
| 画像：比例与 24 桶直方图、首末日、四个 flag 各自触发、**样本 <10 时比例类 flag 强制沉默**、ok/watch/alert 三级、同名不同邮箱聚合且按量排序 | `ProfileTests`（9 例） |
| 趋势：切窗边界日归 baseline、WORSENING/IMPROVING/STABLE/INSUFFICIENT、**weekly_active_days 按各段自身跨度折算** | `TrendTests`（6 例） |
| 匿名化：稳定、可区分、真实姓名不外泄 | `AnonymizeTests`（2 例） |
| git 集成：**同一 UTC 时刻两个挂钟**（北京 01:30 深夜 / 洛杉矶 17:30 白天各判各的）、**周末判定走作者本地日期**（UTC 周日 20:00 = 北京周一凌晨 → 非周末）、author date 优先于 committer date、作者/排除（姓名或邮箱匹配 bot）、since/until 含边界、空仓库、真实仓库建 Report | `GitIntegrationTests`（8 例） |
| 渲染：空仓库、数字与柱条、flags/直方图/levels、trend 的 night-owl 提示行 | `RenderTests`（4 例） |
| CLI：无子命令与非 git 目录 exit 2、scan/authors 的 text+json schema、`--anonymize`、`--window`、audit 门禁通过/超线 exit 1（含 per-author streak）、**audit 比例检查同 ≥10 样本纪律**、选项后置于子命令 | `CliTests`（11 例） |
| 样例同步：`--check` 逐字节校验三份提交样例 | `ExamplesSyncTests`（1 例） |
| **dogfood：对本仓库自身出报告，Σ(每人 commits) == 总 commits 恒等式成立** | `DogfoodTests`（1 例） |

## 项目结构

```
midnight-oil/
├── midnight_oil.py
├── tests/test_midnightoil.py
├── examples/build_examples.py      # 三人 demo 仓库, 从零可复现重建
├── examples/sample-scan.txt
├── examples/sample-authors.txt
├── examples/sample-trend.txt
├── examples/demo-repo/             # demo 仓库工作树快照
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
