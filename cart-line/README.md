# 凑单线 · Cart Line

> 平台战报只写「已为你节省 ¥460」，从不写「其中你为凑单又花了 ¥232」——省略的那半句，恰好等于你没省下的钱。
> A zero-dependency CLI that draws the checkout line (gap vs discount: fill inside the win zone, walk away outside it), audits the savings banner against what fillers really cost you, and tracks whether the stuff you bought for the line ever gets used.

---

## 一句话

结算页只展示一个数字——「已为你节省 ¥X」，而凑单决策的四个变量（购物车小计、满减门槛、优惠额、凑单价）一个都不出现在那行字里。直觉算得出门槛（「再买 32 就能减 50！」），算不出白赚区间（凑 32 省的是 18，凑 60 反而多花 10）；年底的战报记得每一分优惠额，从不记得你为凑单加购的每一件「顺手买了」；为凑单买的东西到家后的命运——用上了、吃灰了、扔了——没有任何账本记录。于是每年两场大促成了全民数学考试，而所有人只对答案的第一行。`cart-line` 的立场：**优惠从来不是钱，少花的钱才是钱；而「少花」必须先扣掉「为凑而多买」的每一元**。工具把这道题拆成四本账：**决策线**（缺口 g 与优惠 d 之比定生死——g ≤ d 存在白赚区间 [g, d]，g > d 判凑不平 NOT_WORTH，放弃满减是数学最优）；**幻觉审计**（每单净收益 = 优惠 − 凑单额；幻觉差 = 平台口径 − 真实净收益 ≡ 凑单总额，代数恒等式钉到 9 位小数——平台每省略你花掉的凑单钱，差的就是那笔钱本身）；**优惠分层**（折扣拆成 free——不凑单也能拿的，和 earned——用凑单品换来的，现金差 = 凑单额 − earned）；**命运对账**（凑单品垃圾率 vs 计划商品垃圾率：促销诱发的购买是不是更容易吃灰，第一次有了行为证据）。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 被满减反复勾引的网购用户——双 11/618 全民数学考试的考生；平时被「满 99 减 20」「每满 300 减 50」精确狙击的人；月底看着账单觉得「优惠都拿了怎么还是花超了」的人。 |
| **场景** | 结算页前的最后五分钟：购物车 268 元，满 300 减 50，货架上三件候选凑单品 15/32/49 元——加哪个？加多少？还是不加了？月底：平台战报弹出来「本月已为你节省 ¥460」，你想知道这里面有多少是真的。拆快递时：为凑单买的手机支架、搞怪袜子、桌面垃圾桶，和认真挑的洗衣液、空气炸锅一起躺在箱子里——它们会有不同的命运吗。 |
| **问题** | **四变量函数靠直觉**：小计 s、门槛 m、优惠 d、凑单价 c 的组合让结算页变成考场，但没有人带着计算器购物——凑超（c > d 倒贴）、硬凑（缺口 > d 的单注定凑不平）、过线手贱（优惠已到手又加购）三种错误每周原样重演，因为没人给它们记过账。**战报的单行本**：平台口径「已节省」= 优惠额合计，这个口径在代数上永远 ≥ 真实净收益，而两者的差恰好等于凑单总额——平台不是算错，是只印对自己有利的那一行。**凑单品命运无人追踪**：为凑单买的东西有没有用上，从没有一本账回答过；「凑单买的东西反正便宜」是幻觉还是事实，没有分母。 |
| **价值与意义** | 1) **一条可以脱口而出的线**：`judge` 把四变量函数压成一次比较——缺口 g ≤ 优惠 d 则存在白赚区 [g, d]（凑单额落区内实付必降，缺口卡线净赚最大 d−g），g > d 则直接判 NOT_WORTH（exit 4）：任何凑单要么不触发、要么倒贴，放弃满减就是数学最优。候选凑单品逐件裁决（FILL/OVERPAY），还能枚举最优组合——「这三件小东西挑哪几件凑」从拍脑袋变成一次子集求和。<br>2) **幻觉差 ≡ 凑单总额**：`audit` 从手编订单账算出每单净收益 = 优惠 − 凑单额，账期总计满足恒等式 **discount − net ≡ filler**（测试钉到 9 位小数）：示例账本平台喊「省 ¥460」，真实净赚 ¥228，差 ¥232 恰好等于凑单总额——不是巧合，是代数。再看分层：¥460 优惠里 ¥300 是 planned 本身就过线的 free 层（不凑也能拿），真正用凑单品换来的 earned 只有 ¥160，而为它付了 ¥232——**现金口径多付 ¥72**。<br>3) **凑单税率**：filler ratio = 凑单额 ÷ 优惠额，示例账本 50.4%——平台喊的每 1 元优惠里有 5 毛被你自己的凑单花掉了，红线 30%，超线 exit 4。这是「这场大促省没省」的第一个可讨论的数字。<br>4) **决策回放**：`simulate` 把每一单对着理论最优重放（裸买 vs 恰好卡线取最小），凑超/硬凑/过线手贱/欠线不达四种错误逐一定价：示例账本 8 单里 4 单 optimal、4 单多付合计 ¥117——其中 ¥68 花在一张数学上注定凑不平的单上，而最优决策本可以比「全部裸买」还省 ¥45。<br>5) **命运对账**：`fate` 给凑单品与计划商品分别算垃圾率（idle+trashed ÷ settled，金额与件数双口径，open 不进分母）：示例账本凑单品 69.5% vs 计划商品 14.1%——**促销诱发的购买吃灰速度是计划购买的 4.9 倍**，行为经济学的结论第一次从你自己的账本里长出来。<br>6) **零依赖 + 纯本地**：Python 3.8 标准库，账本手编 TSV，一行不出电脑。 |

