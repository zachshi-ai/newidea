# 承诺锈蚀 · TODO Rot

> 每条 TODO 都是一张写给未来的支票，但从不过期、无人对账。
> A zero-dependency CLI that turns `git log` into a promise ledger: how long do paid promises actually take, how much rust is on the unpaid ones — and which ones will statistically never be paid.

---

## 一句话

每个长期项目都有一片「TODO 坟场」：`# TODO: 临时方案，迁移后删掉`。十天的 TODO 和十年的 TODO 在编辑器里长得一模一样，于是没有人还、也没有人销账。`todo-rot` 把 git 历史重放成一本**承诺账本**：每条 TODO/FIXME/HACK/XXX 是谁在哪天写下的（承诺人、立据日）、哪些已被偿还（删除即还清，还清用时就是它的寿命）、还欠着多少**锈蚀分**。真正的杀手锏是：用**已偿还承诺的寿命中位数**算出项目的**承诺半衰期**，超过半衰期两倍还没还的，就是**僵尸承诺**——数据显示它大概率永远不会被偿还了。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 长期项目的维护者 / 技术负责人；以及刚接手一套祖传代码、想分清「哪些 TODO 是真规划、哪些是历史遗迹」的工程师。 |
| **场景** | 版本收尾前的清理排期、季度工程卫生盘点、接手老仓库的尽调、CI 里给「承诺膨胀」设预算红线。 |
| **问题** | **TODO 无限生存且免息**：注释里的承诺没有到期日、没有责任人台账、没有销账机制。人眼看到 300 条 TODO 会麻木，因为无法区分「上周写的」和「上一个世纪写的」。等你想还的时候，最大的问题不是懒，而是**不知道先还哪张、哪些其实已经不用还了**（代码早删了，注释还留着；或承诺的上下文已消失）。 |
| **价值与意义** | 1) **承诺有账龄**：每条标记 git 考古出立据日与承诺人，锈蚀分 = 权重 × 账龄，FIXME 锈得比 TODO 快四倍。<br>2) **半衰期是项目的诚实度体检**：还清一张支票实际用了多久？中位数 30 天的团队和 900 天的团队，写下同一个 TODO 时含义完全不同。<br>3) **僵尸判定给出行动清单**：超过 2× 半衰期仍未还的承诺，统计意义上不会有人还了——要么今天还，要么现在删（诚实的放弃优于无限的拖欠）。<br>4) **CI 预算**：`audit` 把「承诺膨胀」变成可防守的红线。<br>5) **零依赖 + 纯本地**：Python 3.8 标准库 + git，不联网不上传。 |

---

## 核心思想：承诺账本 → 半衰期 → 僵尸

把 `git log -p --unified=0` 重放成一条**承诺事件流**：diff 里出现标记行就是「立据」，消失就是「销账」，由此确定性重建全部账目——不需要 blame 逐行回溯，一次 log 就是全部事实。

| 概念 | 定义 | 直觉 |
|---|---|---|
| **weight** | TODO=1 / XXX=2 / HACK=3 / FIXME=4 | 承认「代码是错的」比「以后更好」锈得快 |
| **rot（锈蚀分）** | weight × 账龄（年） | 这张支票拖出来的锈有多厚 |
| **paid（已偿还）** | 标记行从代码中消失 | 寿命 = 销账日 − 立据日 |
| **died（自然死亡）** | 承诺所在的整个文件被删除 | 不是还清，是债随人亡——单独记账 |
| **half-life（半衰期）** | 全部已偿还承诺寿命的中位数 | 这个项目「说话算话」的典型时长 |
| **ZOMBIE（僵尸承诺）** | 账龄 > max(2×半衰期, 30天) | 统计意义上永远轮不到它被还 |
| **FRESH/AGING/STALE/ANCIENT** | <30 / <180 / <365 / ≥365 天 | 绝对账龄分桶，与僵尸判定互补 |

两个精细处理让账本不撒谎：`git mv` 改名后承诺**保留原立据日**（搬家不是洗账龄）；同一提交里标记换了文件则记为**转址**（re-site），同样不重置年龄。承诺文本被编辑 = 旧票作废（还清）+ 开新票，诚实入账。

## 安装（零依赖）

只需 Python 3.8+ 和 `git`，无需 `pip install` 任何东西。

```bash
python3 todo_rot.py ledger           # 承诺账本：账龄、锈蚀、僵尸
```

## 命令速查

```bash
python3 todo_rot.py scan                          # 工作区速览：多少张支票、多重（无需 git）
python3 todo_rot.py ledger                        # 完整账本：账龄/承诺人/锈蚀分/僵尸（text）
python3 todo_rot.py ledger --format json --top 30 # 机读
python3 todo_rot.py halflife                      # 半衰期 + 每人「开票 vs 还票」的账
python3 todo_rot.py audit                         # CI 门禁：僵尸超预算退出码 1
python3 todo_rot.py audit --max-zombies 0 --max-ancient 5 --max-rot 50
python3 todo_rot.py ledger --as-of 2026-08-18     # 固定「今天」，报告可复现
python3 todo_rot.py ledger --exclude vendor --exclude fixtures
```

