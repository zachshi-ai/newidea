# 种草账 · Want Ledger

> 每本账都从「买」才开始记——没有人记账「想要」本身。而冲动恰恰住在种草到拔草之间的那段空白里。
> A zero-dependency CLI that keeps a ledger of the wanting, not just the buying: the half-life of a desire, the two-arm regret trial between your fast hand and your slow one, and a tuition bill for every want that didn't survive its own checkout.

---

## 一句话

你的衣柜有账本（cost-per-wear）、冰箱有账本（fridge-void）、闲置有账本（recoup）——它们全部从「付款那一刻」才开始记；而「想要」本身——深夜刷到的那一下心动、购物车里躺了三周的犹豫、下单当晚就后悔的 2,999——在所有账本里统计蒸发。`want-ledger` 给欲望本身记一本生命周期账（TSV：种草日/品名/价位/标签/结局/结局日/后悔），从你的历史里挖出四样从来没有人替你算过的东西——**种草半衰期**：枯草（没买也不想要了）的中位存活天数，样例 22 株草的答案是 **13.0 天——你的欲望一半活不过两周**；**30 天存活率**：只有 19.0% 的草活过第 30 天——「放购物车冷静 30 天」从此不是口号，是你自己的统计事实；**两臂后悔对账**：冲动臂（种草 ≤7 天即拔草，8 株，75.0% 后悔）vs 沉思臂（种草 >7 天才拔草，5 株，20.0% 后悔）——「手比心快」第一次不是自嘲，是带分母的判决；**冲动学费**：后悔买掉的钱 5,833 ÷ 已购总额 12,717 = **45.9% 越过 30% 线 → REGRET-HEAVY exit 4**——「乱花钱」第一次有了发票。深夜再被种草时 `check` 把闸门放下：种龄 3 天 < 冷却期 14 天 → **STILL COOLING exit 4，2026-09-15 再来表决**，并附上你的证据——「按你的历史，只有 19% 的草能活到你说的那天」；冷静期满 → DECIDE NOW，证据摆桌，表决权在你。它不评判欲望——种草是人的乐趣，枯草是免费的节俭；它只做一件事：**让今晚的「想要」，接受你自己全部历史的盘问**。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 被种草内容包围的普通消费者——直播间里「0 秒下单」的人、购物车当收藏夹用的人、每次大促都「忍不住」事后又吃灰的人；不缺判断力、缺一本欲望历史的理性人。 |
| **场景** | 深夜刷到一台 899 的机械键盘，手指已经悬在购买键上：买，还是先放着？直觉只有两个工具——「我想要」（此刻的欲望）和「我要克制」（抽象的美德），两者之间没有任何数据；上次冲动买的无人机正在抽屉里吃灰，但「下次会不会也后悔」没有答案，因为冲动买的东西和想清楚了才买的东西，从来没有被分成两组比过后悔率。 |
| **问题** | ① **欲望没有寿命记录**：一切消费账本都从成交开始记，种草到拔草/枯草之间的整段生命周期统计蒸发——你不知道自己的欲望平均活几天、多少能活过冷静期；② **冲动与深思没有对照组**：「冲动买亏了」是印象不是数据，「快买」和「慢买」的后悔率从未被并排比较——你对自己的欲望可信度一无所知；③ **冷静期无法执行**：「放 30 天再买」人人会说，但没有账本告诉你 30 天后还想要的比例，闸门缺少你自己的数字，永远拉不起来；④ **学费没有合计**：后悔支出散落在每一笔订单里，从来没有人把它加成一张发票。 |
| **价值与意义** | 1) **欲望有了刻度**：种草半衰期（枯草中位存活 13.0 天）与 30 天存活率（19.0%）——「我就是三分钟热度」从自嘲变成两个可跟踪的数字，你的欲望画像第一次有了分母。<br>2) **两臂对账**：冲动臂 vs 沉思臂的后悔率并排（75.0% vs 20.0%），样本不足时 THIN 拒绝下结论——对自己做对照实验，这是从 scapegoat 继承的皮肤游戏：**后悔列就是你的回填作业**，不回填就没有证据。<br>3) **学费发票**：REGRET-HEAVY 门禁（学费占比 ≥30% exit 4，`--tuition-line` 可调、需 ≥8 笔有价已购才允许设门）——冷静闸门不再是道德说教，是你自己账单的影子。<br>4) **诚实条款**：价位是你声称的价签不是审计的小票；未回填的后悔按缺失数据处理、绝不默认「很满意」；枯草是免费的节俭、只有买错的才进学费；账本只提供证据——**闸门什么也拦不住，表决权永远在你**。 |

---

## 核心思想：给「想要」本身记一本生命周期账

