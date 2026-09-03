# 里程错觉 · Odometer Illusion

> 里程表只记你走了多远，不记车老了多久。
> A zero-dependency CLI that keeps a twin-clock maintenance ledger for a car: every item ages on the mileage clock and the calendar clock at once, and the first clock to run out wins. The odometer only shows the first clock — that is exactly how a rarely-driven car stays "young" on the dash while rotting everywhere else.

---

## 一句话

车有两口钟：**里程钟**（部件随使用磨损）和**日历钟**（部件随时间老化），每项保养听**先走完的那口**。而人的直觉里只有一口钟——里程表那口。一年跑五千公里的车主盯着里程表觉得「这车还新着呢」，但机油开封后氧化吸水、雨刮橡胶龟裂、刹车油吸水降沸点、电瓶化学衰减、冷却液防锈耗尽，全都在日历钟上走，里程表一个字都不会提。4S 店的保养表按「平均车主」设计（半年/5000 公里一刀切），于是低里程车主被时间表收割（过度保养），高里程车主被时间表坑害（保养不足）。`odometer-illusion` 的立场：**保养周期不是两个数字，是两场比赛**。从一张车辆档案和一本可手编的保养账（日期/里程/项目/费用）算出每个品目在两口钟上的**进度**，取 max 得出总进度并指出**约束钟**（先到期的那口）；把 DUE 品目的约束钟汇总成**车主画像**——日历型车主的结论只有一句话：**你的车不是跑旧的，是放旧的**；`trip` 把一段计划旅程对着全部品目过闸（归途日任何一项越线都 exit 4）；`cost` 把小票金额折算成每公里成本——保养从来没有多贵，拖延才贵。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 低里程车主（通勤近/家里第二辆车/退休父母的车，一年跑不到 8000 公里——被里程表欺骗的头号人群）；高里程车主（一年 3 万公里，「去年才保养过」的口头禅持有者）；刚接手二手车、没有任何保养历史的新车主。 |
| **场景** | 师傅说「你这机油都一年没换了」时，心里冒出「我才跑了三千公里」的反驳；4S 店按时间表推销套餐时判断是真需求还是收割；春节/十一长途自驾前回答「这车能不能顶住来回两千六」；把父母一年跑三千公里的车接过来年检时，第一次给它的老化程度建档。 |
| **问题** | **老化是双钟的，而仪表盘只有一口钟**：① 里程表的低读数给低里程车主「车还很新」的错觉（odometer illusion），但机油的氧化、橡胶的龟裂、刹车油的吸水、电瓶的硫酸盐化按日历走，与里程无关；② 4S 店的周期表按「平均车主」一刀切，对低里程车主过度保养、对高里程车主保养不足，而你没有自己的账本去对质；③ 长途前的「车况还行吧」是一种祈祷——哪些品目会在半路越线，出发前没人算过；④ 保养花了多少钱从来只有一个模糊总数，没有每公里、每年的真实费率。 |
| **价值与意义** | 1) **双时钟进度**：每品目两口钟各自算进度（跑了周期里程的百分之几 / 过了周期天数的百分之几），总进度 = max，并指认**约束钟**——「机油里程钟才走 44%，日历钟已走 129%」这一句话终结「要不要换」的争论。<br>2) **车主画像**：DUE 品目的约束钟汇总分型（日历型/里程型/混合），低里程车主第一次看见自己的完整错配——样例车里 6 项 OVERDUE 的约束钟 6/6 全是日历钟，年里程 5,760 km。<br>3) **出发闸门**：`trip --km --days` 把「归途日、归途里程」对全部品目推演，任何一项越线 exit 4 并给出出发前必办清单——把高速上爆的雷提前拆掉。<br>4) **费用账**：小票金额折成每公里成本与年成本——「¥420 的机油」放进「每公里 1 毛 5」的语境里，拖延的代价第一次可比较。<br>5) **零依赖 + 纯本地 + 可复现**：Python 3.8 标准库，`--as-of` 与 `--km-now` 钉死即逐字节可复现，车辆数据不出电脑。 |

