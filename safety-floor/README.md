# 兜底 · Safety Floor

> 保单的数量给你心安，保额的厚度才接得住事。
> A zero-dependency CLI that spreads a family's insurance policies into one coverage-gap ledger: the policies you own prove that someone once sold you something; the floor under your family — target minus actual, per member, per peril — is what catches you the day things go wrong. The premium receipt measures what you paid; this ledger measures what you would land on.

---

## 一句话

保险是家里唯一「买的时候希望永远用不上」的东西，也是唯一**买了和保够了是两回事**的东西：代理人按佣金推产品，不按缺口推——大多数家庭的保单组合是一段「被推销史」，不是一张「保障规划」；「我们家有保险」的安全感来自保单**存在**，不来自保额**够不够**——10 万的重疾保额对一场重疾的意义接近于零，给孩子囤的教育金年金一分保障都不产生，而真正的顶梁柱寿险是零、重疾是零，在裸奔。`safety-floor` 把全家保单摊成一张**缺口账**：从成员表（谁在扛梁）和保单表（谁有什么）算出每个成员 × 每个险种的**目标保额**（通识公式：寿险 = 年收入 × 10、重疾 = 年支出 × 3、医疗 = 百万门槛、意外 = max(年收入 × 5, 20 万)——规划师永远赢，参数全部可覆盖）与**覆盖比**（BARE 裸奔 / THIN 不足半 / SHORT 不足额 / COVERED 达标，医疗险是「有没有」的险种只判二值）；`premium` 记那本没人看过的**保费账**——全家每 1 元保费里有多少落在不产生任何保障的储蓄型上、保费占家庭收入比有没有越过双十定律的保费半边；`gaps` 给出**补哪先**的排序（顶梁柱裸奔第一，永远第一）——它不卖保险、不算保费市价、不预测风险，只回答一个问题：**出事那天，接住你家的是多厚一层地板**。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 一家之主 / 家庭财务管家（有房贷或娃，保单散落在全家人手里、抽屉和邮箱里，说不清全家到底「有哪些、各保多少」）；给娃买了一堆、自己只有单位社保的年轻父母；刚经历朋友患病/朋友圈轻松筹、深夜算过「我要是倒下了房贷谁还」的人。 |
| **场景** | 保险代理人第 N 次推销时，判断是补缺口还是叠 redundancy；整理抽屉翻出一沓保单想做个家庭总账；给娃又签一份教育金时，想知道这份预算是不是本该花在别处；体检报告出现结节后突然想确认「我的重疾到底保多少」。 |
| **问题** | ① **保单组合是被推销史的沉积**：每一张单在当时都有理由，合起来却没人看过——顶梁柱裸奔、孩子超配、储蓄型挤占保障预算，是同一种错的三种长相；② **「有保险」≠「有保障」**：保额的数量感被保单张数替代，10 万重疾 vs 60 万需求的差距静默存在，直到理赔那天才被翻译出来；③ **保费账没有分母**：全家一年交多少保费容易加总，但「占家庭收入多少」「其中多少在买保障、多少在买理财产品」从来没人算；④ **补缺没有顺序**：预算永远有限，先给谁买、先补哪个险种，直觉永远把孩子排在前面——恰恰是最贵的排法。 |
| **价值与意义** | 1) **缺口第一次有数字**：每个成员 × 每个险种的目标保额、现有保额、覆盖比与缺口金额全部摊开——「我们家保障够不够」从一句感觉变成一张账。<br>2) **顶梁柱裸奔结构性现形**：门禁只认最重的账——任何扛梁成员在寿险/重疾/医疗任一险种 BARE（保额为零）即 EXPOSED exit 4，孩子和长辈的缺口如实列出但不触发门禁（先大人后小孩是排序原则，不是道德指责）。<br>3) **保费账两个新分母**：保费收入比（双十定律的保费半边，>15% 说明是买错了不是买少了，exit 4）与**无效保费比**（储蓄型保费占全部保费的比例——「每 1 元保费里有几毛在买保障」第一次被计量）。<br>4) **补缺排序清单**：`gaps` 按「裸奔 > 不足半 > 不足额、顶梁柱 > 成人 > 孩子 > 长辈、缺口大者先」给出清单——工具不知道市场保费价，所以它只回答「补哪先」，不假装知道「花多少」。<br>5) **诚实条款**：目标保额是通识公式不是精算建议，`--life-years` 等参数全部可覆盖（规划师/代理人永远赢）；工具不知道你能买到的保费市价，更不预测你出事的概率；它不构成投保建议——它把缺口摊开，签不签单仍是人的决定。 |