| 概念 | 规则 | 回答的问题 |
|---|---|---|
| **三态生命周期** | 每株草一行：种草日 → 结局（拔草=买了 / 枯草=没买也不想要了 / 空=在长）；结局日必须 ≥ 种草日，枯草不许填后悔（枯草不后悔，它只是死了） | 「这株草现在活着还是死了？」 |
| **种草半衰期 t½** | 枯草存活天数（结局日−种草日）的中位数；<3 株枯草 THIN 拒判 | 「我的欲望平均活几天？」 |
| **30 天存活率** | 在第 30 天可观察的草中，仍然想要的比例（已表决的按表决龄算，在长且 ≥30 天按活过算，太嫩的如实等） | 「冷静 30 天，还剩几成是真的？」 |
| **两臂后悔对账** | 拔草的按买速分组：冲动臂（≤7 天）vs 沉思臂（>7 天），各组后悔率 = 后悔 y ÷ 已回填；未回填的缺席披露、绝不默认满意；每臂 ≥5 株回填才允许下结论 | 「快买和慢买，哪只手更坑我？」 |
| **学费账** | 学费 = 后悔 y 的已购金额合计；占比 = 学费 ÷ 已购总额；≥ 线（默认 30%）→ REGRET-HEAVY exit 4；枯草省下的钱单独成账——**它是你付给自己的节俭奖金** | 「我的冲动一共烧了多少钱？」 |
| **冷静闸门 check** | 种龄 < 冷却期（默认 14 天）→ STILL COOLING exit 4 + 到期日 + 历史存活率证据；≥ → DECIDE NOW + 两臂后悔率 + 学费占比作证 | 「今晚这株草，我的历史怎么说？」 |
| **拒答优先** | <5 株草拒审（exit 3）；半衰期/存活率/两臂各自有样本下限，不足即 THIN 挂牌不判 | 「这本账够不够格被审计？」 |

五条诚实条款刻在实现里：**账本只记你声称的事实**——价位是你填的心理价签，工具不查电商历史价；**未回填的后悔是缺失的化验单**——它从两臂的分母里退席、在 doctor 里亮黄牌，绝不冒充「买得真值」；**枯草无罪**——没买且不想了是欲望的自然死亡，只进节约账、永不进学费；**闸门不拦人**——check 的 exit 4 只是把你自己的历史拍在桌上，深夜的最终表决权永远在你手里，买完请回填后悔列——**那是下一票的证据，是这本账唯一的皮肤游戏**；**样本不足不下结论**——半衰期要 3 株枯草、存活率要 5 株可观察、两臂各要 5 株回填、设门要 8 笔有价已购，差一株都只肯说 THIN。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash dd:ignore
python3 want_ledger.py report examples/grass.csv --as-of 2026-09-04
```

## 命令速查

```bash dd:ignore
python3 want_ledger.py report grass.csv --as-of 2026-09-04      # 欲望普查：半衰期/存活率/两臂/学费
python3 want_ledger.py check grass.csv --item 机械键盘 --price 899 \
    --seeded 2026-09-01 --today 2026-09-04                      # 冷静闸门：今晚这株草的表决资格
python3 want_ledger.py check grass.csv --item 键盘 --seeded 2026-08-10 \
    --today 2026-09-04 --cool 30                                # 冷却期加严到 30 天
python3 want_ledger.py report grass.csv --as-of 2026-09-04 --tuition-line 50  # 放宽设门线
python3 want_ledger.py doctor grass.csv                          # 数据体检（催交后悔作业）
python3 want_ledger.py report grass.csv --format json            # 机读
```

## 一个真实样例

小禾，一年里种了 22 株草（`python3 examples/build_examples.py` 可从零重建，日期全部钉死，`--check` 逐字节校验）：13 株拔草、7 株枯草、2 株在长，标签横跨数码/家居/健身/厨房/衣服/户外。[`examples/sample-report.txt`](examples/sample-report.txt) 的判决：

```text dd:ignore
the census
  sprouts   : 22 seeded (13 bought · 7 wilted · 2 still growing)
  half-life : a want lives 13.0 days before it wilts (median of 7 wilted)
  30d survival: 19.0% of wants live past day 30 (4 of 21 observable)

two arms of you — regret by buying speed
  impulse    (bought within  7 days)   8 bought, 8 graded: 75.0% regret it
  deliberate (bought after    7 days)   5 bought, 5 graded: 20.0% regret it
  verdict on arms: your hands buy faster than your heart approves — impulse regret
  75.0% vs deliberate 20.0%. Slow is your cheaper gear.

the tuition bill
  tuition    : 5,833.00 bought in regret — 45.9% of everything you bought (line 30%)
  saved by wilting: 8,214.00 of wants you let die — the cheapest purchases you never made

