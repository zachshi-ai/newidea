# 体感通胀 · Felt Inflation

> 官方 CPI 说一切安好，你的小票说不然——差距不是错觉，是篮子不同。
> A zero-dependency CLI that computes your personal inflation from a hand-kept receipts ledger: which items are driving your prices up, whether you have already traded down, and how much basket 100 yuan still buys.

---

## 一句话

新闻说「9 月 CPI 同比 +0.1%」，你超市小票上的总额却比去年贵了一截——想抱怨，手里却只有一句「感觉」，没有任何账。这句差距既不能定位源头，也不能拿去讨论，最后只能变成饭桌上的牢骚。`felt-inflation` 的立场：**官方指数没有说谎，它只是把你的让步吸收掉了**——统计方法会把你换去的便宜货链接进指数，于是 published 的数字永远比体感温柔；而你的体感锚点是「保持原样要花多少」，这个数从来没人替你算。工具从一张手编的小票 TSV 里算出四本账：**指数账**——个人 Laspeyres/Paasche/Fisher 通胀率（累计 + 年化），覆盖率与插补占比全披露，样本太薄就诚实拒答；**红黑榜**——把总通胀精确分解到每个品目（外卖 +4.65pp、咖啡豆 +2.32pp……），点名「谁在拉高你的账单」；**降级账**——基期买的老品目悄悄从购物车里消失、被同品类更便宜的新品目顶替，固定篮子通胀 − 实际账单增速 = **让步差**，你为省钱付出的质量代价第一次有了名字；**购买力账**——把百分比翻译成钱：同样这篮子每月多花多少元、100 元还剩几折。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 每周自己采购、对价格敏感的普通人（独居上班族、家庭采购主力、记账 App 里躺着一堆记录却从不回看的人）；和伴侣争论「东西到底贵没贵」的一方；想吐槽「官方数据和我体感不符」却拿不出证据的人。 |
| **场景** | 月底翻账单发现食品支出又涨了；新闻 CPI 和自己的体感对不上；考虑「要不要把每周外卖砍两次」时想知道外卖到底涨了多少；一年下来想复盘「钱到底被什么吃掉了」。 |
| **问题** | **通胀是个宏观平均数，而你的账单是具体的**：① 官方篮子（住房、汽车、教育的权重）不等于你的篮子，「平均」对你没有语义；② 「东西越来越贵」停留在体感——说不出是哪几个品目在拉高账单，也就无法针对性替换；③ 你可能已经在默默降级（换便宜牌子、砍量），官方的链式方法把这种替代吸收进指数，于是「统计」与「体感」的裂缝结构性存在却无处对账；④ 通胀率是百分比不是钱——没人告诉你「同样这个月的一篮子，今年多花多少元」，百分比不会进预算。 |
| **价值与意义** | 1) **指数账**：`rate` 从小票账本算出个人 Laspeyres（固定篮子=体感锚点）、Paasche、Fisher 三个累计通胀与年化（样例：17 个月 +12.88%，年化 +8.93%，超 5% 红线 exit 4）；覆盖率、未覆盖品目、插补价格全披露——样本太薄时 exit 3 **拒绝下结论**，体感第一次有了一个诚实的数字。<br>2) **红黑榜**：`board` 把总通胀分解到品目（贡献 = Δp × 基期数量份额，加总恒等于总通胀，恒等式有测试守着）：外卖 +4.65pp、咖啡豆 +2.32pp，top-2 集中度 54.2%——「一半的体感通胀来自两样东西」从抱怨变成审计结论，降价品目标 cooling。<br>3) **降级账**：`drift` 找出基期买、近三月消失的老品目，与同品类更便宜的新品目配对（样例：¥45 的洗发水 A 悄悄被 ¥22.9 的洗发水 B 顶替，−49.11%）；**让步差** = 固定篮子 +12.88% − 实际账单 +7.60% = +5.28pp——「我明明没有乱花钱，为什么感觉变穷了」的答案：你已经让步了 5.28 个点。<br>4) **购买力账**：`power` 把指数翻译成预算语言：同样这篮子每月多花 ¥110.80、每年 ¥1,329.60；2026 年的 100 元只买得动 2025 年 88.59 元的东西。<br>5) **零依赖 + 纯本地**：Python 3.8 标准库，小票是消费隐私，一行都不出电脑。 |

---

## 核心思想：你的通胀，三把尺子

通胀测量的全部分歧都来自**篮子选在哪个时刻**。工具的三条诚实原则：