---

## 核心思想：一条线，一个恒等式，一本命运账

| 概念 | 规则 | 回答的问题 |
|---|---|---|
| **凑单线** | 缺口 g（到下一档优惠还差多少钱）与优惠 d 之比定生死：g ≤ d → 白赚区 [g, d]，凑单额落区内实付必降；g > d → NOT_WORTH，任何凑单都倒贴；已过线（full）或恰好压线（every）→ 线为 0，别动。单档 full:M:D 与每满 every:M:D 共用同一条判据 | 「这一单数学上怎么走？」 |
| **卡线命题** | 给定档位，实付随凑单额严格递增 → 最优凑单额永远在缺口卡线处（C\* = g），多凑的部分纯花钱 | 「为什么总是恰好凑到线最划算？」 |
| **净收益** | 每单 net = discount − filler；正 = 真省，负 = 倒贴（paid 比裸买还贵） | 「这一单的优惠扣掉凑单还剩多少？」 |
| **幻觉差恒等式** | discount − net ≡ filler（代数恒等式，9 位小数）：平台口径与真实口径的差恰好等于凑单总额——省略即差额 | 「战报里省略了什么？」 |
| **优惠分层** | discount = free（planned 自身已过线）+ earned（靠凑单换来）；现金差 = filler − earned = 实付 − 全裸买；net = free − 现金差 | 「哪些优惠本来就属于我？」 |
| **凑单税率** | filler ratio = filler ÷ discount，红线 30%：每 1 元优惠被凑单吃掉的比例 | 「这场大促省没省？」 |
| **命运双口径** | 垃圾率 = (idle + trashed) ÷ settled（open 未表决不进分母），凑单侧要求金额覆盖率 ≥ 50% 才判灯 | 「为凑单买的东西后来怎样了？」 |
| **红线与门槛** | filler ratio > 30% → exit 4；订单 < 5 或凑单 settled < 5 件 → exit 3 拒绝下结论；恒等式破 → exit 2——宁可沉默，不出没有证据的报告 | 「这个结论背后有多少证据？」 |

三条边界刻在实现里：**filler 是动机不是商品属性**——同一件抽纸，在回购清单上是 planned，顺手拿的是 filler，只有你自己知道哪笔是哪笔，账本记的是你申报的动机；**discount 只记门槛数学**——红包、店铺券、店铺满折一律不进 discount 列（否则恒等式复算不平，账本直接 exit 2 拒收）；**账本自锚定**——年化以账本内最大最小日期折算，不用系统时钟，同一本账在任何机器任何时间跑出逐字节一致的结果。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash dd:ignore
python3 cart_line.py judge --subtotal 268 --rule every:300:50 --fill 15 --fill 32
```

## 命令速查

```bash dd:ignore
python3 cart_line.py judge --subtotal 268 --rule every:300:50 --fill 15 --fill 32 --fill 49
                                            # 结算页裁决：凑单线 + 逐件裁决 + 最优组合（NOT_WORTH exit 4）
python3 cart_line.py judge --subtotal 45 --rule full:99:20
                                            # 不带候选：只画线——缺口、白赚区、凑不平判词
