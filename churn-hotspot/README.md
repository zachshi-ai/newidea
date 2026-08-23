# 变更热点 · Churn Hotspot

> 重构不该从最大的文件开始，该从「**改得最频繁 × 改动代价最高**」的交集开始：
> `hotspot score = churn × size`，加上恶化 / 自愈趋势——重构优先级第一次有了可复算的答案。
> A zero-dependency CLI that ranks where refactoring pays off most, straight from git history.

---

## 一句话

每个技术负责人都开过这种会：技术债列了满满一白板，重构资源只够修三个，先修哪个？直觉偏爱**最大的文件**或**最乱的文件**——但重构 ROI 最高的地方是两根轴的交集：**改得频繁**（业务活跃，每次改动都在付利息）× **文件大**（每次改动付的利息更多）。这个交集没有工具可视化，排期就退化成「谁嗓门大听谁的」。`churn_hotspot` 用 `git log` 把交集变成一张可复算的表：每个文件的 **churn**（窗口内被多少提交 touch）、**size**（当前行数）、**score**（乘积）与等级，再沿时间轴切成前后两半，标注这个热点是在**持续流血**、**新爆发**，还是**正在自愈**——其中「正在自愈的文件，别投重构预算」是反直觉但有数据支撑的洞察。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 技术负责人 / 架构师 / 重构专项的发起人。 |
| **场景** | 季度重构规划、技术债排期、向上级要重构资源的立项汇报、代码冻结前的最后清理。 |
| **问题** | **重构优先级靠拍脑袋**。每个文件都能列出一堆毛病，但资源有限必须排序；直觉选中的往往是「最大 / 最乱」的文件，而真正天天流血的是「改得又频繁、每次改动代价又高」的交集文件。这个交集不可见——没有指标、没有报表、没有趋势，于是排期变成政治问题。 |
| **价值与意义** | 1) **把直觉变指标**：hotspot score = churn × size，经典方法（Adam Tornhill《Software Design X-Rays》热点分析）的零依赖可用版本。<br>2) **时间轴让排序可行动**：PERSISTENT（专项重构第一优先级）/ EMERGING（现在介入还便宜）/ COOLING（**别投预算，它在自愈**）。<br>3) **抗噪音**：lockfile、vendored、生成代码默认排除；一次性写就的大文件明确不算债务（创建 ≠ 债务）。<br>4) **零依赖 + 纯本地**：不联网、不上传，公司代码也适用。 |

---

## 核心思想：付息频率 × 每次付息金额

对每个文件，从 `git log --name-status` 确定性重建它在窗口内的 **touch 历史**（哪些提交改过它、分别在哪半窗口），然后：

| 指标 | 定义 | 直觉 |
|---|---|---|
| **churn** | 窗口内 touch 该文件的提交数 | 付息频率：这文件多久被改一次 |
| **lines** | 当前行数 | 每次付息金额：改它一次要读多少上下文 |
| **score** | churn × lines | 这个文件每季度「支付」的维护利息 |
| **RED / AMBER** | 反复改动的文件中 score 的 P90 / P75（小仓库退化规则见方法论） | 重构专项候选 / 观察名单 |
| **PERSISTENT** | 前后两半窗口都 ≥3 次 touch | 持续流血：计划专项重构 |
| **EMERGING** | 最近半窗 ≥3 次、之前 ≤1 次 | 新爆发：现在介入还便宜 |
| **COOLING** | 之前半窗 ≥3 次、最近 ≤1 次 | 正在自愈：**别把预算花在这** |

三条设计防线防住三类假热点：

1. **churn < 3 永远不进 RED/AMBER**——一次性写就的大文件是「创建」，不是「债务」；
2. **默认排除 lockfile / vendored / 生成代码**——它们的 churn 是依赖噪音，与设计质量无关；
3. **已删除文件、二进制文件自动消失**——热点表里只有活着的、要人维护的代码。

`git mv` 不会骗过它：`--name-status` 的 `R100 old new` 记录构成 rename 链，改名前的历史全部归到当前路径（见 [METHODOLOGY.md](METHODOLOGY.md)）。

---

## 安装（零依赖）

只需 Python 3.8+ 和 `git`，无需 `pip install` 任何东西。

```bash
python3 churn_hotspot.py scan            # 当前仓库热点表
```

## 命令速查

```bash
python3 churn_hotspot.py scan                          # 热点 Top 20（默认窗口 180 天）
python3 churn_hotspot.py scan --window 90              # 只看近一季度
python3 churn_hotspot.py scan --format json --top 50   # 机读
python3 churn_hotspot.py scan --fail-on red            # CI：存在 RED 退出码 1
python3 churn_hotspot.py trend                         # PERSISTENT / EMERGING / COOLING 分组
python3 churn_hotspot.py file churn_hotspot.py          # 单文件画像 + 周活动直方图
python3 churn_hotspot.py scan --exclude 'docs/*'       # 追加排除 glob（可重复）
python3 churn_hotspot.py scan --no-default-excludes    # 连 lockfile 也算进来
python3 churn_hotspot.py scan --min-lines 100          # 忽略小文件
python3 churn_hotspot.py scan --as-of 2026-08-24       # 固定「今天」，可复现报告
```