| 概念 | 规则 | 回答的问题 |
|---|---|---|
| **固定篮子（Laspeyres）** | 基期月买过的品目 × 基期数量做权重，价格换算到对比期——「保持原样的生活」现在的代价 | 「我的体感锚点：什么都没变，我要多花多少？」 |
| **让步差** | 固定篮子通胀 − 实际账单增速。官方统计用链式方法把你的替代吸收掉，这里反着来：把「你已经做的让步」从账单里拎出来示众 | 「账单没涨多少 vs 篮子涨了很多，中间的差去哪了？」 |
| **覆盖率门** | 基期品目在基期之后**再也没出现过** = uncovered，剔除但点名披露；对比期没买到的用最近一次价格 carry-forward 并计数（imputed）；覆盖率 < 60% 挂 THIN 横幅，< 50% 或篮子 < 5 品目直接 exit 3 **拒绝下结论** | 「这个指数背后有多少真价格、多少陈旧价格？」 |
| **红线** | 年化 ≥ `--red-line`（默认 5%）→ exit 4，报告点名「官方平均不是你的平均」；可进脚本与 CI | 「我的价格涨得有多快，要不要当回事？」 |
| **品目贡献分解** | contribution_i = (p₁−p₀)×q₀ / Σp₀q₀，加总恒等于总通胀（分解恒等式，测试钉到 9 位小数） | 「谁在拉高我的账单？是一两个惯犯还是全面开花？」 |
| **配对规则（drift）** | 老品目消失 → 只在同品类、更便宜的新品目里找替补，取价格最接近者；跨品类永不配对 | 「我换去的那个便宜货，是它吗？」 |

三条边界刻在实现里：**品目粒度由你定义**——同一商品跨月要用同一个 slug，换了规格就换名字（指数只认名字）；**账单增速含量变**——`drift` 的实际账单增速混入了买多买少，让步差是方向性证据，不是纯净的价格效应（METHODOLOGY 里写明了边界）；**单月基期是脆的**——赶上促销月做基期会永久扭曲篮子，先用 `months` 看密度再选。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash dd:ignore
python3 felt_inflation.py rate ledger.tsv --base 2025-01 --period 2026-06
```

## 命令速查

```bash dd:ignore
python3 felt_inflation.py rate   ledger.tsv                     # 个人通胀：超红线 exit 4，太薄 exit 3
python3 felt_inflation.py rate   ledger.tsv --red-line 8        # 自定义红线
python3 felt_inflation.py board  ledger.tsv --top 8             # 涨价红黑榜：谁在拉高账单
python3 felt_inflation.py drift  ledger.tsv --window 3          # 降级账：让步差 + 配对
python3 felt_inflation.py power  ledger.tsv --cash 500          # 购买力：500 元还买得动多少
python3 felt_inflation.py months ledger.tsv                     # 密度图：挑一个记满的月做基期
python3 felt_inflation.py rate   ledger.tsv --format json       # 机读
```

## 账本格式

TSV，一行一次采购，`price` 是**这一行的总价**（单价 = price ÷ qty）：

```
date	item	category	qty	price	store
2025-01-03	eggs-30pc	grocery	2	50.00	Freshmart
2025-01-09	coffee-beans-250g	grocery	2	96.00	Roastery
```

`#` 开头是注释；畸形行跳过并计数，绝不炸掉整本账。

## 示例账本里藏着一个完整的故事

`examples/ledger.tsv` 是林晓（上海独居上班族）2025-01 → 2026-06 的 18 个月小票：11 个基期品目、2 个新人。四本账连起来读：

- `rate`：固定篮子 **+12.88%**（17 个月），年化 **+8.93%**，超 5% 红线 → exit 4；2 个品目靠 carry-forward 插补（洗发水 A 已消失、洗洁精双月才买），全部披露
- `board`：**外卖 +4.65pp、咖啡豆 +2.32pp**，top-2 集中度 54.2%——一半的体感通胀来自两样东西；地铁、大米、洗洁精零贡献
- `drift`：¥45 的洗发水 A 被 ¥22.9 的洗发水 B 顶替（−49.11%）；账单实际只涨 **+7.60%**（外卖从 10 次砍到 8 次），让步差 **+5.28pp**——「账单没怎么涨」的真相是**你已经在让步**
- `power`：同样这篮子每月多花 **¥110.80**、每年 **¥1,329.60**；100 元的购买力只剩 **88.59 元**

