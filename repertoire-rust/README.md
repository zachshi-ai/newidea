# 绝活生锈 · Repertoire Rust

> 学会的绝活会在暗中生锈，直到你当众演奏的那一刻才听见。
> A zero-dependency CLI that keeps a freshness ledger for the repertoire that rusts silently — the songs, pieces and party tricks you once learned and quietly assumed you still own.

---

## 一句话

练琴的时间永远是稀缺的：学新曲子必然冷落老曲子，而生锈没有任何声音——你总是在开放麦之夜、在考级评委面前、在朋友起哄「来一段」的时候才发现它已经死了。练习日记 app 记录「练了多久」，却不回答真正的问题：**哪首还能拿得出手、今晚该练哪首、养活这一整本曲目单每周要花多少分钟**。`repertoire-rust` 的立场：**曲目的「会」不是状态，是随时间衰减的量，而衰减速度是你挣来的**。每首曲子有一个**个人化半衰期**——流畅的完整回忆把它拉长，当众砸掉的回忆把它砍断；从一本 JSONL 练习账出发，算出每首的保鲜度与跌破演出线的日期、把**演出之夜对着全部曲目过闸**（exit 4 = 这场演出没有被覆盖）、给出分钟预算内的今晚计划，以及那笔没人算过的账：**保鲜预算**——让全部曲目站在线上每周要付多少分钟，而你实际付了多少。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 业余乐器学习者（吉他/钢琴/小提琴……曲目一直在长，练习时间一直不够）；备考演奏级的学生（考级曲目清单必须全部拿得出手）；酒吧驻唱/开放麦常客（每场 set list 从存量里现挑）；任何拥有「repertoire 型技能」的人——背过的演讲稿、练过的舞段、变过的魔术、学过的外语课文。 |
| **场景** | 报名了三周后的开放麦（「我现在哪几首真的能上台？」）；今晚只有 40 分钟（练新曲还是救旧曲？）；年终盘点（「今年学了 8 首丢了 5 首，这笔买卖划算吗」）；发现一首老歌突然弹不下来了（「它明明上个月还好好的」）。 |
| **问题** | **生锈是静默的、且自我感觉系统性失真**：① 衰减不可感——每天丢 1% 察觉不到，丢到 60% 才第一次听见，那时已经在台上了；② 「练过 = 会」的错觉——练习日记记录了投入（分钟数），却不追踪**存量**（现在的可演奏度）；③ 练习时间的分配靠感觉——新曲的吸引力永远压过旧曲，没人告诉你「再不碰 Fast Car 就要重学了」；④ 曲目单有账单没人看——每首站在线上的曲子每周都在抽你的维护时间，曲目越攒越多，账单越滚越大，直到「哪首都弹不利索」；⑤ 遗忘不是均匀的——弹了半年的曲子和上周刚啃下来的曲子按同一个日历天数去猜，必然猜错两头的。 |
| **价值与意义** | 1) **个人化半衰期**：每首曲子自己挣来的衰减速度（新曲 7 天起步；q5 完整回忆 ×1.6、q4 ×1.3、q2 ×0.7、砸了 ×0.5；当众演奏再 ×1.25）——「保鲜」第一次有了自己的曲线，不是教科书的艾宾浩斯。<br>2) **保鲜度与触键线**：`保鲜度 = 100 × 0.5^(距上次触键天数 ÷ 半衰期)`，FRESH ≥70（今晚就能上台）/ RUSTING ≥40（本周该碰）/ RUSTED <40（维护已无意义，重建区），并给出跌破演出线的**具体日期**。<br>3) **演出之夜闸门**：`gig --date --need N --must X` 把演出日期对全部活跃曲目过闸——今天新鲜不算数，算的是**那晚**还剩多少；不覆盖就 exit 4。<br>4) **今晚计划**：给定分钟预算，按「最先生锈的先救」贪心填满，一次只安排一个 rebuild（重建耗神，摊开等于都没救成），新鲜 ≥95 的不上台曲子不碰。<br>5) **保鲜预算**：让全部活跃曲目站在演出线上每周需要的维护分钟数 vs 你最近四周实际付的——**曲目单是一张没人看的账单**，欠费状态第一次有了数字。<br>6) **塌方归因**：账本预测 68%、手上只弹出 q2——这是一次 collapse（惊讶失败）；collapse 会把半衰期砍到 21 天封顶，两次塌方的曲子被标记 **never stuck**（维护是演戏：要么慢练重建深度，要么体面退役）。<br>7) **零依赖 + 纯本地**：Python 3.8 标准库，`--as-of` 钉死即逐字节可复现，练习账不出电脑。 |