---

## 核心思想：先到期的钟说了算

| 概念 | 规则 | 回答的问题 |
|---|---|---|
| **双时钟 clocks** | 每品目两个周期（日历天数、里程公里），周期为 0 表示该品目不吃这口钟（雨刮/电瓶纯日历，`--period` 可设纯里程件） | 「这项保养在跟时间还是跟里程？」 |
| **进度 progress** | 里程进度 = 已行驶/周期里程；日历进度 = 已流逝/周期天数；**总进度 = max(两者)** | 「这项保养走了百分之几？」 |
| **约束钟 binding clock** | 进度更大的那口钟 | 「是什么让它到期的——用旧的，还是放旧的？」 |
| **档位 band** | progress ≥100% OVERDUE / ≥85% DUE / ≥70% SOON / else OK | 「现在该做什么？」 |
| **原厂假设 assumed** | 服务账里从没出现过的品目，从提车时刻起算并标注 assumed factory | 「没换过的件从哪天开始老化？」 |
| **车主画像 profile** | DUE 品目 ≥2 时按约束钟分型：日历 ≥60% 日历型 / 里程 ≥60% 里程型 / else 混合 | 「我是被里程表骗的那种人吗？」 |
| **出发闸门 trip gate** | 归途日 = as-of + days、归途里程 = 里程 + km，逐品目重算进度；≥100% FAIL exit 4，85–100% 提示 | 「这趟长途，哪些雷会在半路爆？」 |

四条诚实条款刻在实现里：**账本只记你声称的事实**——不连 OBD、不扫行车电脑，工具消费的是你保养小票上的日期和里程；**周期表是常识值不是厂家值**——默认表取保守的公开常识（机油 180d/5000km、刹车油 730d/40000km、电瓶 1095d……），车辆手册永远赢，`--period` 行级覆盖；**assumed 不是数据而是假设**——从没记录过的品目按原厂件从提车日起算并显式标注，接手二手车应先全量记一条基线；**没有费用列就不出费用账**——工具不会替你发明小票上的数字。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash dd:ignore
python3 odometer_illusion.py status examples/family-car.csv examples/service-log.csv --as-of 2025-12-01 --km-now 21400
```

## 命令速查

```bash dd:ignore
python3 odometer_illusion.py status car.csv service.csv --as-of 2025-12-01 --km-now 21400   # 双时钟仪表盘 + 车主画像
python3 odometer_illusion.py trip car.csv service.csv --as-of 2025-12-01 --km 2600 --days 12  # 长途过闸，一项越线 exit 4
python3 odometer_illusion.py cost car.csv service.csv --as-of 2025-12-01 --km-now 21400     # 每公里/每年的真实费率
python3 odometer_illusion.py status car.csv service.csv --period engine_oil=365,10000       # 覆盖周期（手册说了算）
python3 odometer_illusion.py status car.csv service.csv --format json                        # 机读
```

## 一个真实样例

小白，2022-03-15 提车，一本 13 笔的保养账（`python3 examples/build_examples.py` 可从零重建，日期全部钉死，`--check` 逐字节校验）。参照日钉在 2025-12-01，里程表 21,400 km——三年零八个月，年均 5,760 km，标准的低里程车。[`examples/sample-status.txt`](examples/sample-status.txt) 的判决：

```text dd:ignore
  item            last done         mileage  calendar  progress  band
  brake_fluid     assumed factory        54%      186%      186%  !! OVERDUE
  coolant         assumed factory        54%      186%      186%  !! OVERDUE
  wipers          2024-06-20               —      145%      145%  !! OVERDUE
  engine_oil      2025-04-13             44%      129%      129%  !! OVERDUE
  battery         assumed factory          —      124%      124%  !! OVERDUE
  ...
  binding clocks of the 6 due items: 6 calendar · 0 mileage
  you are a calendar-bound driver: 5,760 km/y means the odometer
  barely moves — this car is aging in the garage, not on the road.
