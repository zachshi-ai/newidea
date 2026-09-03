# 求职漏斗 · Job Funnel

> 拒绝大多是静默的，而大脑把每一份沉默都读成一次「你不行」。
> A zero-dependency CLI that keeps one row per application and turns the pile into a measurable funnel: stage conversion with confidence lower bounds, channels ranked by proof instead of luck, and a personal silence deadline mined from your own reply latencies.

---

## 一句话

找工作是一个转化问题，但你拿到的反馈几乎是零：大多数投递石沉大海，少数拒信不含任何原因，于是全部 69 份投递的沉默被大脑压缩成一句笼统的判决——「我不行」或「市场不行」。这句判决既无法定位问题，也无法指导行动。`job-funnel` 的立场：**求职是一根会漏水的管子，你的问题不是水压不够，是从来没人告诉你漏水点在哪一环**。工具从一张手编的投递 CSV 里算出三本账：**漏斗账**——投递→回复→面试→offer 逐环转化率，每环配 Wilson 置信下界，让 0/12 和 0/40 不再被当成同一个 0%，最站不住的一环就是漏水点；**渠道账**——每个渠道按下界排行而不是按运气排行，你最重仓的渠道常常不是被证明最好的那个；**沉默账**——从你自己的响应延迟里挖出 P90 沉默线，超过线的 pending 统计上已经死了，关掉它们，分母才诚实。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 被裁或主动跳槽、投了几十份简历没有回音的工程师/职场人；帮朋友改简历却说不清「问题在简历还是在面试」的热心人；带应届生复盘秋招的导师。 |
| **场景** | 周日晚上复盘本周投递（「投了 20 份、0 回音，下周该改简历、换渠道、还是继续投？」）；收到第 N 封拒信后自我怀疑（「是我不行还是渠道不对？」）；盯着一堆 pending 等待（「这家 17 天没回音，还有戏吗？」）；面试辅导（「该练表达还是该改简历？」）。 |
| **问题** | **拒绝是静默、复合且无信息的**：① 大多数投递没有任何回音——不是「拒」，是「消失」，等待没有任何语义；② 大脑把漏斗的每一环都压缩成一句对**整个人**的判决，而漏斗其实有四环（投递→回复→面试→offer），笼统印象无法定位漏水点；③ 小样本的率会撒谎——内推 3 次成 1 次的「33%」和海投 100 次 2% 的「差」都不是它们看起来的样子，渠道选择于是退化为迷信；④ pending 永远挂在心上——没有一条「可以安心关掉」的客观线，账本只进不出，转化率永远虚高。 |
| **价值与意义** | 1) **漏斗账**：`funnel` 把 69 份投递折成三行转化率，每行配 Wilson 置信下界——样本不足的环节标 THIN，它的率只是传闻；站得住的环节里下界最低的就是**漏水点**，直接回答「该改简历还是该练面试」。<br>2) **渠道账**：`channels` 按下界排行——2/2 的猎头漂亮但站不住（THIN），5/12 的内推才是**被证明的最好渠道**；「努力冠军 ≠ 被证明冠军」的错配被点名，65% 的力气在贫矿上一目了然。<br>3) **沉默账**：`aging` 从你自己的首次回复延迟里挖出 P90 沉默线（样例里 17 天），超过线的 pending 标 EXPIRED——「统计上它已经死了」是一个可以拿来安心的客观判决，关掉 7 条死账后真实的转化率才浮出来（25.5% → 22.6%）。<br>4) **零依赖 + 纯本地**：Python 3.8 标准库，`--as-of` 钉死即逐字节可复现，求职数据敏感，一份都不出电脑。 |

---

## 核心思想：给每个率配一个「它最差能有多差」

求职分析的全部错误，都来自把**原始转化率**当**事实**。2/3 的猎头渠道「66.7%」压过 5/12 的内推「41.7%」——但前者只发生了 2 次，后者的下界其实更结实。工具的三条诚实原则：

