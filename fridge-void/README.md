# 冰箱黑洞 · Fridge Void

> 浪费是一个家里唯一不被记账的经济活动——账单记下了每一次买进，没有任何账本记下结局。
> A zero-dependency CLI that completes the grocery ledger with outcomes: how much of what you buy never gets eaten, which categories are the black holes, why each thing died, and what your food really costs per yuan actually swallowed.

---

## 一句话

月底翻账单，只有一句「这个月买菜花了一千八」；永远没有另一句「其中两百多块直接进了垃圾桶」——那袋蔫掉的青菜、过期一周的酸奶、冰箱最深处发现时已经变质的半根萝卜，在 0.5 秒的内疚之后被盖上垃圾桶盖子，从统计上蒸发。买进被记账（买菜钱躺在每一张账单里），结局从不被记账（垃圾桶不开发票），于是「少浪费点」永远是一句无法对账的美德口号。`fridge-void` 的立场：**黑洞不可怕，不可见的黑洞才可怕**。工具把「结局」补进账本——每份食材记一行（买进日期/品名/品类/数量/金额/结局/死因），确定性算出五本账：**浪费率**（金额与重量双口径，年化成「你每年扔掉多少钱」）；**品类红黑榜**（每个品类对总浪费率的贡献分解，加总恒等于总浪费率——「一半的浪费来自绿叶菜」从内疚变成审计结论）；**死因结构**（放坏/过期/不爱吃/煮多了/忘在深处，五种死因对应五种对策，死因错了药就不对）；**浪费税**（吃进嘴的每 1 元菜实际花了 ¥1.31——你自己发明的个人通胀，CPI 对此一无所知）；**采购过闸**（购物车逐条过你自己的浪费史：试过两次扔过两次的燕麦奶在下单前就被自己的黑名单拦下）。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 自己采购做饭的都市人——独居上班族、小家庭掌勺的那个人；对「买菜花钱」有数、对「买菜扔钱」没数的人；试过「这周少浪费点」的决议却没有任何账本来执行决议的人。 |
| **场景** | 周末清冰箱，清出一袋蔫菜和一盒过期酸奶；打开采购 App 下单，顺手又加了一把菠菜；健康野心发作买了燕麦奶/羽衣甘蓝，喝一口就再没动过；月底看食品支出觉得「也没吃什么啊」。 |
| **问题** | **结局不可见**：账本只记买进不记结局，浪费在统计上蒸发——你知道花了多少，不知道其中多少进了垃圾桶，更不知道是哪些东西、因为什么原因进去的。于是 ①「浪费多不多」全凭心情，没有一个可以拿去讨论的率；② 浪费混在品类里，你不知道自己的黑洞是绿叶菜还是乳品，钱持续往同一个洞里掉；③ 对策无从谈起——「买多了」要减量、「忘了吃」要整理冰箱、「不爱吃」要进黑名单，三种病一种药只会全部治坏；④ 价格是骗你的——标价假装你吃到的每一口都是你付了钱的那一口，真实单价从没人算过。 |
| **价值与意义** | 1) **浪费率账**：`ledger` 从手编 TSV 算出金额与重量双口径浪费率、结局分布（ate/gave/tossed——**送人是完成使命，不算浪费**）、年化黑洞（样例：12 周 62 批次，扔掉 23.8%，按此节奏一年 ¥833.73 进垃圾桶；红线 15%，超线 exit 4）；样本 < 20 条目直接 exit 3 **拒绝下结论**——浪费第一次有了可以拿去讨论的数字。<br>2) **品类红黑榜**：`board` 把总浪费率分解到品类（贡献 = 品类扔掉金额 ÷ 全部 settled 金额，加总恒等于总浪费率，恒等式有测试钉到 9 位小数）：样例里绿叶菜 66.4%（买 10 块扔 6.6）、主食 76.5%、乳品 100%——「鸡蛋和肉都好好吃完了，黑洞全在绿叶菜和煮多的米饭上」这个结构性事实，不记账永远不会知道。<br>3) **死因结构**：`cause` 把扔掉的每一笔归因到五种死因——spoiled 买多了（量的问题）、expired 过期没动（动能问题）、rejected 试过不爱吃（黑名单问题）、leftover 煮多了（手的问题）、forgot 忘在冰箱深处（可见性问题）：样例 spoiled 41.8% + rejected 34.3% = 76%——减量和黑名单两件事就能覆盖四分之三的浪费，**死因决定对策，对策对不上死因的自律都是白受罪**。<br>4) **浪费税**：`tax` 把浪费率翻译成价格语言：浪费率 r 之下，吃进嘴的每 1 元实际花了 1/(1−r) 元——样例整体 ¥1.313（+31.3%），绿叶菜 ¥2.97、主食 ¥4.25、乳品 100% 浪费率直接判 **INFINITE**（你买的每一点乳品都进了垃圾桶，它对你的真实单价是无穷大）。这是你自己发明的个人通胀，与 CPI 无关，官方永远不会替你统计。<br>5) **在库盘点与采购过闸**：`pantry` 把还没结局的食材按在库天数排排队，超过 7 天挂 DUE 灯（样例：冬瓜已经在架上躺了 19 天）；`plan` 让购物车逐条过你自己的浪费史——rejected 黑名单是硬闸（试过两次扔过两次的燕麦奶，第三盒在下单前被拦下 exit 4），重灾区品类挂横幅，采购总额超历史周均 1.5 倍挂「冰箱不是保险库」横幅；**账本只拒绝继续沉默，买不买仍是人的决定**。<br>6) **零依赖 + 纯本地**：Python 3.8 标准库，冰箱是家庭的隐私，一行不出电脑。 |

