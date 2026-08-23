# 危险时刻 · Witching Hour

> 每个 bug 都有两个时间戳：**写下它的那一刻**，和**发现它的那一刻**。所有工具只给你第二个。
> A zero-dependency CLI that blames the lines a fix commit deleted back to the commit where they were BORN — so defects land in the wall-clock window that wrote them, not the one that caught them.

---

## 一句话

「疲劳时写的代码质量差」人人会讲，却永远是轶事——bug 被发现时往往已过了好几天，没人记得它是**几点**写下的。`witching-hour` 把 fix commit 删掉的每一行用 `git blame` 追溯到它的**出生 commit**，按**作者当时墙上的钟**分时段，与同时段的产出基线对比：如果凌晨 0-3 点只贡献 19% 的代码行，却贡献了 35% 的后来被修的行，该时段的**缺陷相对风险 RR = 1.92**——统计意义上的「女巫时刻」。它的回答不是「谁在熬夜」（那是负荷观测），而是「**几点写下的代码最容易带着 bug 活到白天**」。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 想用数据而非说教审视加班文化的工程负责人 / TL；想找到自己生物钟风险窗口的工程师个人；on-call 事故复盘主持人。 |
| **场景** | 季度工程健康复盘（「加班换来的进度到底返工了多少」）；事故归因会（这个 bug 是什么状态下写下的）；个人年终自省（「我的危险时段是凌晨还是周五下午」）。 |
| **问题** | **缺陷的责任时刻被系统性错记**：CI 记录的是修复时刻，周报记录的是发现时刻，但 bug 的「出生证明」——它被写下的那一刻——从来无人签发。于是「深夜代码质量差」无法证伪也无法证实：个人看不到自己的时段风险，团队无法核算加班的隐性返工成本，「早点睡」永远停留在建议层面。 |
| **价值与意义** | 1) **归因而非观测**：不是统计「几点在提交」，而是统计「几点写下的行后来被修」——把质量问题连本带利记回它的出生时刻。<br>2) **RR 而非绝对数**：深夜缺陷多不算数，要除以深夜产出占比——**单位产出的缺陷率**才是公平比较。<br>3) **墙钟原则**：每个提交按作者当时的本地钟点入账，分布式团队的北京凌晨与伦敦傍晚永不混淆。<br>4) **统计纪律**：缺陷行 < 20 整份报告自我降级为「轶事」；单窗口 < 5 行不下结论（`low-n`）。<br>5) **零依赖 + 纯本地**：Python 3.8 标准库 + git，不联网不上传，不碰绩效系统。 |

---

## 核心思想：两条时间线 → 出生证明 → 风险比

把 `git diff` 与 `git blame` 串成一条归因链：fix commit **删掉的行**是嫌疑行，blame 到它们**最后被写下的 commit** 拿到出生时刻，按作者墙钟入桶，再与全历史的产出分布对比。

| 概念 | 定义 | 直觉 |
|---|---|---|
| **出生时刻（birth）** | 被 fix 删掉的行，其 blame 指向 commit 的作者钟点 | bug 的「犯罪现场」，不是「结案时刻」 |
| **嫌疑行** | fix commit diff 中被删除/修改的旧行 | 修复通常是替换掉写坏的行；纯新增的行不背锅 |
| **D%（缺陷份额）** | 该时段出生的嫌疑行 / 全部嫌疑行 | 这个时段「贡献」了多少日后返工 |
| **W%（产出份额）** | 该时段变更行数 / 全部变更行数 | 这个时段实际写了多少（基线） |
| **RR（风险比）** | D% ÷ W% | 单位产出的缺陷率：RR=2 即同样一行代码，此时段写出的被修概率是平均的 2 倍 |
| **DANGER** | RR ≥ 1.5 且嫌疑行 ≥ 5 | 统计上站得住的「女巫时刻」 |
| **low-n** | 嫌疑行 < 5 | 有数字，但样本不配拥有结论 |
| **insufficient** | 全仓嫌疑行 < 20 | 整份报告自认是轶事 |

三个诚实条款刻在实现里：merge commit 完全不可见（`--no-merges`），其冲突解决行被 fix 追溯时记为 **unborn**（无出生证明，不硬归因）；rename 后 blame 穿透改名找到真正的出生 commit；根 commit 上没有 fix（无 parent 可 diff），静默跳过。

## 安装（零依赖）

只需 Python 3.8+ 和 `git`，无需 `pip install` 任何东西。

```bash
python3 witching_hour.py scan    # 你的 bug 是几点写下的？
```

## 命令速查