## 验收标准（全部转为自动化测试）

| # | 验收标准 | 测试 |
|---|---|---|
| 1 | 黄金账本上 Laspeyres 累计 +13.89%、年化 +68.24% 与手算一致（den 180 → num 205，L⁴ 年化） | `GoldenIndexTest::test_laspeyres_cumulative_and_annualized` |
| 2 | Paasche +15.38%（150/130）、Fisher +14.63%（√(L·P)）与手算一致 | `GoldenIndexTest::test_paasche_and_fisher` |
| 3 | 贡献分解恒等式：各品目贡献之和 == 总通胀（钉到 9 位小数），单项值精确（alpha/beta 5.5556pp、gamma 2.7778pp） | `GoldenIndexTest::test_contribution_decomposition_identity` |
| 4 | uncovered 品目剔除且点名披露；carry-forward 插补按品目计数披露 | `GoldenIndexTest::test_coverage_imputed_uncovered_disclosed` |
| 5 | 基期篮子 < 5 品目 → exit 3 + REFUSED（拒绝下结论） | `GateTest::test_basket_under_five_refused_exit_3` |
| 6 | 覆盖率 < 50% → exit 3（coverage 40% 场景） | `GateTest::test_coverage_under_fifty_refused_exit_3` |
| 7 | 覆盖率 50–60% → THIN 横幅 + 仍出结论（57.1% 场景） | `GateTest::test_thin_banner_between_fifty_and_sixty` |
| 8 | 退出码语义：0 正常 / 2 用法错 / 3 太薄拒答 / 4 超红线 | `GateTest::test_exit_codes_documented_values` |
| 9 | 畸形行（列数错、qty≤0、price≤0、坏日期、空品目）跳过并计数，不炸 | `ParsingTest::test_malformed_rows_counted_not_fatal` |
| 10 | 注释、表头、空行、按日期排序、同月多行单价加权混合 | `ParsingTest` 四项 |
| 11 | 零依赖：源码 import 仅限标准库白名单 | `ParsingTest::test_zero_dependency_stdlib_only` |
| 12 | period ≤ base、base/period 越界、坏月份格式 → exit 2；账本文件缺失 → exit 2 | `UsageTest` 六项 |
| 13 | 年化 ≥ 红线（默认 5%）→ exit 4；自定义红线放宽后 → exit 0 | `GoldenIndexTest` 两项 |
| 14 | 降价品目贡献为负、出现在 cooling 一侧（−2.08pp） | `BoardSidesTest::test_price_drop_shows_on_cooling_side` |
| 15 | drift 配对：只配同品类、更便宜、价格最接近的新品目；跨品类永不配对；abandoned 披露最后价格 | `DriftTest::test_pair_picks_closest_same_category_newcomer` 等 |
| 16 | 让步差方向语义：正 = 「你已经做出的让步」，负 = 「买得更多更好，无降级」 | `DriftTest::test_positive_concession_gap_trade_down` / `test_negative_gap_means_no_downgrade` |
| 17 | power 三值（月差 ¥25、年差 ¥300、百元购买力 ¥87.80）与手算一致；JSON 字段齐全且 exit code 正确 | `GoldenIndexTest::test_power_translates_into_money`、`JsonAndMonthsTest` |
| 18 | `months` 密度图文本与 JSON 两种形态正确 | `JsonAndMonthsTest::test_months_command_lists_density` 等 |
| 19 | 示例账本故事成立：exit 4、+12.88%/+8.93%、外卖 driver #1（+4.65pp）、top-2 过半、trade-down −49.11%、月差 ¥110.80 | `DemoLedgerTest` 四项 |
| 20 | dogfood：`examples/build_examples.py --check` 逐字节重建账本与 4 份报告 | `DogfoodTest::test_examples_byte_sync` |

## 与仓库其他点子的边界

仓库里已有的是**消费决策**工具：cost-per-wear 算单件衣服的利用率、repair-ledger 算修与换、dusty-subs 类审计订阅浪费、life-tag 把标价换算成生命小时；slow-leak 读的是**物理用量**（漏电漏水漏气），本件读的是**价格**。本件不回答「该不该买」，它回答「**你买的东西正在以多快的速度变贵、谁在推、你已经为此让了多少步**」——对象是价格水平的时间序列，工具是指数统计，数据源是你自己的小票。两者互补：先用本件看清涨价的源头，再用那些工具决定砍掉什么。

## License

MIT © 2026