| 概念 | 规则 | 回答的问题 |
|---|---|---|
| **Wilson 下界** | 每个转化率都配 95% 单侧置信下界 `wilson_lb(k, n)`，排行与「最弱环节」判定全部用下界而不是原始率 | 「这个率最差能有多差？站得住吗？」 |
| **THIN 门** | 机会数 `n < min-n`（默认 10）的环节/渠道标 THIN：它的率是传闻不是事实，**永远不参加**「最弱环节」「被证明冠军」的判定 | 「这条率的样本够说话吗？」 |
| **样本饥饿** | 所有环节都 THIN 时不给任何漏水点判决，只给「先加量，后优化」——样本不足时的优化是迷信 | 「现在该优化还是该攒样本？」 |
| **沉默线** | 你自己所有有回音投递的首次延迟 P90（最近邻秩）；已知样本 < 5 时退回借来的默认 21 天并在报告里**声明出处** | 「等多久才算它死了？」 |
| **两本分母** | 漏斗只用已决投递（decided）做分母，pending 不进来稀释；但 aging 会告诉你「关掉死账后分母怎么变」——观察和手术分离，关不关仍是你的决定 | 「我的率现在是多少？埋了死账之后呢？」 |
| **渠道分母** | 渠道的 `n` 含 pending 与 withdrawn——它们是真实发生的尝试；pending 只能拉低不能拉高一个渠道的率，所以排行是保守的 | 「我的力气花在哪，哪被证明有效？」 |

四条边界刻在实现里：**offer 即到达**——拒了 offer 也算 funnel 的 offer 层，本工具测量的是获取能力，不是接受决策；**withdrawn 不进漏斗**——你主动结束的不算漏斗杀的；**沉默线的 10% 代价**——P90 线内 90% 的投递会有回音，线外仍约有 10% 会复活，EXPIRED 是止损线不是死亡判决书；**嵌套分母**——漏斗三环的分母是嵌套的（面试层的分母是回复层），环节间的比较是描述性的，METHODOLOGY 里写明了它的边界。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash dd:ignore
python3 job_funnel.py funnel applications.csv --as-of 2025-12-01
```

## 命令速查

```bash dd:ignore
python3 job_funnel.py funnel ledger.csv                         # 漏斗账：哪一环在漏水
python3 job_funnel.py funnel ledger.csv --as-of 2025-12-01      # 钉死参照日 → 逐字节可复现
python3 job_funnel.py funnel ledger.csv --min-n 5               # 放宽 THIN 门
python3 job_funnel.py channels ledger.csv --endpoint interview  # 渠道排行：换成功口径
python3 job_funnel.py aging ledger.csv --as-of 2025-12-01       # 沉默账：谁已死、谁还活着（有过期 exit 4）
python3 job_funnel.py show ledger.csv "Hexagram Tech Senior"    # 单条投递完整时间线
python3 job_funnel.py funnel ledger.csv --format json           # 机读
python3 job_funnel.py aging ledger.csv --redact                 # 公司名哈希脱敏，报告可外发
```

## 一个真实样例

李默，32 岁后端工程师，9 月初被裁。11 周里投出 69 份：海投 45、内推 12、猎头 3、官网 9。11 月底签了 Hexagram Tech，12 月 1 日他用 `job-funnel` 复盘这 11 周（`python3 examples/build_examples.py` 可从零重建，日期全部钉死，`--check` 逐字节校验）。[`examples/sample-funnel.txt`](examples/sample-funnel.txt) 的判决：

```text dd:ignore
  ledger     : 69 applications · 55 decided · 12 pending · 2 withdrawn · 1 offer

  stage                      n  passes     rate   wilson lo
  applied -> response       55      14    25.5%       15.8%   <- weakest proven stage
  response -> interview     14       6    42.9%       21.4%
  interview -> offer         6       1    16.7%        3.0%  (thin)

  weakest proven stage : applied -> response (wilson lo 15.8%)
                         the wall is up front: resumes are not turning into conversations —
                         interview polish cannot fix a funnel that leaks before anyone answers.
```

读法：他怀疑了两个月的「我面试表达不行」被数据否决——面试关 42.9% 站得住，墙在**最前面**：55 份简历只换来 14 次对话。 offer 层只有 6 次机会，标 THIN，那 16.7% 只是传闻。然后是渠道账（[`examples/sample-channels.txt`](examples/sample-channels.txt)）：

```text dd:ignore
  channel              n  success  pending     rate   wilson lo
  recruiter            3        2        1    66.7%       20.8%  (thin)
  referral            12        5        1    41.7%       19.3%   <- proven best
  board               45        6        7    13.3%        6.3%
  careers              9        1        3    11.1%        2.0%  (thin)

  effort champion : board — 45 of 69 applications (65%)
  proven champion : referral — wilson lo 19.3% vs the incumbent's 6.3%
  mismatch        : board carries the volume while referral outperforms it ~3.1x —
                    correlation is not cause (referrals arrive pre-vetted), but
                    the budget is upside-down