公共参数可放在子命令前后任意一侧；`--as-of` 固定时间基准，用于可复现报告与测试。

---

## 一个真实样例

见 [`examples/`](examples/)。迷你电商后端（可用 `python3 examples/build_examples.py` 从零重建，全部日期固定）：

```text dd:ignore
  1  RED    checkout/flow.py  churn   7  lines   318  score    2226  [persistent]
  2  AMBER  search/legacy_index.py  churn   5  lines   258  score    1290  [cooling]
  3  GREEN  pay/api.py  churn   5  lines   228  score    1140  [emerging]
```

这张 7 行的表浓缩了全部方法论：

- **`checkout/flow.py`（RED + persistent）**：整季都在流血的核心，重构专项第一优先级，没有争议。<!-- dd:ignore: demo 虚构文件，样例见 examples/ -->
- **`search/legacy_index.py`（AMBER + cooling）**：score 全库第二——按直觉它该排第二优先级；但趋势列说它前半窗 4 次、最近半窗只有 1 次，**正在自愈**。把预算花在它身上，是在为一个正在消失的问题买单。<!-- dd:ignore: demo 虚构文件，样例见 examples/ -->
- **`pay/api.py`（GREEN + emerging）**：score 只排第三，等级甚至 GREEN——分数和等级都看不见它；但趋势列说它从「没人动」变成「三周改四次」。**新火情按定义是分数看不见的**（它的分数还没涨起来），这正是趋势轴存在的理由：现在补测试、做拆分，成本只有等它长成 flow.py 之后的一个零头。<!-- dd:ignore: demo 虚构文件，样例见 examples/ -->

---

## Dogfood：本仓库自身

```bash
python3 churn_hotspot.py scan --as-of 2026-08-24 --window 60
```

对 newidea 仓库自己跑 60 天窗口：46 个文件里唯一的 RED 是——**根 `README.md`**（churn 5，emerging）。事实完全吻合：每交付一个点子它就被登记一次，是全仓库唯一被反复修改的「活文件」。顺带这次 dogfood 还逼出了一个真实 bug：`git log --since` 是**遍历剪枝**而非日期过滤，历史上日期交错时会静默漏提交——现在日期过滤完全在解析侧完成（见 [METHODOLOGY.md](METHODOLOGY.md) FAQ）。

---

## 验收标准

全部验收已转为自动化测试（`python3 -m unittest discover -s churn-hotspot/tests`，40 tests）：

| # | 验收标准 | 对应测试 |
|---|---|---|
| 1 | `scan` 输出 Top-N 热点表（churn / lines / score / 等级 / 趋势），按 score 降序，score = churn × lines | `test_scan_tables_have_score_churn_lines_sorted_desc` |
| 2 | 已删除文件、二进制文件（NUL 检测）永不出现 | `test_deleted_files_never_appear` / `test_binary_files_never_appear` |
| 3 | 默认排除 lockfile / vendored / 生成代码；`--no-default-excludes` 关闭；`--exclude` 追加 glob | `test_lockfile_excluded_by_default_but_counted` 等 |
| 4 | churn < 3 的文件永远不进 RED/AMBER（创建 ≠ 债务） | `test_churn_below_3_never_earns_red_or_amber` |
| 5 | 等级自适应：≥5 个热点文件用 P90/P75 分位；小仓库退化为「最差者 RED」 | `test_percentiles_on_large_repos` / `test_small_repo_worst_eligible_is_red` |
| 6 | 窗口平分两半，趋势分类 PERSISTENT / EMERGING / COOLING / STABLE 且两半之和 = churn | `test_trend_classes_are_classified` / `test_trend_halves_sum_to_churn` |
| 7 | `--window` 只统计窗口内 touch；`--as-of` 固定基准，输出可复现 | `test_window_filters_old_commits` / `test_as_of_is_reproducible` |
| 8 | `trend` 分组报告附行动建议（含「cooling 别投预算」） | `test_trend_text_groups_with_advice` |
| 9 | `file` 单文件画像：指标 + 周活动直方图；未知文件退出码 2 | `test_file_profile_with_histogram` / `test_unknown_file_exits_2` |
| 10 | rename 链：`git mv` 后历史 churn 归到当前路径 | `test_rename_keeps_churn_on_live_path` |
| 11 | `--fail-on red/amber` CI 退出码；无热点时通过 | `test_fail_on_red_exits_1_when_red_exists` / `test_fail_on_passes_when_no_hotspots` |
| 12 | RED/AMBER 即使被 `--top` 截断也强制出现在表中 | `test_red_amber_survive_top_cut_in_text` |
| 13 | 零依赖：Python 3.8+ 标准库 + git，`python3 -m unittest` 即可验证 | 全部 |

---

## 与本仓库其他点子的关系

这是「点子实验室」的第六件作品，也是系列拼图的收口：决策债务、gitweek、文档漂移、知识单点、承诺锈蚀都在**发现问题**；这一件回答发现一堆问题之后最贵的问题——**先修哪个**。它也和 [bus-factor](../bus-factor/) 互补：bus-factor 说「这个文件只有一个人懂」，churn-hotspot 说「这个文件值得你派人去懂」。

## License

MIT © 2026
