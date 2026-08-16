# 知识单点 · Bus Factor

> 把「这段代码只有一个人懂」从直觉变成**可测量的风险账本**：谁在独守哪些文件、他离开的爆炸半径有多大。
> A zero-dependency CLI that measures knowledge concentration from git history — who solely guards which file, and what breaks if they leave tomorrow.

---

## 一句话

每个技术负责人都被问过（或问过自己）这个问题：「如果 X 明天离职，哪块业务会瘫？」——而答案从来只能靠拍脑袋。可 git 里明明躺着全部事实：**每个文件谁改过、改过多少行**。`bus-factor` 把这些事实变成一组可复算的指标：文件的知识份额、卡车因子（Truck Factor）、独守人清单、以及任何一人离开时的**爆炸半径**。不是绩效工具，是一份**团队知识分布的风险报告**。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 技术负责人 / 工程经理；以及休假或离职季需要安排交接的团队。 |
| **场景** | 季度风险盘点、核心成员提出离职 / 请长假、代码 ownership 治理、并购或外包交接前的尽调。 |
| **问题** | **知识分布风险不可见**：一个仓库里有多少文件「事实上只有一个人懂」，没有任何工具回答；等那人离开才发现支付回调、构建脚本只有他动过。人工盘点靠拍脑袋，交接文档靠离职前最后一周赶工——而风险本可以提前一年看见。 |
| **价值与意义** | 1) **把直觉变指标**：卡车因子从传说变成每文件、每模块、每人的可复算数字。<br>2) **爆炸半径模拟**：`radius` 一条命令回答「如果 X 离开会怎样」，直接产出交接清单（哪些文件**没有任何第二作者**）。<br>3) **提前治理**：RED 文件清单 + 行动建议（配对 / review / 轮岗），在风险变成事故前消化它。<br>4) **零依赖 + 纯本地**：不联网、不上传，公司代码也适用。 |

---

## 核心思想：知识份额 → 风险分级 → 爆炸半径

对每个文件，从 `git log --numstat` 确定性重建**每位作者的知识份额**（按新增行数加权，pair programming 经 `Co-Authored-By` 双方计入——度量的是「谁懂」，不是「谁产出」），然后：

| 指标 | 定义 | 直觉 |
|---|---|---|
| **share** | 作者新增行数 ÷ 全部作者新增行数 | 这个人对这份代码的「熟悉度代理」 |
| **TF** (truck factor) | 份额降序累积到 **≥50%** 所需的最少作者数 | 「几卡车才撞得垮这个文件」 |
| **guardian** | 单人份额 **≥80%** | 事实上的独守人 |
| **critical** | 单人份额 **≥50%** | 少了他，剩下的人凑不够一半 |
| **RED / AMBER / GREEN** | TF=1 / TF=2 / TF≥3 | 单点 / 脆弱 / 健康 |

再加两个组织级视图：**guardians**（谁在独守哪些文件）与 **radius**（某人离开的爆炸半径：失守文件数、行数、以及**零第二作者**的交接清单）。

`git mv` 不会骗过它：rename 链把移动前的历史接到新路径上（这个特性正是首次 dogfood 时被本仓库自己的重组提交逼出来的，见下文）。

---

## 安装（零依赖）

只需 Python 3.8+ 和 `git`，无需 `pip install` 任何东西。

```bash
python3 bus_factor.py scan            # 当前仓库风险报告
```

## 命令速查

```bash
python3 bus_factor.py scan                          # 全库风险报告（text）
python3 bus_factor.py scan --format json --top 20   # 机读；列 20 个文件
python3 bus_factor.py scan --window 365             # 只看近一年（知识会过期）
python3 bus_factor.py scan --fail-on red            # CI：存在 RED 退出码 1
python3 bus_factor.py file bus_factor.py             # 单文件：谁的份额多少
python3 bus_factor.py module src/billing            # 目录聚合：模块级 TF
python3 bus_factor.py guardians                     # 独守人清单 + 交接标记
python3 bus_factor.py radius "alice"                # alice 离开的爆炸半径
python3 bus_factor.py scan --min-lines 100          # 只看 ≥100 行的文件
python3 bus_factor.py scan --no-coauthored          # 关掉 pair 学分
python3 bus_factor.py scan --include-bots           # 把 dependabot 也算进来
```

公共参数可放在子命令前后任意一侧；`--as-of YYYY-MM-DD` 固定「今天」，用于可复现报告与测试。

---

## 一个真实样例

见 [`examples/`](examples/)。三人团队 + 一只 dependabot 的迷你仓库（可用 `python3 examples/build_examples.py` 从零重建，全部日期固定）：