---

## 核心思想：地板厚度 = 每一格的 目标 − 现有

| 概念 | 规则 | 回答的问题 |
|---|---|---|
| **目标保额 target** | 寿险 = 年收入 × 10（`--life-years`；无收入成员目标 0，未成年人/长辈不设寿险目标——他们的身故不构成家庭收入中断）；重疾 = 年支出 × 3（`--ci-years`，康复期收入中断对全员等价）；医疗 = 百万门槛 100 万（`--medical-floor`，二值险种）；意外 = max(年收入 × 5, 20 万)（`--accident-years` / `--accident-flat`） | 「这一格的及格线在哪？」 |
| **覆盖比 coverage** | 现有保额 ÷ 目标；≥1 COVERED / <1 SHORT / <0.5 THIN / 0 BARE；**医疗险只判二值**：≥门槛 COVERED，否则 BARE——20 万的「医疗险」在大额账单面前不是小号保障，是没有 | 「这一格站在哪一档？」 |
| **角色 role** | beam 顶梁柱 / spouse 配偶 / adult 成人 / child 孩子 / elder 长辈；决定寿险目标有无与排序权重 | 「谁在扛梁，谁在裸奔？」 |
| **保费账 premium** | 全家年保费 ÷ 家庭年收入 = 保费收入比（≤10% OK / 10–15% TIGHT / >15% OVERPAY exit 4——双十定律的保费半边）；储蓄型（other）保费单独归堆成**无效保费比** | 「钱花在保障上，还是花在心安上？」 |
| **补缺排序 gaps** | 状态权重（BARE 0 / THIN 1 / SHORT 2）→ 角色权重（beam 0 / spouse·adult 1 / child 2 / elder 3）→ 缺口金额降序 | 「下一笔预算给谁？」 |
| **门禁 verdict** | 任一 beam 的寿险/重疾/医疗任一 BARE → **EXPOSED** exit 4；无 BARE 但有 THIN/SHORT → CRACKED；全 COVERED → SOLID；保费比 >15% 独立触发 exit 4 | 「这层地板现在能不能接住事？」 |

四条诚实条款刻在实现里：**目标保额是通识先验不是精算**——支出倍数与收入倍数取公开常识值（10/3/5），参数全部可覆盖，专业规划师永远赢；**工具不知道保费市价**——`gaps` 只排「补哪先」，任何「某产品多少钱」的问题都超出账本的管辖；**other 险种不进保障账但进保费账**——年金/教育金/增额寿的真实功能是储蓄，把它当保障数是整本账最大的自欺，工具直接点名金额；**不构成投保建议**——它不预测风险、不推荐产品、不算收益率，它只把「出事那天接住你的是什么」摊开成一个数字。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash dd:ignore
python3 safety_floor.py report examples/family.csv examples/policies.csv --expense 200000
```

## 命令速查

```bash dd:ignore
python3 safety_floor.py report family.csv policies.csv --expense 200000   # 全家缺口总账 + verdict 门禁
python3 safety_floor.py gaps family.csv policies.csv --expense 200000     # 补哪先：排序清单
python3 safety_floor.py premium family.csv policies.csv                   # 保费账：收入比 + 无效保费
python3 safety_floor.py report family.csv policies.csv --expense 200000 \
    --life-years 8 --ci-years 5 --medical-floor 2000000                    # 参数覆盖（规划师永远赢）