公共参数（`--as-of` / `--format` / `--exclude`）跟在子命令之后。`--as-of` 时以纯历史重放为准，不读工作区。

## 一个真实样例

见 [`examples/`](examples/)。三人迷你仓库（可用 `python3 examples/build_examples.py` 从零重建，日期全部固定，提交哈希跨机器可复现）：

```text dd:ignore
-- Promise book -----------------------------------------
  FRESH    #                                          1 promises
  ANCIENT  ###                                        3 promises
  ZOMBIE     1 promises older than 2x half-life — will never be paid
  total rust on the books: 13.2

-- Oldest unpaid (top 15 by rust) -----------------------
    10.4 rot  FIXME     951d ZOMBIE  src/billing.py
           # FIXME: race condition on refund
           promised by Alice Chen at 2024-01-10 (a2c49f07d1)
```

这个仓库的承诺经济学（[`examples/sample-halflife.txt`](examples/sample-halflife.txt)）：两张已偿还支票寿命 51 天和 498 天，半衰期 274.5 天，僵尸阈值 549 天。于是 951 天的退款竞态 FIXME 是僵尸；而 443 天的 sqlite 迁移 TODO 虽然 ANCIENT、却未越过阈值——**账龄老不等于僵尸，要和项目自身的还钱速度比**。这正是本工具与「grep TODO 按日期排个序」的本质区别。

完整报告见 [`examples/sample-ledger.txt`](examples/sample-ledger.txt)。demo 仓库还演示了：`git mv` 后承诺保龄、文件删除导致承诺自然死亡、Alice 开的票被 Bob 还掉（还票记在开票人头上）。

## dogfood：两个真实账本

**click（pallets/click，3321 个提交，快照 as-of 2026-08-18）**——一个自律项目的标准像：

```text dd:ignore
  paid promises    : 11
  median lifetime  : 17 days (the project half-life)
  mean / max       : 364.6 / 3091 days
  zombie threshold : older than 34 days
```

中位数 17 天、均值 364.6 天、最长一张支票拖了 **3091 天（8.5 年）**——教科书级的重尾分布，正是 METHODOLOGY 用中位数而非平均数的理由。click 按自己的标准（阈值 34 天）判定：账上唯一那张 360 天的 `XXX` 已是僵尸。per-author 视角里 Kevin Deldycke 开 9 张还 8 张（空头率 11%），是承诺经济学的正面教材。

**本仓库（newidea）**——工具扫自己出生的仓库：历史里 0 立据 0 销账，工作区 155 张支票全部是「未提交的新票」（因为这个点子目录正是本提交新增的）。工具如实报告了自己出生的事实，没有假装懂。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_todorot.py`](tests/test_todorot.py)，65 个用例，`unittest` + 真实临时 git 仓库，日期全部固定、`--as-of` 钉死「今天」）：

```bash
python3 -m unittest discover -s todo-rot/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 规范化：owner/issue/日期剥离、大小写与标点归一、长度截断、四种标记权重 | `NormTests`（11 例） |
| 扫描：四类标记定位、小写/todo 复数不误报、二进制（扩展名+内容）跳过、.git 与 `--exclude` 前缀过滤、owner/issue/declared 提取 | `ScanTests`（7 例） |
| 解析：sentinel 记录头、oldest-first 重放序、M/A/D/R 状态、±行收集且不混入 +++/--- 头、带空格带引号路径、hunk 外行忽略 | `ParserTests`（7 例） |
| 账本：立据/销账/寿命、无立据的销账记 orphan、同提交转址保龄（含无历史时降级为新票不丢票）、文件删除=自然死亡、文本编辑=还旧开新、rename 更新队列与路径、半衰期中位数与排除项 | `LedgerUnitTests`（10 例） |
| 端到端：根提交立据、精确寿命、三票半衰期、僵尸需半衰期且过阈值、无还票则无僵尸、`git mv` 保龄、删除销户、每人开票/还票/空头率、exclude 前缀、`--as-of` 截断重放、未提交新增/删除计数、同名承诺逐张配对、total rot | `GitIntegrationTests`（13 例） |
| 渲染：空账本、分桶汇总与僵尸行、半衰期表（median/mean/max/每人） | `RenderTests`（3 例） |
| CLI：scan（无 git 也可用）、ledger/halflife/audit 的 text+json、audit 门禁通过/僵尸红线/rot 与 ANCIENT 预算、非 git 目录 exit 2、无子命令 exit 2、参数后置 | `CliTests`（8 例） |
| 样例同步：`--check` 逐字节校验提交样例 + demo 树与重建一致 | `ExamplesSyncTests`（2 例） |
| **dogfood：对本仓库自身出账本，scan 数 = promises + uncommitted 恒等式成立** | `DogfoodTests`（2 例） |

## 项目结构

```
todo-rot/
├── todo_rot.py
├── tests/test_todorot.py
├── examples/build_examples.py
├── examples/sample-ledger.txt
├── examples/sample-halflife.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