---

## 核心思想：「会」是一笔会折旧的资产，折旧率是你自己挣来的

练习管理工具都记录流量（练了多久），本件记录存量（还剩多少可演奏），而存量的折旧率不是查表查来的，是从你自己的回忆质量里挣出来的：

| 概念 | 规则 | 回答的问题 |
|---|---|---|
| **半衰期 h** | 新曲 7 天起步；每次触键后按回忆质量更新：q5 ×1.6 / q4 ×1.3 / q3 ×1.0 / q2 ×0.7 / q1 ×0.5，perform 再 ×1.25，钳位 [1, 365] 天 | 「这首曲子的记忆有多耐放？」 |
| **保鲜度 F** | `F = 100 × 0.5^(gap/h)`，gap = 今天 − 上次触键 | 「它现在还剩几成？」 |
| **三档带** | F ≥70 FRESH（拿得出手）/ ≥40 RUSTING（本周该碰）/ <40 RUSTED（重建区）——阈值即 `--line` / `--rebuild-line` | 「现在该做什么？」 |
| **触键线 touch-by** | 上次触键 + h×log₂(100/line)——保鲜度跌到演出线的日期 | 「最晚哪天必须碰它？」 |
| **塌方 collapse** | maintain/perform 会话 q≤2，且会话前账本预测 ≥60、距上次触键 ≥7 天——预测说是、手上说不是；collapse 后 h 封顶 21 天 | 「哪次失败是惊讶，哪次是活该？」 |
| **never stuck** | 塌方 ≥2 次——深度从未达标，维护不产生耐久性 | 「哪首该放弃维护、改慢练重建或退役？」 |
| **演出闸门 gig** | 按演出日重算每首的 F；ready 数 < `--need` 或 `--must` 落榜 → exit 4 | 「那晚我到底拿得出几首？」 |
| **保鲜预算 budget** | Σ 每首（中位维护分钟 × 7 ÷ 触键间隔） vs 最近 28 天实际分钟 ÷ 4 | 「养活这本曲目单每周要付多少？我付了吗？」 |