python3 safety_floor.py report family.csv policies.csv --expense 200000 --format json  # 机读
```

## 一个真实样例

小陈家：本人（顶梁柱，年入 30 万）、太太（配偶，年入 15 万）、娃、陈妈（长辈），家庭年支出 20 万，8 张保单（`python3 examples/build_examples.py` 可从零重建，`--check` 逐字节校验）。[`examples/sample-report.txt`](examples/sample-report.txt) 的判决：

```text dd:ignore
verdict: EXPOSED — the pillar stands bare (陈小明: life (0 of 3,000,000), ci (0 of 600,000)).
the day the pillar falls, this family lands on nothing. exit 4
```

覆盖矩阵把整件事摊开：顶梁柱本人**寿险裸奔（0 / 300 万）、重疾裸奔（0 / 60 万）**——单位团意险的 10 万意外是他全部的自有保障，剩下的 300 万医疗还是消费型；太太重疾只有 20 万（覆盖比 0.33 THIN）、意外裸奔；娃重疾 50 万（SHORT）、意外裸奔；陈妈意外达标，医疗裸奔。而保费账（[`examples/sample-premium.txt`](examples/sample-premium.txt)）给出最扎心的一行：

```text dd:ignore
  premium ratio : 3.1% of income · OK (<= 10.0% OK · > 15.0% OVERPAY, exit 4)
  savings-type  : 8,000/yr = 57.0% of every premium yuan — annuities and education funds buy no protection
  premium feeds : 陈小满 70.3% · 林悦 25.0% · 陈小明 2.5% · 陈母 2.1%
```

**保费比例健康（3.1%），但每 1 元保费里有 5 角 7 分买的是教育金年金——不产生一分保障；娃吃掉 70.3% 的保费，扛梁的人只占 2.5%。** 不是买贵了，是买反了方向。补缺清单（[`examples/sample-gaps.txt`](examples/sample-gaps.txt)）第一行永远是同一句话：顶梁柱寿险 300 万、重疾 60 万——先大人后小孩，在这里不是口号，是排序算法。

## dogfood：样例账本即狗粮

```text dd:ignore
$ python3 examples/build_examples.py --check
examples in sync
```

真实保单天然敏感，本件不内置任何真实家庭的账。dogfood 的形式与仓库传统一致：**三份样例报告由交付代码本身渲染**（`examples/build_examples.py` 走与 CLI 完全相同的代码路径），CI 用 `--check` 逐字节校验——报告里的每一个数字都能从钉死的账本与参数复现，一份手写的样例都不存在。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_safetyfloor.py`](tests/test_safetyfloor.py)，`unittest` + 合成账本）：

```bash
python3 -m unittest discover -s safety-floor/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 账本解析：中英文表头与角色/险种别名归一、空行容忍、负保额/负保费报行号、被保人不在成员表 exit 3、重复成员名 exit 3、未知角色/险种 exit 3、other 储蓄型保留不入保障账 | `ParserTests` |
| 目标保额：寿险 = 收入×10 且无收入者目标 0、child/elder 无寿险目标、重疾 = 支出×3 全员一致、医疗门槛二值、意外 = max(收入×5, 20 万)、四个 `--*-years/--*-floor/--accident-flat` 覆盖、`--expense` 缺失 exit 3 | `TargetTests` |
| 覆盖矩阵：BARE/THIN/SHORT/COVERED 档位边界（0/0.5/1）、医疗二值判档、child/elder 寿险格显示 — 不判档、beam 排最前、`--format json` | `MatrixTests` |
| 保费账：保费收入比三档（≤10% OK / 10–15% TIGHT / >15% exit 4）、无效保费比（other 险种）、按成员的保费去向、收入全 0 不判比例只披露 | `PremiumTests` |
| 补缺排序：状态权重优先（BARE > THIN > SHORT）、角色权重次之（beam > spouse/adult > child > elder）、同权重缺口金额降序、清单含目标/现有/缺口金额 | `GapsTests` |
| 门禁：beam 任一必配险种 BARE → EXPOSED exit 4、无 BARE 有缺口 → CRACKED exit 0、全达标 → SOLID exit 0、保费比 >15% 独立 exit 4、child/elder BARE 不触发门禁 | `VerdictTests` |
| CLI：无参数 exit 2、文件缺失 exit 3、负 `--expense` exit 3、JSON 机读 | `CliTests` |
| **dogfood：样例逐字节同步 + demo 数字核验（EXPOSED/缺口金额/保费比/无效保费比）** | `DogfoodTests` |

## 项目结构

```
safety-floor/
├── safety_floor.py
├── tests/test_safetyfloor.py
├── examples/build_examples.py
├── examples/family.csv
├── examples/policies.csv
├── examples/sample-report.txt
├── examples/sample-gaps.txt
├── examples/sample-premium.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