---

## 核心思想：买进只是借款，结局才是决算

食品账本和别的账本的根本区别：**每一笔买进都悬而未决，直到结局发生**。工具的四条诚实原则：

| 概念 | 规则 | 回答的问题 |
|---|---|---|
| **结局三分** | 每份食材的结局 ∈ ate（吃掉）/ gave（送出）/ tossed（扔掉，须注明五种死因之一）；open 表示还在架上——**「吃掉」和「送出」都是使命完成，只有 tossed 进浪费分子** | 「这份食物最后怎样了？」 |
| **分母纪律** | 浪费率 = tossed ÷ (ate + gave + tossed)；open 不进分母——它还没表决，提前把它算成浪费是对它的冤枉 | 「这个率的分母里有什么？」 |
| **贡献恒等式** | 品类贡献 = 品类 tossed ÷ 全部 settled，加总恒等于总浪费率（分解恒等式，测试钉到 9 位小数）；死因占比加总恒等于 1 | 「黑洞在哪个品类、死于什么原因？」 |
| **浪费税** | 浪费率 r 的品类里，吃进嘴每 1 元的真实成本 = 1/(1−r)；r = 100% 的品类直接判 INFINITE | 「标价 6 块的菠菜，到我嘴边是几块？」 |
| **红线与门槛** | 浪费率 ≥ `--red-line`（默认 15%）→ exit 4；条目 < 20 或没有 settled 金额 → exit 3 拒绝下结论；数据坏行 → exit 2——**宁可沉默不出报告，不出没有证据的报告** | 「这个结论背后有多少证据？」 |

三条边界刻在实现里：**手编意味着诚实**——结局是你自己记的，账本不猜「这袋菠菜大概吃了一半」；**品类粒度由你定义**——「绿叶菜」和「乳品」是你的分类，工具只对分类负责；**anchor 是账本自己的今天**——`pantry` 以账本内最大日期为「现在」，同一本账任何机器任何时间跑出的结果逐字节一致。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash dd:ignore
python3 fridge_void.py ledger ledger.tsv
```

## 命令速查

```bash dd:ignore
python3 fridge_void.py ledger ledger.tsv                     # 全账本体检：浪费率+结局+年化，超红线 exit 4，太薄 exit 3
python3 fridge_void.py ledger ledger.tsv --red-line 0.10     # 自定义红线
python3 fridge_void.py board ledger.tsv --top 8              # 品类红黑榜：黑洞在哪个品类
python3 fridge_void.py cause ledger.tsv                      # 死因结构：量的问题还是黑名单问题
python3 fridge_void.py tax ledger.tsv                        # 浪费税：吃进嘴的每 1 元实际花了几块
python3 fridge_void.py pantry ledger.tsv                     # 在库盘点：谁快烂了（DUE 灯）
python3 fridge_void.py item  ledger.tsv 燕麦奶                # 单品全史：买过几次、扔过几次
python3 fridge_void.py plan  ledger.tsv cart.tsv             # 采购过闸：购物车过你自己的浪费史
```

## 账本格式

TSV，一行一份食材批次，手编，UTF-8，`#` 开头是注释：

```
bought	name	category	qty	unit	cost	outcome	outcome_date	cause
2026-06-01	菠菜	绿叶菜	400	g	6.5	tossed	2026-06-06	forgot
2026-06-01	鸡蛋	蛋奶	750	g	21.0	ate	2026-06-14	
2026-06-12	鲈鱼	水产	500	g	32.0	gave	2026-06-15	
2026-08-24	牛奶	蛋奶	1000	ml	13.0	open			
```

- `bought`/`outcome_date`：YYYY-MM-DD；结局不得早于买进。
- `outcome` ∈ `ate` / `gave` / `tossed` / `open`；`open` 行结局两列留空。
- `cause`（仅 tossed 行必填）∈ `spoiled`（放坏）/ `expired`（过期没动）/ `rejected`（试过不爱吃）/ `leftover`（煮多了）/ `forgot`（忘在深处）。
- `unit` 任意文本；重量口径只认 `g`/`kg`，其余单位不参与重量口径（披露覆盖率）。