```text dd:ignore
-- Risk --------------------------------------------------
  RED    #####     550 lines    5 single-owner knowledge
  AMBER  #         100 lines    1 two authors
  --> 85% of measured lines are RED (knowledge in exactly one head)

-- Sole guardians (>= 80% share) -------------------------
  Alice Chen            2 files      200 lines
      auth.py, core.py
  Chen Wu               1 files      200 lines
      payments/webhook.py
```

`radius chen` 会告诉你是哪 200 行知识在一个人脑子里：

```text dd:ignore
bus-factor blast radius — if Chen Wu leaves tomorrow
  critical (share >= 50%): 1 files, 200 lines
  handoff  (guarded, zero other authors): 1 files, 200 lines
  Handoff checklist — nobody else ever touched these:
    payments/webhook.py
```

完整报告见 [`examples/sample-report.txt`](examples/sample-report.txt) 与 [`examples/sample-radius.txt`](examples/sample-radius.txt)。

**首次 dogfood 即抓到真实盲点**：工具完成后第一件事是扫描本仓库（newidea），`decision-debt/` 下的所有文件卡车因子为 0、作者为空——因为 8ac5fc4 曾把整个项目 `git mv` 重组进子目录，按路径匹配的历史全部断裂。于是实现了 rename 链解析（`git log --diff-filter=R` 的传递闭包），并用 `GitIntegrationTests.test_git_mv_preserves_history` 固化。

---

## 季度仪式（每季一次，5 分钟）

1. `python3 bus_factor.py scan` —— 先看全库：RED 行数占比、独守人清单。
2. 对每个独守人跑 `radius`，把「零第二作者」清单变成配对 review / 轮岗计划——**用第二个作者消化风险，而不是重写代码**。
3. 把 `scan --format json` 存档进 issue，下季度对比：RED 是在变小，还是又长出了新的单点。
4. 想守住下限？CI 里挂一道闸门：

```yaml
# .github/workflows/bus-factor.yml
- run: python3 bus-factor/bus_factor.py scan --fail-on red --min-lines 200
```

只对大文件开闸（`--min-lines` 抬高阈值），避免误伤——门槛是治理策略，工具只负责如实测量。

---

## 验收标准与测试

验收标准全部转成自动化测试（`tests/test_busfactor.py`，62 个用例，`unittest` + 真实临时 git 仓库，所有日期固定、输出跨进程确定）：

```bash
python3 -m unittest discover -s bus-factor/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 解析：log 记录/字段/numstat/二进制 `-`/花括号与箭头 rename 展开 | `ParserTests`（11 例） |
| 解析：rename 状态行与传递闭包（含环安全） | `ParserTests` |
| 身份：bot 识别（dependabot 等）、邮箱归一化、多姓名变体、三层 resolve（姓氏优先邮箱，不误配 display 名） | `AuthorTests`（5 例） |
| 指标：份额、TF（1/2/3、50% 边界、空集）、HHI、有效人数、guardian 80% 边界、critical、风险分级 | `MetricTests`（12 例） |
| 端到端：独守 / 50-50（TF=1 无 guardian）/ 三人分摊（TF=2）/ min-lines 过滤 / 当前行数≠累计 churn | `GitIntegrationTests` |
| 端到端：爆炸半径（孤儿文件 vs 共享作者）、guardians 视图 | `GitIntegrationTests` |
| 端到端：bot 默认忽略且可含、Co-Authored-By 学分（50/50）与关闭开关 | `GitIntegrationTests` |
| 端到端：`git mv` 后历史不断裂；已删除文件默认排除、`--include-deleted` 考古 | `GitIntegrationTests` |
| 端到端：`--window` 时间窗过滤、目录聚合 | `GitIntegrationTests` |
| CLI：子进程独立运行、text/json 结构、`--fail-on red|none` 退出码、未知作者/文件/非 git 目录 exit 2、全局参数可置于子命令后 | `CliTests`（13 例） |
| 样例同步：demo 仓库重建后关键数字硬断言（TF/guardian/风险档/作者数）+ 与提交样例逐字节一致 | `ExamplesSyncTests`（3 例） |
| **dogfood：对本仓库自身扫描，结构完整且如实反映单人维护现状** | `DogfoodTests`（2 例） |

---

## 项目结构

```
bus-factor/
├── bus_factor.py
├── tests/test_busfactor.py
├── examples/build_examples.py
├── examples/sample-report.txt
├── examples/sample-radius.txt
├── METHODOLOGY.md
└── README.md
```

---

## License

MIT © 2026（见[仓库根目录](../LICENSE)）
