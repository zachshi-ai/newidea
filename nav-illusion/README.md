# 净值幻觉 · NAV Illusion

> 基金的净值是你的现金流泼上去的一面墙，App 给你看墙的增长率，从不给你看你的手。
> A zero-dependency CLI that audits the gap between the fund you bought and the investor who bought it: the NAV page prints the fund's time-weighted return, your money-weighted XIRR is what your chasing-and-panicking actually earned, and the difference between them is a tuition bill nobody has ever itemized for you.

---

## 一句话

收益率有两种，基金 App 只给你看第一种。**时间加权收益 TWR**（净值首尾增长率）衡量这只基金赚不赚钱——它假装你的钱一直在场；**货币加权收益 XIRR**（解你全部申赎现金流的内部收益率）衡量你的钱实际赚了多少——它记得你每一笔追高与割肉。两者的差就是**行为差**：2024 年那只净值 +35% 的基金，追涨杀跌的持有者真实年化可能只有 5%，因为你下跌前的重仓、坑底的恐慌赎回、反弹后的 FOMO 回补，全都记在 XIRR 里、全都缺席于净值页。`nav-illusion` 从两本可手编的账（申赎现金流 + 复权净值序列）算出四本账：**对账账**——份额账本逐笔复算、期末市值钉死；**收益率账**——XIRR 二分求解、TWR 首尾年化、行为差一步到位；**行为账**——每笔申赎的历史百分位（金额加权平均 >0.65 即追涨型）、回撤 >10% 期间的割肉清单及其后 90 天的错过涨幅；**反事实账**——同样的钱期初一次买入 vs 月定投 vs 你的实际操作，三口锅摆在一起，学费第一次有了明细。它不预测净值、不建议买卖：它只回答一个从没有人替你算过的问题——**这只基金赚的钱，有多少落进了你的口袋，丢掉的那部分是谁拿走的**。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 自己申赎基金的普通基民（不开对冲、不做量化，凭感觉加减仓）；定投半途而废的人；在基金回撤里割过肉又追回来的人——「基金赚钱、基民不赚钱」段子的当事人。 |
| **场景** | 年底打开基金 App：持仓收益 +8%，基金页面却写着「近三年 +58%」，钱去哪了没人回答；大盘跌 20% 时恐慌清仓、反弹 15% 后忍不住追回，两次操作各值多少个点从来没数；朋友晒出「我只买宽基定投」时，想知道自己凭手感的操作到底比无脑定投好还是差。 |
| **问题** | **净值增长率是基金的成绩单，不是你的**：① TWR 假设资金全程在场，你的追涨杀跌它一概不知——App 把前者印在最大的字号里，错觉由此生成（净值幻觉）；② 你的真实收益率（XIRR）需要解你全部现金流的时间价值，没有任何面向个人的工具算它；③ 行为差的归因（追高买了多少、坑底割了多少、割完错过多少反弹）散落在交易记录里，从没有被拼成一张账单；④ 「早知道拿住不动」是一句忏悔，没有人把它折成可比较的数字。 |
| **价值与意义** | 1) **行为差第一次有数字**：XIRR − TWR = 你的择时总贡献，年化口径，正了你比基金还会玩，负了你在给自己的情绪打工——「管住手」从鸡汤变成可计量的学费。<br>2) **行为画像有证据**：每笔申购的近一年高位位置（金额加权平均 >0.65 追涨型 CHASING / <0.35 抄底型 BOTTOM-FISHING），割肉清单按「距前 180 日高点回撤 >10%」客观识别，并计算其后 90 天错过的反弹金额。<br>3) **反事实三连**：期初一次买入（hold）、等额月定投（dca）、你的实际操作（actual）三口锅并排——「拿住不动」和「无脑定投」第一次与你的手感同台报价。<br>4) **诚实条款**：不连行情 API，净值全部用户提供；不建模 T+1 确认与费率折扣（请用费后金额记账）；XIRR 不收敛或数据病态时拒答 exit 3 而不是报一个荒谬的负数；不构成任何投资建议——它对账过去，不导演未来。 |

---

## 核心思想：净值是基金的成绩单，XIRR 才是你的

