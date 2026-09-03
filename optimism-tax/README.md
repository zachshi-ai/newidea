# 乐观税 · Optimism Tax

> 你的 3 天从来不是 3 天——但没人知道它到底是几天，直到把 20 次估算摊在桌上对账。
> A zero-dependency CLI that audits every estimate you have ever made against what actually happened, and turns your own track record into a **personal optimism tax rate** — so the next promise you make is priced from evidence, not guessed from hope.

---

## 一句话

每个排期会上都有一个人说「这个 3 天」，然后全团队按 3 天排期，最后 5 天交付——下个排期会他还是说 3 天，**还是有人信**。这不是性格问题，是行为经济学里的 *planning fallacy*（规划谬误，Kahneman & Tversky 1979）：人对任务的预测系统性乐观，且**从不回头对账**。Jira 记录估时，却从不审计估时者的校准度；你的「3 天」在统计上到底是几天，没有任何一本账记得这件事。`optimism-tax` 就是这本账：每完成一个任务记一张**收据**（你承诺了几天、实际花了几天），账本算出你的**个人乐观税率**——典型一次任务会超出估算多少倍——以及 P80 安全报价、按任务类型的失真分账、校准趋势，和你**已经交出去的总税额**。从此「3 天」这个数字被拆成两半：你**意思上**的 3 天，和你**应该承诺**的天数。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 写估时的开发者（「我每次都说 3 天，每次都干 5 天」）；对客户报工期的负责人（「报价该乘几？」）；按团队估时排期的 TL / PM（「这个人的『完成』到底是什么意思」）。 |
| **场景** | sprint 规划会（报价前先跑 `quote`）；立项报价与合同工期（P80 报价就是「五次里晚一次」的价格）；季度复盘（「我们这个季度给乐观税交了 56 个人日」）；新人导师制（「你进项目的前 10 次估算，先自己看账」）。 |
| **问题** | **估算没有审计**：① 规划谬误人人都有，但工具只记录估算、从不对比实际——「我总低估」永远停留在自我感觉；② 失真是**分类型**的：调研类永远爆、bug 修复基本准、运维类藏 buffer，但没人有账本看清自己的「哪一类不准」；③ 报价没有依据——该报 3 天还是 6 天，全靠当时的勇气，而不是靠自己的历史数据。 |
| **价值与意义** | 1) **税率可计算**：中位膨胀比 = 乐观税率，四档税阶从 calibrated 到 HEAVY，你对团队的排期影响第一次有了数字。<br>2) **报价有依据**：`quote 3` 用你自己的历史告诉你「你嘴里的 3 天，统计上是 3.8 天；要 80% 按时，报 10.3 天」——这是 reference class forecasting（参考类别预测）的个人化落地。<br>3) **失真分类型现形**：全局税率 1.25x 看着无害，分桶后 research 类 3.55x、ops 类 0.71x——前者重税，后者在藏 buffer，**两种失真都要治**。<br>4) **诚实条款刻在实现里**：样本不足拒绝报价、未知 tag 拒绝校准（防 typo 假冒）、离群项目不绑架中位数、半截收据跳过但计数。<br>5) **零依赖 + 纯本地**：Python 3.8+ 标准库，账本就是一个 JSONL 文件，不碰任何项目管理工具的 API。 |

---

## 核心思想：收据 → 税率 → 报价

每张收据是一行 JSONL：`{"estimate": 3, "actual": 5, "tag": "research"}`。它的**膨胀比**（inflation ratio）r = actual ÷ estimate——r=1.0 说到做到；r=2.0 低估一倍；r<1.0 提前完成（也可能是**藏 buffer**）。账本在其上算出五个数：

| 概念 | 定义 | 回答的问题 |
|---|---|---|
| **乐观税率** | r 的**中位数** | 典型的一次任务，会超出估算多少倍？ |
| **P80 报价** | r 的 80 分位数 × 估算 | 要「五次里晚一次」，该承诺几天？ |
| **税阶** | 按税率分档：calibrated(≤1.1) / mild(≤1.5) / standard(≤2.0) / HEAVY(>2.0) | 听你报价的人该给你的数字打几折？ |
| **总税额** | Σ(actual − estimate) | 迄今为止，乐观让你和团队一共垫了多少人日？ |
| **失真分账** | 按 tag 分桶的各自税率 | 你不是整体不准，是**哪一类**不准？ |

**税阶是消费行为的分界，不是统计推论**：≤1.1 你说什么就是什么；≤1.5 听的人留一点 slack；≤2.0 你的数字意味着 +50-100%；>2.0 你说「X 天」，排期的人听到的是「2X 天」。**税率不是绩效分**——它服务的对象是「听你报价排期的人」，不是给你打分的人：税率高说明承诺失真需要校准，不说明能力差，两者刻意分离。

三条诚实条款刻在实现里：**样本不足不出报价**——8 条收据以下，中位数是噪音 pretending to be a track record，`quote` 直接拒绝（exit 3）；**未知 tag 拒绝校准**——`quote 3 --tag resarch`（拼错）会被拒绝而不是静默回退全局，样本薄的已知 tag 才回退，且声明依据；**离群值不绑架税率**——九次 1.5x 加一次 20x 的灾难，税率还是 1.5x（中位数），但 p80 会把灾难的尾巴如实抬进安全报价。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。账本默认是当前目录的 `records.jsonl`。

```bash dd:ignore
python3 optimism_tax.py record --estimate 3 --actual 5 --tag research   # 记一张收据
python3 optimism_tax.py report                                          # 你的乐观税总账
```

## 命令速查