四条诚实条款刻在实现里：**半衰期是个人的不是教科书的**——同一首曲子在不同人手上衰减速度不同，参数只从你自己的账本里长出来；**今天的 FRESH 不等于那晚的 ready**——gig 按演出日重算，Firefly 今晚 82%、演出夜 36%；**塌方封顶**——一次惊讶失败证伪了「这首已经很耐放」的假设，无论 h 练到多大都砍回 21 天，信任靠重建；**archive 不是删除**——180 天没碰的曲子移出维护盘点（预算与计划不再为它买单），但它还在账上，碰一次就回来。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash dd:ignore
python3 repertoire_rust.py fresh examples/gig-ledger.jsonl   # 哪首在生锈？
```

## 记账格式

一本 JSONL，一行一次练习（字段名固定，质量 1–5 自评：5 = 完整流畅过全曲，1 = 当场散架）：

```json dd:ignore
{"piece": "Fast Car", "date": "2026-08-04", "kind": "maintain", "quality": 2, "minutes": 20}
```

`kind` 三种：`learn`（还在啃）/ `maintain`（复习已经会的）/ `perform`（当众演奏）。`quality` 缺省按 3（中性触键）计，`minutes` 缺省 0。

## 命令速查

```bash dd:ignore
python3 repertoire_rust.py fresh ledger.jsonl                       # 保鲜排行：谁在生锈、保鲜预算
python3 repertoire_rust.py fresh ledger.jsonl --as-of 2026-08-31    # 钉死参照日 → 逐字节可复现
python3 repertoire_rust.py gig ledger.jsonl --date 2026-09-12       # 演出之夜还有几首拿得出手
python3 repertoire_rust.py gig ledger.jsonl --date 2026-09-12 --need 3 --must "Fast Car"  # 过闸，不覆盖 exit 4
python3 repertoire_rust.py plan ledger.jsonl --minutes 45           # 今晚的分钟预算怎么花
python3 repertoire_rust.py show ledger.jsonl "Romance"              # 单曲全部会话 + 塌方档案
python3 repertoire_rust.py fresh ledger.jsonl --format json         # 机读
```

## 一个真实样例

Lena 的吉他账（`python3 examples/build_examples.py` 可从零重建，日期全部钉死，`--check` 逐字节校验）：九首曲子、八个月练习、2026-09-12 的开放麦。参照日钉在 2026-08-31，[`examples/sample-fresh.txt`](examples/sample-fresh.txt) 的判决：

```text dd:ignore
  repertoire    : 8 active pieces · 3 fresh · 2 rusting · 3 rusted · 1 archived · 1 never stuck
  as of         : 2026-08-31 (pinned)
  first to rust : Hotel California Solo — fresh 0%, 62d past its touch-by date
  next to drop  : Firefly falls below the 70 line on 2026-09-02

  piece                  fresh       h         last     touch-by  status
  Hotel California Solo     0%      5d   2026-06-28   2026-06-30  !! RUSTED
  Classical Gas             0%     12d   2026-05-02   2026-05-08  !! RUSTED
  Romance                  38%     21d   2026-08-02   2026-08-12  !! RUSTED · never stuck (2 collapses)
  More Than Words          42%     15d   2026-08-12   2026-08-19  !  RUSTING
  Fast Car                 59%     21d   2026-08-15   2026-08-25  !  RUSTING · 1 collapse
  Firefly                  82%     10d   2026-08-28   2026-09-02     FRESH · fragile (h 10d)
  Wish You Were Here       92%    106d   2026-08-18   2026-10-11     FRESH
  Blackbird                99%    365d   2026-08-24   2027-02-27     FRESH

  keep-alive budget : 158 min/wk holds 8 pieces above the 70 line
  actual (last 4wk) : 54 min/wk — underfunded (34% of budget)
```

读法：**Blackbird 的 h=365 天是半年稳定维护挣来的**，半年不碰都还在台上；Firefly 是 Lena 八月刚写完的新歌，今晚 82%——但半衰期只有 10 天，9 月 2 日就跌破演出线，**今晚的新鲜救不了演出那晚**。最下面是本件的头条：让全部 8 首站在演出线上每周要付 158 分钟，Lena 最近四周只付了 54——**曲目单欠费三倍**，这就是「哪首都弹不利索」的会计学解释。然后是演出闸门（[`examples/sample-gig.txt`](examples/sample-gig.txt)）——12 天后的开放麦，8 首里只有 2 首能活到那晚：

```text dd:ignore
  ready on the night (2):
  ✓ Blackbird               96% on the night ·  99% today · half-life 365d
  ✓ Wish You Were Here      85% on the night ·  92% today · half-life 106d

  won't make it (6):
  ✗ Firefly                 36% on the night ·  82% today · half-life 10d — fresh today is not ready on the night
  ...
  gate: FAIL — need 3 ready, have 2 · must-have "Fast Car" not ready