| 概念 | 规则 | 回答的问题 |
|---|---|---|
| **份额账本 shares** | 申购份额 += 金额 ÷ 当日净值；赎回份额 −= 金额 ÷ 当日净值；分红不减份额（现金落袋）；份额 <0 = 数据病态 exit 3 | 「我现在到底有多少份？」 |
| **TWR** | 复权净值首尾总增长率 + 年化（(1+total)^(365/天数) − 1） | 「这只基金自己赚了多少？」 |
| **XIRR** | 现金流 = 申购负 / 赎回正 / 分红正 / 期末市值正，二分法解 NPV=0；不收敛 exit 3 | 「我的钱实际年化了多少？」 |
| **行为差 gap** | XIRR − TWR（同为年化口径）；≥0 BEAT / −5pp~0 DRAG / ≤−5pp BLEEDING exit 4（`--gap-line` 可调） | 「我和这只基金之间，谁拖累了谁？」 |
| **高位位置 price position** | 该笔净值在**近 365 日**高低区间中的位置（0=区间底、1=区间顶，≥1 也按 1 记——追在高点之上更是追高）；申购按金额加权平均 >0.65 判 CHASING、<0.35 判 BOTTOM-FISHING；窗口内净值点不足 2 个如实记「无历史」不参与加权 | 「我总在贵的时候买吗？」 |
| **割肉清单 panic** | 卖出日净值距前 180 日高点回撤 >10% 即 PANIC；机会成本 = 卖出份额 × (之后 90 日净值 − 卖出净值)（窗口不足 90 日如实标注） | 「坑底那刀割掉了多少钱？」 |
| **反事实 simulate** | actual = 你的期末市值；hold = 全部申购金额在首日一次买入；dca = 每月等额定投（默认取实际月均净申购） | 「拿住不动 / 无脑定投，各值多少？」 |

四条诚实条款刻在实现里：**账本只记你声称的事实**——不连任何行情接口，净值序列与申赎记录全部手工提供，建议使用基金公司公布的复权净值（分红再投口径）；**费后记账**——T+1 确认、申购费折扣、赎回费梯度一概不建模，请直接记费后金额；**分红记 DIV 现金落袋**——它是 XIRR 里的正现金流、也不该凭空消失在份额里，两本账各自自洽；**拒答优先于胡说**——净值不足 2 点、跨度不足 180 天、现金流不足 2 笔、份额穿透、XIRR 不收敛，一律 exit 3 交还数据，绝不输出一个看起来像结论的负数。**本工具不构成投资建议**：它审计已发生的行为，不预测净值，不推荐买卖。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash dd:ignore
python3 nav_illusion.py report examples/flows.csv examples/navs.csv --as-of 2026-06-30
```

## 命令速查

```bash dd:ignore
python3 nav_illusion.py report flows.csv navs.csv --as-of 2026-06-30      # XIRR/TWR/行为差 + 判定灯
python3 nav_illusion.py flows flows.csv navs.csv --as-of 2026-06-30       # 逐笔审计：百分位 + 割肉清单
python3 nav_illusion.py simulate flows.csv navs.csv --as-of 2026-06-30    # actual vs hold vs dca
python3 nav_illusion.py doctor flows.csv navs.csv                          # 数据体检
python3 nav_illusion.py report flows.csv navs.csv --gap-line -10          # 阈值放宽到 −10pp
python3 nav_illusion.py report flows.csv navs.csv --format json           # 机读
```

## 一个真实样例

小陈，2024-01-03 起对同一只基金做了 5 笔操作（`python3 examples/build_examples.py` 可从零重建，日期全部钉死，`--check` 逐字节校验）。净值走势：1.00 → 涨到 1.15 → 深坑 0.98 → 两年半到 1.35，总收益 **+35%**。小陈的操作：起步投 5,000，涨到高点追进 20,000，坑里恐慌赎回 12,000，反弹后 FOMO 回补 8,000，最后再追 5,000。[`examples/sample-report.txt`](examples/sample-report.txt) 的判决：

```text dd:ignore
  two clocks of return
    fund TWR     : +12.78%/yr   the fund's report card (nav 1.0000 → 1.3500, +35.00% total)
    your XIRR    : +6.46%/yr   what your money actually earned
    behavior gap : -6.32 pp/yr   XIRR − TWR

  behavior profile
    buy price position (365d, amount-weighted): 0.89 → CHASING
    panic sells  : 1 of 1 — worst sold in a -14.32% drawdown (180d high 1.1500)
                   2024-10-08 — next 90 days paid +7.30% back: 875.60 went to whoever held

  verdict: BLEEDING — gap -6.32 pp <= -5.00 pp line. The fund earned; your hands paid the difference.