```bash dd:ignore
python3 optimism_tax.py record --estimate 3 --actual 5.5 --tag research --note "OAuth 调研"
                                                     # 每完成一个任务记一张收据
python3 optimism_tax.py report                       # 税率 / 税阶 / 总税额 / 分桶 / 趋势 / 红旗
python3 optimism_tax.py report --format json         # 机读
python3 optimism_tax.py report --fail-under 1.5      # 门禁：税率 > 1.5 则 exit 4
python3 optimism_tax.py quote 3                      # 你嘴里的 3 天，统计上是几天？
python3 optimism_tax.py quote 3 --tag research       # research 类的 3 天（样本够时用该类校准）
python3 optimism_tax.py quote 3 --file team.jsonl    # 换一本账（团队公共账本）
```

## 一个真实样例

三人迷你账本（`python3 examples/build_examples.py` 可从零重建，25 张收据 + 1 张半截收据，全部数字钉死，输出跨机器逐字节可复现）：dana 做 feature、eva 做 research、frank 做 ops，四个月。[`examples/sample-report.txt`](examples/sample-report.txt) 的总账：

```text dd:ignore
  records                 : 25
  median inflation        : 1.25x   <- your optimism tax rate
  p80 inflation           : 3.42x   (the 1-in-5 late quote)
  bracket                 : ~ mild tax      — plan a little slack
  total tax paid          : 56.0 days (sum of actual - estimate across 25 tasks)
  finished early          : 20% of records (ratio < 1)

  per-tag distortion ledger (typical inflation by task type):
    feature          n=9    1.17x median
    research         n=8    3.55x median
    bugfix           n=4    1.00x median
    ops              n=4    0.71x median

  red flags:
    * FRAGMENTED CALIBRATION (p80/median = 2.74x > 2.5) — you are not one tax
      rate, you are several: tag your tasks and read per-tag
```

读法：全局税率 1.25x、税阶 mild，看着人畜无害——但**总税额 56 个人日**，整整一个季度。红旗说「你不是一个税率，是好几个」，分桶立刻现形：feature 类 dana 诚实（1.17x），research 类 eva 的每个 spike 都长到估算的 3.55 倍（重灾区），ops 类 frank 每次提前完成（0.71x）——那不是美德，是**藏 buffer**：他报的数里塞了安全余量，排期后段在空转。于是同一个「3 天」有两种真实价格（[`examples/sample-quote-research.txt`](examples/sample-quote-research.txt)）：

```text dd:ignore
  estimate: 3.0 days, tag=research
  basis   : 8 records tagged 'research'
  median quote (P50): 10.6 days  (3.0 x 3.55)
  safe quote    (P80): 11.8 days  (3.0 x 3.92) — late 1 time in 5
```

「research 要 3 天」这句话在这个团队的真实价格是 **10.6 天**——没有这本账之前，每一次它都被当真。

## dogfood：为什么 newidea 仓库还没有自己的账本

乐观税需要的输入是一本**从未存在过的账**：`newidea` 已交付 12 个点子，但没有一次开发在开工时写下「这个我估 X 天」。这正是本点子要治的病本身——**工具出现之前，没人记收据；没记收据，校准永远无从谈起**。所以仓库自己的账本从本点子开始：从第 13 个点子起，每个点子的开工估算与实际耗时进 `records.jsonl`，攒够 8 张收据时，乐观税会给「在 newidea 开发一个新点子」这件事报出它第一笔有依据的价。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_optimismtax.py`](tests/test_optimismtax.py)，69 个用例，`unittest` + 临时账本文件，CLI 全流程集成）：

```bash dd:ignore
python3 -m unittest discover -s optimism-tax/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 膨胀比 = actual ÷ estimate；r<1（提前完成）与 r=0 合法 | `TestRatio`（4 例） |
| 税率 = **中位数**：单次 20x 灾难不拉飞税率；偶数插值 | `TestTaxRate`（4 例） |
| P80 分位数：单元素、精确命中、线性插值、p80 > median（右偏） | `TestQuantile`（6 例） |
| 失真分账：按 tag 分桶各算税率；薄桶（<3）不给税率只标 thin | `TestTagAccounts`（3 例） |
| 报价：P50/P80 计算；**样本 <8 拒绝**（exit 3）；薄 tag 回退全局并声明依据；未知 tag（typo）拒绝；tag 样本 ≥8 用该类校准 | `TestQuote`（7 例） |
| 趋势：最近 10 条 vs 之前；worsening / improving / flat / unknown 四判 | `TestTrend`（5 例） |
| 红旗：样本不足、碎片化校准（p80/median>2.5）、恶化、藏 buffer（>40% 提前完成）各触发；干净账本零误报 | `TestRedFlags`（6 例） |
| 税阶边界 1.1/1.5/2.0；总税额 = Σ(actual−estimate) | `TestBrackets`（2 例） |
| 账本解析：缺字段 / 非数字 / bool 伪装数字 / 零或负估算全部拒收；坏行跳过且计数；空账本报错 | `TestLedgerParsing`（12 例） |
| CLI：record 追加并提示报价门槛、report 全流程 + json + `--fail-under` exit 4、quote exit 3 拒绝、缺账本 exit 2 | `TestCLI`（13 例） |
| 零依赖：AST 级检查 import 不出标准库白名单 | `TestZeroDependencies`（3 例） |
| **dogfood：样例账本 25+1 行、税率 1.25x、总税额 56.0 天、research 桶 3.55x、quote 端到端、输出确定性** | `DogfoodTests`（4 例） |
| 样例同步：账本与三份样例输出可从零重建且逐字节一致 | `ExamplesSyncTests`（1 例） |

## 项目结构

```
optimism-tax/
├── optimism_tax.py
├── tests/test_optimismtax.py
├── examples/build_examples.py
├── examples/records.jsonl
├── examples/sample-report.txt
├── examples/sample-quote.txt
├── examples/sample-quote-research.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
