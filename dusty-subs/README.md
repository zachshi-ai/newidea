# 吃灰订阅 · Dusty Subs

> 订阅按「月」向你收费，你的生活按「次」发生。
> A zero-dependency CLI that rebuilds your subscription ledger from a plain bank-statement CSV — periodic-debit detection, the next-12-months payment calendar, price-hike and promo-trap flags — then translates monthly fees into **cost per use**: the only price your life actually pays.

---

## 一句话

订阅是唯一一种「消费在发生时没有支付动作」的支出：首次扣款那天你做了一个决策，之后每一次扣款都只是惯性。银行 app 告诉你这个月花了多少，从不告诉你**下一年已经被谁锁定了多少**；月费 30 听着便宜，只用了 2 次就是每次 15——但你从没见过 15 这个数字，见到的永远是 30。`dusty-subs` 的立场：**月费是幻觉单位，每次使用的价格才是真实价格**。把流水 CSV 交给它，它用三条确定性规则（名字、节奏、金额）从几百笔一次性消费里把周期扣款重建出来，年化、排日历、抓涨价、识破首月促销，然后在你在一张手写的使用清单上填几个数之后，把每个订阅翻译成那句你一直在回避的话：**这个会员，你每次用掉多少钱**。用得起的留下，吃灰的现形——cut 清单合计，就是你一年能赎回的钱。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 订阅制时代的普通消费者（「我一个人到底订了多少服务？」）；年底做财务复盘的家庭管理员；手握一打 SaaS 订阅、被自动续费刺过一刀的自由职业者。 |
| **场景** | 年度财务复盘（导出三年流水，看看到底在为什么持续付费）；收到扣款短信的瞬间（「这 app 我多久没打开了？」）；决定砍哪些订阅之前（按每次使用的价格排优先级，而不是按月费）；涨价通知弹出的当天（它 62 涨到 70，过去三年我一共为它花了多少？）。 |
| **问题** | **订阅的账本不存在**：① 支付与消费解耦——大脑只为「掏钱动作」记账，自动续费没有掏钱动作，于是不记账；② 流水里的订阅是藏在几百笔一次性消费里的**规律信号**，人眼扫不过来，而且描述字段被商户改得面目全非（订单号、电话、国家代码各月不同）；③ 定价单位错位——订阅按月报价，生活按次发生，两个单位之间没有汇率，于是「30/月」永远显得便宜；④ 没有任何报表回答「下一年已经被锁定了多少」。 |
| **价值与意义** | 1) **账本自动重建**：三条确定性规则（商户名归一化 → 间隔规律 → 金额一致）把订阅从流水里捞出来，不靠银行 app 的商户分类，不联网，不上传。<br>2) **未来摊在桌上**：未来 12 个月扣款日历与锁定总额——订阅的本质是对未来的承诺，这份承诺第一次有了数字。<br>3) **汇率建起来了**：接入一张手写的使用清单（商户 + 年使用次数），每个订阅获得唯一可比的价格——每次使用的价格，KEEP / WATCH / CUT 三档，0 次使用的标记 pure dust。<br>4) **痕迹全透明**：涨了多少价、首月促销后真实价是多少、哪些「看起来像订阅」被哪条规则拒绝了、哪些行是重复/坏行——报告逐一说明，不黑箱。<br>5) **纯本地零依赖**：银行流水是最敏感的个人数据，Python 3.8 标准库本地解析，不碰网络。 |

---

## 核心思想：三道关，把订阅从流水里捞出来

一个商户要坐上订阅的席位，必须连过三关。任何一关不过，它和它的拒绝理由一起如实列出——**工具不藏它拒绝的东西**：

| 关 | 规则 | 默认 | 拦下谁 |
|---|---|---|---|
| **名字关** | 描述归一化：小写、去 ≥2 位数字串（订单号/电话/月份戳）、标点变空格 | — | 同一商户被散落成五个「假商户」 |
| **节奏关** | 最大间隔 ≤ 2.05× 中位间隔，且间隔变异系数 CV ≤ 0.35 | `--gap-outlier` / `--gap-cv` | 打车（2.8× 的间隔大洞）、连缺两个月的死号 |
| **金额关** | ≥ 60% 的扣款落在中位金额 ±20% 以内 | `--amount-min` / `--amount-tol` | 间隔规律但金额散的大采购（每周菜钱） |