购物车 `cart.tsv`（给 `plan` 用）：`name	category	qty	unit	cost`。

## 验收标准

| # | 验收标准 | 落在 |
|---|---|---|
| A1 | TSV 解析：9 列、header 行跳过、注释与空行忽略；缺列/坏日期/坏数字/负金额/空品名 → exit 2 | `ParsingTest` |
| A2 | 结局校验：outcome 四值枚举；open 行不得带结局日期；settled 行必须带；结局早于买进 → exit 2 | `ParsingTest` |
| A3 | 死因校验：tossed 必填五死因之一；非 tossed 行带死因 → exit 2 | `ParsingTest` |
| A4 | 浪费率分母 = ate+gave+tossed；gave 不算浪费；open 不进分母 | `AccountingTest` |
| A5 | 重量口径只认 g/kg（ml/个不参与），披露覆盖率 | `ParsingTest`·`cmd_ledger` |
| A6 | 品类贡献加总恒等于总浪费率，9 位小数 | `AccountingTest` |
| A7 | 死因占比加总恒等于 1，9 位小数 | `AccountingTest` |
| A8 | 浪费税 = 1/(1−r)；r=100% 判 INFINITE 不崩 | `AccountingTest`·`TaxTest` |
| A9 | 年化按账本跨度折算（最短 1 周）；周均买进同口径 | `AccountingTest` |
| A10 | exit 3：条目 < 20 / 无 settled 金额 / 查无此单品 / 无死因可示 | `ExitCodeTest` 等 |
| A11 | exit 4：浪费率超红线（默认 15%，可调）；品类红黑榜有 disaster 区 | `ExitCodeTest`·`BoardTest` |
| A12 | pantry 以账本最大日期为锚点；超 7 天挂 DUE → exit 4；全 settled → 空清单 | `PantryTest` |
| A13 | item 按归一名聚合（大小写/空白不敏感）；给出主导死因 | `ItemTest` |
| A14 | plan：rejected 精确品名 → BLOCKED exit 4；重灾区品类 → WARNING 不拦 exit；cart 总额 > 1.5× 周均买进 → WARNING；空 cart → exit 2 | `PlanTest` |
| A15 | 样例账本与全部报告快照可由 `examples/build_examples.py` 逐字节复现（`--check` 进 CI） | `ExamplesSync`（`--check`） |

```bash
python3 -m unittest discover -s fridge-void/tests   # 49 tests
```

## demo 快照（examples/）

12 周独居账本：62 批次、买进 ¥876.40——

```
== fridge-void · full audit ==
ate    ¥582.80  72.2%
gave   ¥32.00  4.0%  (a gift is not waste)
tossed ¥192.40  23.8%  <-- the void
waste rate 23.8% (red line 15.0%)  ->  VERDICT: RED, exit 4
every yuan you actually eat cost you 1.313 yuan at the till (+31.3%)
at this pace you throw ¥833.73 of food into the bin every year
```

`board`：绿叶菜 66.4%（disaster）、主食 76.5%、乳品 100%；肉禽 0.0%——「肉都好好吃了，黑洞全在绿叶菜、米饭和健康野心上」。`cause`：spoiled 41.8% + rejected 34.3% = 76%，减量与黑名单覆盖四分之三。`tax`：绿叶菜吃到嘴每 1 元真实 ¥2.97，乳品 INFINITE。`plan`：燕麦奶第三盒被自己的黑名单 BLOCKED，菠菜挂 disaster 横幅，鸡腿放行。

## 与近邻点子的边界

- **expiry-cliff（到期悬崖）**：管「凭证的失效提前量」——护照/保单/域名是一次性到期事件；本件管「食材的结局对账」，保质期只是五种死因之一的背景，核心是浪费率与死因结构。
- **dusty-subs（吃灰订阅，建设中）**：订阅是「持续付费 × 低频使用」，数据从银行流水扫描；本件是「离散购入 × 一次性消耗」，结局必须一行行手工记——没有流水能告诉你那把菠菜最后怎样了。
- **cost-per-wear（每穿成本）**：耐用品利用率 = 价格 ÷ 使用次数；本件是消耗品损耗率 = 扔掉 ÷ 结局，分母是结局分布不是使用次数。
- **felt-inflation（体感通胀）**：价格在涨你才要多付；本件里价格一分没涨，是你自己把买到的食物扔掉了——浪费税是个人行为税，CPI 对此一无所知。
- **slow-leak（暗漏）**：同为「账本缺口」家族——slow-leak 补的是「用量聚合抹平了泄漏线索」，本件补的是「账本只记买进、从不记结局」；一个看三表曲线，一个看食材结局。
- **left-behind（漏带时刻）**：「错题本喂养下一张清单」的机制同源，但域完全不同——那边是出行装箱错误，这边是食材结局；这边多出死因结构与浪费税两层。

## License

MIT © 2026