python3 cart_line.py audit   orders.tsv            # 账期审计：幻觉差恒等式 + 优惠分层 + 凑单税率（>30% exit 4）
python3 cart_line.py fate    orders.tsv items.tsv  # 命运对账：凑单品垃圾率 vs 计划商品垃圾率
python3 cart_line.py simulate orders.tsv           # 决策回放：逐单对最优重放，四种错误逐一定价（exit 0 镜子）
python3 cart_line.py validate orders.tsv [items.tsv]  # 全部恒等式复算（I1–I6）
```

## 账本格式

订单账 `orders.tsv`，一行一单，手编，UTF-8，`#` 开头是注释：

```
date	order	rule	planned	filler	discount	paid
2026-10-21	O-101	every:300:50	268.0	32.0	50.0	250.0
2026-10-23	O-102	full:99:20	88.0	34.0	20.0	102.0
```

- `rule` ∈ `every:M:D`（每满 M 减 D，可叠加）/ `full:M:D`（满 M 减 D，一次）/ `none`。
- `planned`：没有满减也本来要买的商品原价合计——**filler 是动机不是商品属性**。
- `filler`：为凑单加购的原价合计。
- `discount`：门槛优惠实得合计（只记满减；红包券不进，否则复算不平 exit 2）。
- `paid`：实付。
- 两道自洽闸门（破即 exit 2）：`discount == rule(planned + filler)`；`planned + filler − discount == paid`（残差容 1 分钱）。

命运账 `items.tsv`，一行一件你关心命运的商品：

```
date	order	name	price	filler	fate	fate_date
2026-10-21	O-101	手机支架	32.0	1	idle	2026-12-30
2026-10-21	O-101	洗衣液	89.0	0	used	2027-01-15
```

- `filler` ∈ `0`/`1`；`fate` ∈ `used`（用上了）/ `idle`（闲置）/ `trashed`（处理掉）/ `open`（未表决，fate_date 留空）。
- `order` 必须存在于订单账；settled 行必填 fate_date 且不得早于购买日。
- `fate` 命令要求凑单侧金额覆盖率（Σitems(filler=1).price ÷ Σorders.filler）≥ 50% 才判灯，否则横幅声明样本不完整、判决 withheld。

## 验收标准

| # | 验收标准 | 落在 |
|---|---|---|
| A1 | 订单账 7 列 / 命运账 7 列解析：header 跳过、注释与空行忽略；缺列/坏日期/负金额/坏 rule（d ≥ m 拒收）/空单号 → exit 2 | `OrdersParsingTest`·`ItemsParsingTest` |
| A2 | 双自洽闸门：discount 必须被 rule 复算出（容差 0.005）、paid 必须等于 planned+filler−discount（容差 0.01），破 → exit 2；分厘级舍入尘埃容忍 | `OrderConsistencyTest` |
| A3 | 统一凑单判据：FULL 与 EVERY 共用「缺口 g vs 优惠 d」——g ≤ d FILLABLE（白赚区 [g, d]），g > d NOT_WORTH；四种规则×场景组合钉死 | `RuleMathTest.test_unified_judgment_gap_vs_discount` |
| A4 | NO_NEED 语义：FULL 已过线 / EVERY 余数恰好为 0 → 线为 0，任何 filler 纯亏 | `RuleMathTest`·`JudgeCmdTest` |
| A5 | 浮点尘埃：total 299.999999 仍按单档、300.000000 干净触发下一档 | `RuleMathTest.test_every_float_dust` |
| A6 | judge：候选逐件三态裁决（FILL/FLAT/OVERPAY）、最优单件 = 净赚最大者、最优组合 = 子集和落入白赚区的最小合计（≤ 15 件枚举） | `CandidateTest`·`BestComboTest`·`JudgeCmdTest` |
| A7 | NOT_WORTH → exit 4，判词给出「倒贴下限 g−d」与「什么都不买」的建议；候选全 miss 也 exit 4 | `JudgeCmdTest` |
| A8 | 幻觉差恒等式 discount − net ≡ filler，9 位小数；且对每一单恒有 net ≤ discount（filler ≥ 0，平台口径永不低估） | `IdentityTest` |
| A9 | 优惠分层恒等式：free + earned = discount；现金差 = filler − earned = 实付 − 全裸买；net = free − 现金差（示例账本 ¥300/¥160/¥72/¥228 全钉死） | `IdentityTest` |
| A10 | audit：filler ratio > 30%（`--red-line` 可调）→ exit 4 RED；倒贴单逐单点名并注明病根（凑超线/凑不平/过线手贱）；年化按账本跨度折算并挂「大促节奏 ≠ 全年节奏」横幅 | `AuditCmdTest` |
| A11 | audit THIN：订单 < 5 → exit 3；账期内无任何门槛优惠 → exit 3 | `AuditCmdTest` |
| A12 | fate：open 不进分母（对照账本加一件 open 凑单品，两个率纹丝不动）；凑单 settled < 5 件 → exit 3；金额覆盖率 < 50% → 判决 withheld exit 0；凑单垃圾率 > 50% → exit 4；双口径（金额+件数）与倍数同报告 | `FateCmdTest` |
| A13 | simulate：best 为真最小（分厘网格暴力扫 0–400 元凑单额对拍）；错误五分型 FORCED/GRATUITY/OVERFILLED/UNDERSHOT/MIXED 按示例账本逐单钉死（O-108 的 +¥1.00 在列）；simulate 恒 exit 0（回放是镜子，红线在 audit） | `ReplayTest` |
| A14 | 快照：全部命令输出由 `examples/build_examples.py` 逐字节复现（`--check` 进 CI） | `CliBehaviourTest` |