不足 3 次扣款（`--min-hits`）的商户连参评资格都没有——一次性买 iPhone 的 8999 不该出现在任何账本上。通过的商户得到周期标签（weekly / monthly / quarterly / annual / `182d` 自定义）、年化成本，以及一份锚定在**流水最后一天**（绝不碰墙钟，同一份流水永远预测同一个未来）的未来 12 个月扣款日历。

金额历史还会被审一遍：**涨价**（末次 ≥ 中位(之前)×1.10）、**降价**（≤0.90，该问问是不是降级了）、**促销跳档**（首笔 ≤ 0.8×中位(其余)——试用期价格的真相是后面的每一笔）。

最后一步翻译需要你：手写一张使用清单（商户，年使用次数），工具算出 **cost per use = 年化成本 ÷ 年使用次数**：≤ mpu（默认 15）**keep**；≤ 3× mpu **watch**；超过 **cut**；填 0 的是 **pure dust**——纯灰尘，连价格都算不出来。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash
python3 dusty_subs.py scan examples/demo-data/bank.csv
```

## 命令速查

```bash
python3 dusty_subs.py scan bank.csv                        # 哪些是订阅，各自年化多少
python3 dusty_subs.py report bank.csv --usage usage.csv --ignore 房租
                                                           # 全景：账本+日历+涨价+每次成本
python3 dusty_subs.py explain 超级猩猩 bank.csv --usage usage.csv
                                                           # 单个订阅的完整时间线与预测
python3 dusty_subs.py report bank.csv --format json        # 机读
python3 dusty_subs.py report bank.csv --fail-over 12000    # 门禁：下一年锁定额超线则 exit 4
```

流水 CSV 需要日期、描述、金额三列（中英表头都认：`日期/摘要/金额/类型` 或 `date/description/amount`），银行网银、支付宝、微信账单导出后稍作删减即可；有 `类型` 列就按它过滤收支，没有负号就默认全是支出。使用清单就两列：`商户,年使用次数`（商户名写子串即可，工具会做唯一匹配）。

## 一个真实样例

虚构人物林，三年流水（`python3 examples/build_examples.py` 可从零重建，每个日期与金额钉死，样例逐字节可复现）：八个订阅、两个长得像订阅的干扰项、一笔一次性 iPhone。[`examples/sample-scan.txt`](examples/sample-scan.txt) 的判决（节选）：

```text
  merchant                    hits  cycle           last  annualized  flags
  平安车险-自动续保                      6  182d           2,200    4,412.09  -
  超级猩猩月卡                        36  monthly          299    3,520.48  -
  NETFLIX.COM 8665797172        36  monthly           70      824.19  hike +13% (62 -> 70)
  NOTION LABS INC               36  monthly           36      423.87  promo 4 first, real 36
  OFFICE 365 HOME (MSFT)         3  annual           398         398  -

  periodic-looking, but failed the checks:
    盒马鲜生                        12 hits ~every 84d · amounts too scattered (17% within +/-20% of 194.15)
    滴滴出行                         6 hits ~every 46d · gap 130d is a 2.8x outlier against median 46d
```

填上使用清单之后，[`examples/sample-report.txt`](examples/sample-report.txt) 里的翻译（节选）：

```text
  next-12-months calendar (your future, already sold):
    2026-09         2,649   (6 charge(s))
    2027-03         3,047   (7 charge(s))
    TOTAL          10,498

  cost per use (annualized / uses-per-year, mpu 15; >3x mpu is dust):
    !! CUT  pure dust      平安车险 自动续保
    !! CUT  1,760.24/use   超级猩猩月卡
    ~ watch  18.32/use      netflix com
    OK keep  1.49/use       p9rsk spotify stockholm se

  cutting the dust refunds 8,356.44 a year. The gym is not judging; the ledger is.