```

Lena 想在开放麦弹 Fast Car（`--must "Fast Car"`）：账本说不行——那晚它只剩 40%。今晚计划（[`examples/sample-plan.txt`](examples/sample-plan.txt)）在 45 分钟预算里给出诚实的第一步：Classical Gas 重建 37 分钟，**一次只安排一个 rebuild**（Hotel California 和 Romance 排队），剩 8 分钟——离「把 Fast Car 捞回演出线」还差几次这样的晚上，账本会一直看着。[`examples/sample-show.txt`](examples/sample-show.txt) 里 Romance 的档案：两次塌方、两次重建、半衰期两次被砍回 21 天——「ledger said 68%, hands said no」，这首曲子需要的不是 maintenance，是慢练重建，或者体面退役。

## dogfood：样例账本即狗粮

```text dd:ignore
$ python3 examples/build_examples.py --check
examples in sync
```

个人练习数据天然私密，本件不内置任何真人账本。dogfood 的形式与仓库传统一致：**四份样例报告由交付代码本身渲染**（`examples/build_examples.py` 走与 CLI 完全相同的代码路径），CI 用 `--check` 逐字节校验——报告里的每一个数字（158 分钟的账单、82%→36% 的新鲜度、68% 的塌方预测）都能从钉死的账本与 `--as-of` 复现，一份手写的样例都不存在。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_repertoirerust.py`](tests/test_repertoirerust.py)，55 个用例，`unittest` + 合成账本）：

```bash
python3 -m unittest discover -s repertoire-rust/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 账本解析：缺省 quality/minutes、浮点整型收编、多种日期写法、BOM 与空行、坏 JSON 报行号、缺字段/未知 kind/quality 越界/负 minutes 报错、空账本报错、乱序输入按日排序、同日重复会话保留 | `ParserTests`（11 例） |
| 衰减模型：半衰期数学（0/h/2h 天 = 100/50/25）、成长表五档、perform 加成、h 钳位、中性触键重置时钟不动 h、生涩触键缩 h、触键间隔与触键日、三档带边界（70/40 含等号） | `ModelTests`（8 例） |
| 塌方检测：预测 ≥60 且 q≤2 且隔 ≥7 天才塌方、塌方后 h 封顶 21、3 天内的失败是坏日子不是塌方、预测 <60 的失败是重建不是惊讶、两次塌方 → never stuck 入 perma 名单 | `CollapseTests`（5 例） |
| 归档边界：181 天归档、180 天仍在维护盘点 | `ArchiveTests`（1 例） |
| 保鲜预算：需求 = Σ 中位维护分钟×7÷触键间隔（手算对账）、实际 = 28 天窗口分钟÷4、underfunded/holding 判定、无维护史回退默认分钟 | `BudgetTests`（3 例） |
| 演出闸门：今晚新鲜 ≠ 那晚 ready（Firefly 82→36）、FAIL exit 4 与失败清单措辞、PASS exit 0、无 gate 旗标不出 gate 行、must 未匹配 exit 3 | `GigTests`（5 例） |
| 今晚计划：触键日升序 + 贪心填装、预算精确用满、一次 rebuild 上限与 deferred、perma 曲目的重建带警告、≥95 不碰名单 | `PlanTests`（5 例） |
| 报告：未来会话忽略并计数、生锈排行（并列按名）、next to drop 取最早触键日的 FRESH 曲目 | `ReportTests`（3 例） |
| 单曲档案：塌方标注措辞、未知/歧义查询 exit 3、精确匹配优先于子串 | `ShowTests`（3 例） |
| CLI：无参数 exit 2、文件缺失 exit 3、坏 `--as-of` exit 3、坏 `--date` exit 2、line/rebuild-line 校验、四种命令 JSON 可解析、`--as-of` 缺省今天 | `CliTests`（7 例） |
| **dogfood：样例逐字节同步 + demo 判决核验** | `DogfoodTests`（3 例） |

## 项目结构

```
repertoire-rust/
├── repertoire_rust.py
├── tests/test_repertoirerust.py
├── examples/build_examples.py
├── examples/gig-ledger.jsonl
├── examples/sample-fresh.txt
├── examples/sample-gig.txt
├── examples/sample-plan.txt
├── examples/sample-show.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