```bash dd:ignore
python3 witching_hour.py scan                          # 归因主报告：窗口表 + RR + 判定
python3 witching_hour.py scan --min-total-lines 10     # 放宽统计门槛（小仓库）
python3 witching_hour.py scan --fix-pattern '(?i)defect|修复'
python3 witching_hour.py scan --author "Bob Li"        # 只看一个人的危险时段
python3 witching_hour.py rhythm                        # 编码生物钟：24 小时 + 星期分布
python3 witching_hour.py birth src/billing.py          # 一份文件的逐行出生证明
python3 witching_hour.py birth src/billing.py --danger-only   # 只看深夜出生的行
python3 witching_hour.py scan --format json            # 机读
```

## 一个真实样例

三人迷你仓库（`python3 examples/build_examples.py` 可从零重建，日期全部钉死，提交哈希跨机器可复现）：alice 白天型高产出，bob 三次凌晨 2-3 点会话，carol 周五深夜修生产事故。[`examples/sample-scan.txt`](examples/sample-scan.txt) 的判决：

```text dd:ignore
  window   defect  work     D%     W%     RR   verdict
  00-03        7     38   35.0   18.3   1.92   ! DANGER
  03-06        2     13   10.0    6.2   1.60   low-n
  09-12        6     86   30.0   41.3   0.73   ok
  ...
  top birth hours: 02:xx 7 lines, 10:xx 3 lines, 11:xx 3 lines
```

读法：bob 的凌晨会话只写了 18.3% 的行，却埋下了 35% 的日后返工，RR 1.92 判 DANGER；03-06 窗口 RR 1.60 但只有 2 行嫌疑，工具拒绝下结论（`low-n`）——**该沉默时沉默，这是特性不是缺陷**。而 [`examples/sample-birth.txt`](examples/sample-birth.txt) 里那份 `src/billing.py` 的出生证明更直观：25 行代码 17 行诞生于 02:47，一周后白天的修复 commit 换掉了其中 8 行。<!-- dd:ignore: src/billing.py 为 demo 仓库内示例文件，非本仓库引用 -->

```text dd:ignore
  L   1  2026-03-03 02:47  Bob Li             <- witching hour
  ...
  25 line(s) shown, 17 born inside 22:00-06:00.
  Those lines were written against the body's will.
```

## dogfood：扫它自己出生的仓库

```text dd:ignore
-- Witching Hour scan: newidea
  commits scanned        : 5   (2026-08-12 .. 2026-08-18)
  fix commits matched    : 0
  defect lines attributed: 0

  ! only 0 defect lines attributed (< 20 needed).
```

这个「点子实验室」自身的 5 个 commit **全部诞生于 00:00-03:00**（rhythm 直方图里 3463 行变更无一行在白天）——点子确实是深夜长出来的。但工具拒绝趁势讲故事：没有 fix commit 就没有嫌疑行，没有嫌疑行就没有 RR，于是它如实打出 insufficient。等这个仓库开始修自己的 bug，凌晨造点子的返工率自然会浮出水面。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_witchinghour.py`](tests/test_witchinghour.py)，38 个用例，`unittest` + 真实临时 git 仓库，`GIT_AUTHOR_DATE` 钉死每个时间戳）：

```bash
python3 -m unittest discover -s witching-hour/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 墙钟：`%aI` 作者本地钟点入桶、UTC 与 +08 的同一时刻各归各桶、跨午夜危险窗口 | `HourTests`（7 例） |
| diff 解析：旧侧行号收集、count 省略 = 1、`-l,0` 纯插入不产生嫌疑行、/dev/null 跳过 | `DiffParserTests`（3 例） |
| blame 解析：porcelain 头 → 行号到出生 sha、元数据行不误匹配 | `BlameParserTests`（1 例） |
| 统计：RR 计算、DANGER/ok/low-n/- 四种判定、无活动窗口不除零 | `StatsTests`（5 例） |
| 归因链：深夜引入行落到深夜桶、纯新增行不归因、时区墙钟、merge 排除且其解决行记 unborn、rename 穿透归因、root commit 不炸、`--max-fix-commits` 留新弃旧、`--author` 过滤、中文修复消息识别、churn 基线 = adds+dels | `GitIntegrationTests`（12 例） |
| CLI：scan/rhythm/birth 的 text+json、`--danger-only`、非 git 目录 exit 3、无子命令 exit 2、参数后置 | `CliTests`（6 例） |
| 样例同步：demo 树与三份报告可从零重建且逐字节一致 | `ExamplesSyncTests`（2 例） |
| **dogfood：对本仓库自身 scan/rhythm 不崩且内部恒等** | `DogfoodTests`（2 例） |

## 项目结构

```
witching-hour/
├── witching_hour.py
├── tests/test_witchinghour.py
├── examples/build_examples.py
├── examples/demo-repo/
├── examples/sample-scan.txt
├── examples/sample-rhythm.txt
├── examples/sample-birth.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
