# 每穿成本 · Cost Per Wear

> 衣服的真实价格不在吊牌上，在衣柜的出勤记录里——吊牌价 ÷ 穿的次数，才是它真正收你的钱。
> A zero-dependency CLI that keeps the ledger fashion never does: cost-per-wear ranking, the graveyard of never-worn clothes (and the capital sleeping in it), category hoarding, a season coverage matrix, and a shopping simulator that tells your next buy apart from your 8th white tee.

---

## 一句话

一件衣服的账要分两本记：购买那天记一次吊牌价，之后每次穿着摊薄一点——真实价格 = 吊牌价 ÷ 穿的次数。但没人算这本账：购买决策在试衣间 3 分钟内完成，账单只显示第一本。于是直觉全被吊牌价绑架——**贵而常穿的风衣被骂「乱花钱」，便宜而从不穿的快时尚在衣柜里吃灰**；「没衣服穿」和「塞爆」并存，因为缺口是结构性的（没有能穿的外套），采购却是冲动性的（第 8 件白 T）。`cost-per-wear` 把第二本账记出来：CPW 排行、衣柜坟场（含沉睡资金）、品类堆积区、品类×季节覆盖矩阵，再加一个**剁手模拟器**——想买的清单逐条判定「填补缺口」还是「喂养堆积」。扔与不扔仍是你的决定；但至少下次剁手前，你知道自己有一件 1599 的羽绒服从来没穿过。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 「衣柜塞爆却没衣服穿」的上班族；换季整理衣柜的人；双十一/黑五购物车躺着十个「要不要」的人；想搞 capsule wardrobe 却不知道从哪砍起的人。 |
| **场景** | 换季清点（一年两次，每次 15 分钟）；下单前把购物车喂给模拟器；年度盘点「今年衣柜里的钱有多少在睡觉」；给朋友的穿搭建议需要证据（「你不是缺衣服，是缺外套」）。 |
| **问题** | **衣服的第二本账没人记**：① 真实价格 = 吊牌价÷穿着次数，但购买决策只看吊牌价，直觉里 1200 的风衣「贵」、79 的白 T「便宜」——穿 96 次之后这笔账正好反过来；② 坟场不可见：从没穿过的衣服安静地挂在原处，没人统计衣柜里有多少钱在睡觉；③ 堆积不可见：第 7 件白 T 是逐次买入的，每次单看都「不贵、会穿」；④ 缺口与堆积不同时可见： coverage 是结构问题（品类×季节），采购是冲动问题（单件），两套坐标系从没对过。 |
| **价值与意义** | 1) **直觉反转有数字**：CPW 排行让「贵=浪费」的直觉现出原形——样例衣柜里最值的是 39 块的拖鞋（0.65/穿），最贵的是 699 块只穿过一次的婚礼衬衫。<br>2) **沉睡资金**：坟场清单 + 金额合计——「衣柜里 49.6% 的钱在睡觉」比「别乱买」有力得多。<br>3) **堆积区点名**：同品类数量触顶的品类被直接列出（白T ×7、袜子 ×6、连衣裙 ×4）。<br>4) **覆盖矩阵**：品类×季节的事实陈列，让「没衣服穿」落到具体空格上。<br>5) **剁手模拟器**：把购物车逐条判为填补缺口/堆积区/孤儿否决——第 8 件白 T 在下单前就被拦下。<br>6) **诚实条款**：工具只记「买」与「穿」两本账，不评判审美，不建议扔什么——处置永远是人的决定。<br>7) **零依赖 + 纯本地**：Python 3.8 标准库，清单不出你的电脑。 |

---

## 核心思想：一次购买，次次穿着——把第二本账记出来

| 账本 | 算什么 | 为什么值得单独记 |
|---|---|---|
| **CPW 排行** | 吊牌价 ÷ 穿着次数，降序 = 「最贵的衣服」；升序前五 = 「真正的便宜货」 | 0 次穿的衣服没有 CPW（未定型，返回 ∞）——它们进坟场，不进榜单 |
| **衣柜坟场** | 从未穿（购入 ≥180 天，豁免期保护新衣）+ 长眠（上次穿 ≥365 天）；合计**沉睡资金** | 吃灰的衣服不会被提起；金额合计让「吃灰」第一次有了价格 |
| **品类堆积区** | 同品类数量 ≥4（可调）→ 点名 + 该品类已投入合计 | 第 8 件白 T 的问题不是贵，是重复——单看每件都不贵 |
| **覆盖矩阵** | 品类 × 四季的数量陈列（all 归四季） | 「没衣服穿」的真相是结构性缺口；矩阵只陈列事实，不设「应该几件」的基线——基线因人而异 |
| **剁手模拟器** | 想买清单逐条过两道否决：堆积否决（该品类 ≥阈值 → 「第 N 件」）→ 孤儿否决（该品类挂着从未穿的 → 「先穿它」） | 下单前 10 秒，把冲动换成一次对账 |

三条诚实条款刻在实现里：**0 次 = 未定型**——从没穿的衣服没有「每次成本」，只有「从未开始」；**豁免期保护新衣**——买来准备下季穿没有错，180 天内不算孤儿；**不建议扔**——工具提供谁在吃灰的证据，「扔」永远是人的决定。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

## 命令速查