```

读法：**基金年化 +12.78%，小陈年化 +6.46%**——差额 6.32 个百分点就是两年半里每次「感觉该加了」「感觉要完」的手感税。申购的近一年高位位置金额加权 0.89：钱主要泼在墙上已经很高的位置。唯一一笔赎回发生在 −14.32% 的回撤里（PANIC 实锤），卖掉的 12,178.7 份在之后 90 天里涨回了 7.30%——约 ¥876 的反弹落进了没割肉的人口袋。然后是反事实三连（[`examples/sample-simulate.txt`](examples/sample-simulate.txt)）：

```text dd:ignore
  actual  your hands, as lived             29,036.29
  hold    one shot on day one              35,100.00   +6,063.71 vs actual
  dca     blind monthly   866.67 ×30       30,381.40   +1,345.11 vs actual

holding still beat your hands by 6,063.71; your timing was the most expensive part of this fund.
```

同样的钱，期初一次拿住不动到今天值 35,100——你的手感两年半花了 6,064 元学费；连闭着眼睛定投都比手感多 1,345。行为差 −6.32pp ≤ −5pp 红线，`report` 亮 **BLEEDING** 灯并 **exit 4**——不是要你清仓，是要你在下一次手痒之前，先读完这份学费明细。逐笔审计（[`examples/sample-flows.txt`](examples/sample-flows.txt)）把每一笔的高位位置与标签摆上桌；`doctor`（[`examples/sample-doctor.txt`](examples/sample-doctor.txt)）先确认这两本账值得被审计。

## dogfood：样例账本即狗粮

```text dd:ignore
$ python3 examples/build_examples.py --check
examples in sync
```

真实持仓天然敏感，本件不内置任何真实基民的账。dogfood 的形式与仓库传统一致：**四份样例报告由交付代码本身渲染**（`examples/build_examples.py` 走与 CLI 完全相同的代码路径），CI 用 `--check` 逐字节校验——报告里的每一个数字都能从钉死的账本与 `--as-of` 复现，一份手写的样例都不存在。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_navillusion.py`](tests/test_navillusion.py)，`unittest` + 合成账本 + 预计算期望值）：

```bash
python3 -m unittest discover -s nav-illusion/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 账本解析：中英文表头、动作别名（申购/赎回/分红→BUY/SELL/DIV）、三种日期写法、可选净值列留空触发插值、缺表头/坏数字报行号、空行容忍 | `ParserTests` |
| 插值：按天数线性插值到当天、边界外拒绝、插值笔数在报告中披露 | `InterpTests` |
| 份额账本：申购/赎回/分红的份额增减、期末市值 = 剩余份额 × as-of 净值、赎回穿透报 exit 3 | `ShareLedgerTests` |
| XIRR：单笔两年翻倍 = +41.42%、等额定投现金流的标准解、不收敛/无解 exit 3、符号约定（申购负赎回正） | `XirrTests` |
| TWR：首尾总收益、年化换算（365/天数）、复权净值口径说明 | `TwrTests` |
| 行为差：gap = XIRR − TWR 恒等、三档判定灯边界（BEAT/DRAG/BLEEDING）、BLEEDING exit 4、`--gap-line` 覆盖 | `GapTests` |
| 高位位置与画像：365 日窗口区间位置计算与 [0,1] 截断、金额加权平均、CHASE-HI/BOTTOM-LO/MID-RANGE 与 CHASING/BOTTOM-FISHING 档位、无历史首笔不参与加权 | `PercentileTests` |
| 割肉识别：回撤 >10% 判 PANIC、90 日窗口机会成本、窗口不足 90 日如实标注、未越线判 DISCIPLINE | `PanicTests` |
| 反事实：hold 期初一次买入、dca 月定投金额与节奏、actual/hold/dca 三口锅并排输出、差额 = hold − actual | `SimulateTests` |
| doctor：日期乱序、flows 越出净值范围、重复日期、样本不足 exit 3（净值 <2 点/跨度 <180 天/现金流 <2 笔） | `DoctorTests` |
| CLI：无参数 exit 2、文件缺失 exit 3、`--as-of` 缺省净值末日、`--format json` | `CliTests` |
| **dogfood：样例逐字节同步 + demo 数字核验（XIRR/TWR/gap/期末市值）** | `DogfoodTests` |

## 项目结构

```
nav-illusion/
├── nav_illusion.py
├── tests/test_navillusion.py
├── examples/build_examples.py
├── examples/flows.csv
├── examples/navs.csv
├── examples/sample-report.txt
├── examples/sample-flows.txt
├── examples/sample-simulate.txt
├── examples/sample-doctor.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