```

读法：**机油才走了里程钟的 44%（「才跑了两千公里换什么油」），但日历钟已经 129%**——油在曲轴箱里氧化了七个多月。刹车油与冷却液「从没换过」按原厂件算 186%，电瓶纯日历 124%，雨刮 145%。6 项 OVERDUE 的约束钟 6/6 全是日历钟：这台车没有一项是被**用**坏的。然后是出发闸门（[`examples/sample-trip.txt`](examples/sample-trip.txt)）——春节想跑 2,600 km 回家：

```text dd:ignore
  trip gate : depart 2025-12-01 · + 2,600 km / 12 days
  return    : 2025-12-13 @ 24,000 km

  6 of 11 items cross the line mid-trip:
  ! brake_fluid       188% at return (calendar clock) — service before you leave
  ...
  gate: FAIL
```

6 项在路上越线，exit 4——出发前办掉，比在高速服务区叫拖车便宜。最后是费用账（[`examples/sample-cost.txt`](examples/sample-cost.txt)）：13 笔小票 ¥3,161，**每公里 0.148 元，每年 851 元**——保养从来没有多贵。

## dogfood：样例账本即狗粮

```text dd:ignore
$ python3 examples/build_examples.py --check
examples in sync
```

真实车辆数据天然敏感，本件不内置任何真实车主的账。dogfood 的形式与仓库传统一致：**三份样例报告由交付代码本身渲染**（`examples/build_examples.py` 走与 CLI 完全相同的代码路径），CI 用 `--check` 逐字节校验——报告里的每一个数字都能从钉死的账本与 `--as-of`/`--km-now` 复现，一份手写的样例都不存在。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_odometerillusion.py`](tests/test_odometerillusion.py)，43 个用例，`unittest` + 合成账本）：

```bash
python3 -m unittest discover -s odometer-illusion/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 账本解析：中英文表头与品目别名归一、空行容忍、五种日期写法、里程读数、缺表头/缺车行报错、未知品目保留不丢弃 | `ParserTests`（8 例） |
| 双时钟数学：总进度 = max(两钟)、纯日历件无里程钟、`--period` 纯里程件、档位七点边界、约束钟归属、assumed 从提车起算、最近一次服务重启双钟、周期覆盖改判 | `ClockTests`（8 例） |
| 核心错配：低里程车机油日历钟 OVERDUE 而里程钟 <50%、高里程车里程钟 OVERDUE 而日历钟 <50%、里程表读数 = max(账本， --km-now) | `MismatchTests`（3 例） |
| 仪表盘：按总进度降序、counts 行、未知周期品目单列不判档、`--format json` | `StatusTests`（3 例） |
| 车主画像：年里程、日历型/里程型分型、DUE <2 不分型 | `ProfileTests`（4 例） |
| 出发闸门：FAIL exit 4 与出发前清单、全绿 PASS exit 0、归途点 = as-of+days / 里程+km、85–100% 仅提示不拦、--days 缺省 7 与 --km 必填、负数拒绝 | `TripTests`（6 例） |
| 费用账：总额/每公里/每年/按品目分布、无费用列时诚实拒绝编造、坏费用报行号 | `CostTests`（3 例） |
| CLI：无参数 exit 2、文件缺失 exit 3、坏 `--period` exit 3、`--as-of` 缺省今天、`--km-now` 生效 | `CliTests`（5 例） |
| **dogfood：样例逐字节同步 + demo 数字核验** | `DogfoodTests`（3 例） |

## 项目结构

```
odometer-illusion/
├── odometer_illusion.py
├── tests/test_odometerillusion.py
├── examples/build_examples.py
├── examples/family-car.csv
├── examples/service-log.csv
├── examples/sample-status.txt
├── examples/sample-trip.txt
├── examples/sample-cost.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