verdict: REGRET-HEAVY — 45.9% of what you bought, you regret buying: 5,833.00 of your
money went to desires that did not survive their own checkout.
```

读法：**你的欲望一半活不过 13 天，只有 19% 能活过 30 天**——「放购物车冷静一下」第一次有了你自己的统计学背书。两臂对账更扎心：**秒杀的 8 株拔草后悔了 6 株（75.0%），想了一个月以上的 5 株只后悔 1 株（20.0%）**——无人机（2,999，飞了两次）和第二双跑步鞋（第一双还在吃灰）都在冲动臂的学费单上；而「想太久会不会错过」的担忧被沉思臂的 20% 部分证伪。学费 5,833 ÷ 已购 12,717 = 45.9%，越过 30% 门禁线，`report` 亮 **REGRET-HEAVY** 并 **exit 4**。然后是深夜那一刷（[`examples/sample-check-cooling.txt`](examples/sample-check-cooling.txt)）：

```text dd:ignore
  sprout    : 机械键盘 · 899.00 · seeded 2026-09-01, age 3 day(s)
  evidence  : of your past wants, 19.0% lived past day 30 (21 observable)
  testimony : impulse regret 75.0% (n=8) · deliberate regret 20.0% (n=5) · tuition 45.9% of spending

verdict: STILL COOLING — age 3 < cooling period 14. Come back on 2026-09-15 and vote.
```

种龄 3 天的草被自己的历史拦下：**按小禾的账本，这株草只有 19% 的概率活到值得买的那天**。同一个键盘，种了 25 天之后再来 `check`（[`examples/sample-check-decide.txt`](examples/sample-check-decide.txt)）就是另一个世界：冷静期已满，**DECIDE NOW exit 0**——证据摆桌，买不买是人的决定，买完回填后悔列。`doctor`（[`examples/sample-doctor.txt`](examples/sample-doctor.txt)）先确认这本欲望账值得被审计。

## dogfood：样例账本即狗粮

```text dd:ignore
$ python3 examples/build_examples.py --check
examples in sync
```

真实消费史天然敏感，本件不内置任何真实消费者的账。dogfood 的形式与仓库传统一致：**四份样例报告由交付代码本身渲染**（`examples/build_examples.py` 走与 CLI 完全相同的代码路径），CI 用 `--check` 逐字节校验——报告里的每一个数字都能从钉死的账本与 `--as-of` 复现，一份手写的样例都不存在。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_wantledger.py`](tests/test_wantledger.py)，`unittest` + 合成账本 + 手工点数的期望值）：

```bash
python3 -m unittest discover -s want-ledger/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 账本解析：中英文表头、结局别名（拔草/枯草/在长/bought/passed/空）、后悔别名（y/是/真后悔/n/不后悔）、价位留空=None、缺表头/坏结局/坏后悔报行号、空行容忍、乱序重排、空品名拒答 | `ParserTests` |
| 结构校验：在长带结局日拒答、已表决缺结局日拒答、结局早于种草拒答（时间旅行）、枯草带后悔拒答（枯草不后悔） | `ValidateTests` |
| 欲望普查：22 株三态计数、半衰期 13.0（7 株枯草中位）、<3 株枯草 THIN、30 天存活率 4/21、<5 可观察 THIN、`--as-of` 时间旅行把后决的草截断为在长、早于首株拒答、默认 as-of=账本末日、<5 株整体拒审 | `CensusTests` |
| 两臂对账：第 7 天整归冲动臂第 8 天归沉思臂、未回填退出分母且计数披露、每臂 <5 株 THIN 拒判、沉思臂更差时反向判决（waiting is not automatically wisdom） | `ArmsTests` |
| 学费账：学费/已购/节约三账（5,833 / 12,717 / 8,214）、无价已购退出金额账并披露、REGRET-HEAVY ≥30% exit 4、<8 笔有价已购不许设门、`--tuition-line` 覆盖 | `MoneyTests` |
| 冷静闸门：种龄 3<14 → STILL COOLING exit 4 + 到期日 + 存活率证据、期满 → DECIDE NOW + 两臂+学费作证、`--cool` 覆盖翻转、`--today` 早于 `--seeded` 拒答、check 永不改写账本 | `CheckTests` |
| doctor：催交后悔作业（回填时滞 ≥7 天亮黄牌）、无价已购黄牌、同日同品重复种草黄牌、<5 株 UNHEALTHY exit 3、枯草过少预告 THIN | `DoctorTests` |
| CLI：无参数 exit 2、文件缺失 exit 3、check 必填参数 exit 2、`--format json` 永不设门（数据不是判决） | `CliTests` |
| **dogfood：样例逐字节同步 + demo 数字独立核对（半衰期 13.0、存活率 19.05%、冲动臂 75%、学费占比 45.87%）** | `DogfoodTests` |

## 项目结构

```
want-ledger/
├── want_ledger.py
├── tests/test_wantledger.py
├── examples/build_examples.py
├── examples/grass.csv
├── examples/sample-report.txt
├── examples/sample-check-cooling.txt
├── examples/sample-check-decide.txt
├── examples/sample-doctor.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