```bash
python3 -m unittest discover -s cart-line/tests   # 74 tests
```

## demo 快照（examples/）

一个大促季（2026-10-21 → 2026-11-11）8 单：平台战报「已省 ¥460」——

```
== cart-line · order audit ==
planned ¥2709.00 | filler ¥232.00 | discount ¥460.00 | paid ¥2481.00

the platform says:  "you saved ¥460.00"
the ledger says:    you really kept ¥228.00  (net = discount - filler)
the difference ¥232.00 is EXACTLY the filler total — to the last cent,
by algebra: every yuan of filler you paid is a yuan the banner never mentions.

where the discount came from:
  free   ¥300.00  (planned alone already crossed the line — no filler needed)
  earned ¥160.00  (bought with ¥232.00 of fillers -> cash diff +¥72.00)

illusion identity: discount - net - filler = 0.000000000
filler ratio: 50.4% of the discount was eaten by fillers (red line 30.0%)
  -> VERDICT: RED, exit 4 — the promotion is mostly a mirror of your own spending.
```

`judge`（268 元、每满 300−50、候选 15/32/49）：线 = 缺口 32、白赚区 [32, 50]、最大净赚 18；15 元 MISS、32 元恰卡线净赚 18、49 元只剩 1——「最优单件 ¥32」一行终结收银台的犹豫。`judge`（45 元、满 99−20）：缺口 54 > 20，判词「buy nothing extra」exit 4——凑不平的单在数学上早已注定。`simulate`：三层账 **最优 2364 < 全裸买 2409 < 实付 2481**——你的白赚单（O-101/O-104 恰好卡线）是真的，多付的 ¥117 里 ¥68 花在一张注定凑不平的单（O-106）、¥25 花在过线后的手贱（O-107）、¥24 花在两次凑超线（O-102 +23、O-108 +1）。`fate`：凑单品垃圾率 **69.5%** vs 计划商品 **14.1%**——10 件凑单品 6 件在吃灰，吃灰速度是计划购买的 4.9 倍。

## 与近邻点子的边界

- **nav-illusion（净值幻觉）**：同是「平台口径 vs 真实口径」的审计，那边审计基金的收益率幻觉（XIRR − TWR 的行为差），本件审计促销战报的节省幻觉（discount − net ≡ filler 的凑单差）；那边两只收益率钟，这边一条结算页的线。
- **dusty-subs（吃灰订阅，建设中）**：订阅是「持续付费 × 低频使用」，浪费来自健忘，账单自己会说话；本件是「瞬时决策 × 一次购买」，浪费来自冲动，必须靠手编动机建账——没有流水能告诉你哪件是凑单买的。
- **fridge-void（冰箱黑洞）**：同为「结局账本」家族——那边记食材的结局（ate/tossed 五种死因），本件记凑单品的命运（used/idle/trashed 四态）；那边分母是买进总额，这边多出一组对照（计划商品的垃圾率）。
- **cost-per-wear（每穿成本）**：那边把价格摊到使用次数上算利用率；本件不折算使用，只对比两类购买的死亡率——凑单品 4.9 倍的吃灰速度，是动机污染购买的证据，不是单件的利用率。
- **felt-inflation（体感通胀）**：那边价格在涨，你被迫多付；本件价格一分没涨，是你自己为门槛多买了东西——一个是你控制不了的篮子，一个是你控制得住的手。
- **move-line（挪窝线）**：同为「决策线」家族——那边是续租的忍价线（多少涨幅以内值得忍），这边是结算页的凑单线（多少凑单额以内值得加）；那边把搬家麻烦翻译成数字，这边把「顺手买了」翻译成数字。

## License

MIT © 2026