```

读法：猎头的 66.7% 只发生了 3 次，标 THIN 压不住场面；**被证明的最好渠道是内推**，而 65% 的力气投给了下界只有它 1/3 的海投。最后是沉默账（[`examples/sample-aging.txt`](examples/sample-aging.txt)）——沉默线是从他自己的 22 次回复延迟里挖出来的 P90 = 17 天：

```text dd:ignore
  silence deadline : 17d (P90 of 22 applications answered)
  pending          : 12 applications · 7 expired beyond the line · 5 still alive

  Solango   Backend Engineer   board  2025-10-21   41d  EXPIRED — silent past the line; …
  Forge Works  Embedded Backend  referral  2025-11-24   7d  alive

  7 pending are past your silence line — close them and the honest response rate
  reads 25.5% -> 22.6%. A ledger that never buries anything measures nothing.
  gate: ACTION — close the dead, keep the alive waiting
```

[`examples/sample-show.txt`](examples/sample-show.txt) 里那条 offer 的完整档案：投递到首响 3 天（沉默线 17 天）、渠道快照、判定「offer — the whole point of the funnel」，一屏读完。

## dogfood：样例账本即狗粮

```text dd:ignore
$ python3 examples/build_examples.py --check
examples in sync
```

求职数据天然敏感，本件不内置任何真人数据。dogfood 的形式与仓库传统一致：**四份样例报告由交付代码本身渲染**（`examples/build_examples.py` 走与 CLI 完全相同的代码路径），CI 用 `--check` 逐字节校验——报告里的每一个数字都能从钉死的账本与 `--as-of` 复现，一份手写的样例都不存在。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_jobfunnel.py`](tests/test_jobfunnel.py)，58 个用例，`unittest` + 合成账本）：

```bash
python3 -m unittest discover -s job-funnel/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 账本解析：中英文表头别名、最小三列、BOM 与空行、四种日期写法、outcome 词表中英别名与空值默认 pending、未知 outcome/回复早于投递/空公司/空渠道报行号、无表头报错、文件缺失 | `ParserTests`（11 例） |
| Wilson 下界：0/12 与 0/0 为 0、三个已知值、下界恒不高于原始率、成功率单调、同比率大样本下界更紧、最近邻秩 P90 | `WilsonTests`（6 例） |
| 漏斗：pending/withdrawn 不进分母、三环计数与率、漏水点 = 站得住环节的下界最低者、THIN 环节永不判漏、min-n 门三档、全员 THIN → 样本饥饿判决、全 pending 空漏斗、JSON 载荷 | `FunnelTests`（8 例） |
| 渠道：分组计数（n 含 pending/withdrawn）、THIN 渠道可登顶但不判冠军、被证明冠军跳过 THIN、endpoint 三档切换、努力冠军/被证明冠军/错配同行、冠军一致行、全 THIN「none yet」、JSON 载荷 | `ChannelTests`（8 例） |
| 沉默账：P90 线从已知延迟挖出、样本不足退回借来的默认并声明、age == 线存活 / 线 +1 过期边界、按年龄降序、关死账后率的重算、exit 4 与 ACTION 门、全存活 exit 0 与 CLEAR 门、报告声明线出处、JSON 载荷 | `AgingTests`（9 例） |
| 单条档案：唯一子串匹配、pending 等待判定（线内 alive / 线外 EXPIRED）、渠道快照行、歧义 exit 3、无匹配 exit 3、`--redact` 哈希公司名 | `ShowTests`（6 例） |
| CLI：无参数 exit 2、`--as-of` 非法 exit 3、`--as-of` 缺省今天、funnel 表不泄漏公司名、子进程退出码（aging 4 / 文件缺失 3） | `CliTests`（5 例） |
| **dogfood：样例逐字节同步 + 样例故事数字核验 + 提交账本交叉核对** | `DogfoodTests`（3 例） |

## 项目结构

```
job-funnel/
├── job_funnel.py
├── tests/test_jobfunnel.py
├── examples/build_examples.py
├── examples/applications.csv
├── examples/sample-funnel.txt
├── examples/sample-channels.txt
├── examples/sample-aging.txt
├── examples/sample-show.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