```bash dd:ignore
python3 cost_per_wear.py audit examples/wardrobe.csv                      # 每穿成本账本
python3 cost_per_wear.py audit examples/wardrobe.csv --format json        # 机读
python3 cost_per_wear.py audit examples/wardrobe.csv --orphan-alert 0.25  # 门禁：沉睡占比超 25% exit 4
python3 cost_per_wear.py audit examples/wardrobe.csv --today 2026-09-04   # 钉死日期，可复现
python3 cost_per_wear.py plan examples/wardrobe.csv --want "外套:899,白T:79"   # 剁手模拟器
python3 cost_per_wear.py plan examples/wardrobe.csv --want "外套:899" --strict # 有 REJECT 就 exit 4
python3 cost_per_wear.py validate examples/wardrobe.csv                   # 格式体检
```

## 一个真实样例

32 件单品、总投入 9215 的合成衣柜（[`examples/wardrobe.csv`](examples/wardrobe.csv)，[`examples/build_examples.py`](examples/build_examples.py) 可从零重建）。[`examples/sample-audit.txt`](examples/sample-audit.txt) 的判决（节选）：

```text dd:ignore
-- Cost Per Wear · 每穿成本
   32 items · 0 skipped · 总投入 9215.00 · today 2026-09-04

   最贵的衣服（吊牌价 ÷ 穿的次数）：
   name                     category       price  wears       cpw
   婚礼衬衫                 衬衫          699.00      1    699.00
   连衣裙 素色              连衣裙        399.00      1    399.00
   ...
   风衣 LaMode              外套         1200.00     96     12.50

   真正的便宜货（cpw 最低）：
     白袜A                            0.30/穿
     拖鞋 家用                        0.65/穿

   衣柜坟场：沉睡资金 4572.00（占总投入 49.6%）
     never worn  羽绒服 打折购入             1599.00  460d
     never worn  连衣裙 碎花                  399.00  538d
     ...
     asleep      婚礼衬衫                     699.00  last 2025-06-01

   品类堆积区（同品类数量触顶）：
     白T            x7  已投入 553.00
     袜子           x6  已投入 90.00
     连衣裙         x4  已投入 1596.00
```

读法：1200 的风衣穿着 96 次之后每穿只要 12.5——它是衣柜里第二便宜的 item，而当年买它时你嫌贵；婚礼衬衫只穿了一次，每穿 699，还会被长眠线抓走（上次穿已是 460 天前）。坟场里最大的一笔是打折买的羽绒服：1599、460 天、0 次——**折扣价买下的从未使用，是全价买下的吃灰**。把这个衣柜喂给剁手模拟器（[`examples/sample-plan.txt`](examples/sample-plan.txt)）：

```text dd:ignore
-- Cost Per Wear · 剁手模拟器
   ✓ ACCEPT  外套              899.00  填补缺口（该品类现有 1 件）
   ✗ REJECT  白T                79.00  第 8 件（该品类已有 7 件，堆积区）
   ✗ REJECT  羽绒服           1299.00  该品类有从未穿过的「羽绒服 打折购入」（460 天）——先穿它
   ✓ ACCEPT  冬靴              599.00  填补缺口（该品类现有 0 件）

   2 fill a gap, 2 feed a pile.
```

「先穿它」三个字就是孤儿否决的全部意义：你的购物车里躺着的可能正是坟场里那件的同款新色。

## dogfood：合成埋点，不是玩具跑通

真实衣柜清单属于个人隐私，不该上传仓库，所以本项目的 dogfood 是**合成埋点**：`examples/build_examples.py` 用钉死的日期构造 ground truth（32 件、总投入 9215.00、4 件孤儿、2 件豁免期内新衣、4 件长眠、3 个堆积区、沉睡资金 4572.00 = 49.6%），验收测试要求工具**精确恢复**每一个数——坟场名单零多报零漏报（豁免期的新衣必须不被误抓）、堆积区品类与数量精确、CPW 榜首对齐、模拟器四条判定逐条核对。埋点重建证明的是工具真的在算账，不是打印一份看起来像账本的东西。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_costperwear.py`](tests/test_costperwear.py)，49 个用例，`unittest`，无网络无外部依赖）：

```bash
python3 -m unittest discover -s cost-per-wear/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 解析：中英列名、季节连写与别名（春秋/winter/全年）、日期格式+时间后缀、gbk、坏行与负数计数、可选列缺失、错误退出 | `ParseTests`（9 例） |
| CPW 数学：基本摊销、0 次 = 未定型、舍入 | `CpwTests`（3 例） |
| 坟场：180 天豁免期、无购买日期按孤儿处理、豁免期可调、长眠 365 天线、矛盾数据不重复计钱、占比数学 | `GraveyardTests`（6 例） |
| 榜单：真实价格降序只收穿过的、便宜货升序、15 条截断 | `BoardTests`（3 例） |
| 堆积区：阈值与投入合计、低于阈值不报、阈值可调 | `HoardTests`（3 例） |
| 覆盖矩阵：all 归四季、连写季节分摊 | `CoverageTests`（2 例） |
| 模拟器：堆积否决、孤儿否决（品类再小也拦）、填补缺口放行、豁免期内新衣不否决、--want 解析（全角/半角/错误） | `PlanTests`（5 例） |
| ground truth：32 件 9215.00、坟场与长眠名单精确、豁免期不误抓、堆积区、双榜榜首、覆盖矩阵、四条判定 | `ScenarioTests`（8 例） |
| CLI：text/json、--today 改判、--strict 门禁 exit 4、validate、--orphan-alert 门禁、退出码 0/2/3 | `CliTests`（9 例） |
| 样例同步：衣柜清单与两份报告可从零重建且逐字节一致 | `SyncTests`（1 例） |

## 项目结构

```
cost-per-wear/
├── cost_per_wear.py
├── tests/test_costperwear.py
├── examples/build_examples.py
├── examples/wardrobe.csv
├── examples/sample-audit.txt
├── examples/sample-plan.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