```

读法：健身房月卡三年扣了 36 次 299，林一共去过两次——**每次 1,760 块**，这不是会员费，这是纪念品价。车险排第一是因为车卖了保险还在自动续保：pure dust，连除法都做不了。网飞 62 涨到 70 被抓出来，Notion 首月 4 块的试用价后面站着 36 块的真实价。而九月那个 2,649，是下一年已经卖掉的九月。

## dogfood：工具吃自己的狗粮

银行流水是最私人的数据，这份仓库里没有真人账单——dogfood 的方式是让**全部验收测试对已提交的样例流水跑真实 CLI**（不是 mock）：scan / report / explain 的每个关键数字（锁定总额 10,498、cut 回血 8,356.44、健身房每次 1,760.24）都在样例设计时手工核对过，测试钉死这些数字，算法与样例从此互相看住对方。你自己的 dogfood 只需三步：网银导出三年 CSV → `scan` 看账本 → 填一张十行的使用清单跑 `report`。第三个数字（每次使用的价格）出现的那一刻，砍不砍已经不需要工具替你决定了。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_dustysubs.py`](tests/test_dustysubs.py)，56 个用例，`python3 -m unittest discover -s dusty-subs/tests`）：

| 验收标准 | 对应测试 |
|---|---|
| 金额与百分比格式：整数千分位无小数、小数两位、带符号百分比 | `MoneyFormatTests`（3 例） |
| 商户归一化：大小写、≥2 位数字串（订单号/卡尾）、标点折叠、单数字保留 | `NormalizeTests`（4 例） |
| 流水解析：中英表头、类型列三规则（类型列 > 负号 > 全视为支出）、utf-8 BOM、制表符、货币符号与千分位（CSV 引号字段）、四种日期格式、坏行跳过并计数、精确重复行去重并计数、缺列/缺文件/空文件报错 | `ParseTests`（11 例） |
| 识别三关：min-hits 之下不参评、缺缴一月（1.97×）识别、连缺两月（3.0×）以 outlier 拒绝、CV 超限拒绝、间隔规律但金额散拒绝、周期四档 + 自定义 `182d` | `DetectTests`（6 例） |
| 预测与年化：add_months 月末截断（1/31→2/28，闰年 2/29→2/28）、月付钉住同日、自定义周期按中位间隔推、预测锚定流水末日、horizon 截断、同日重复扣款不产生 0 间隔 | `ProjectionTests`（6 例） |
| 价格痕迹：涨价 ≥1.10×中位(前)、降价 ≤0.90×、促销首笔 ≤0.8×中位(余)、平稳无标记 | `MoveTests`（4 例） |
| 使用清单：中英表头与无表头两列、精确匹配后唯一子串匹配、歧义不猜、三档判定边界（≤mpu keep、≤3×mpu watch、>3×mpu cut）、0 次 pure dust、未匹配行与缺失标注如实列出 | `UsageTests`（5 例） |
| 端到端剧本：提交样例的 ground truth（293 行/256 笔支出/12 商户、9 个订阅、房租年化 61,225.81、ignore 后 10,409.56、锁定 72,898→10,498、日历 2026-09=2,649/6 笔、涨价 62→70 +12.9%、每次成本与 cut 回血 8,356.44） | `ScenarioTests`（8 例） |
| CLI：scan/report/explain 的 text+json、`--ignore`、`--fail-over` 门禁 exit 4、无子命令 exit 2、坏文件与未知商户 exit 3 | `CliTests`（5 例） |
| **dogfood：提交样例经真实 CLI 全链路跑通且关键数字与 ground truth 一致** | `DogfoodTests`（3 例） |
| 样例同步：demo 数据与三份报告可从零重建且逐字节一致 | `ExamplesSyncTests`（1 例） |

## 项目结构

```
dusty-subs/
├── dusty_subs.py
├── tests/test_dustysubs.py
├── examples/build_examples.py
├── examples/demo-data/bank.csv
├── examples/demo-data/usage.csv
├── examples/sample-scan.txt
├── examples/sample-report.txt
├── examples/sample-explain.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
