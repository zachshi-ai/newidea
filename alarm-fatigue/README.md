# 警报疲劳 · Alarm Fatigue

> Flaky test 不是坏测试，是误鸣的火警——误鸣多了，没人再看警报。
> A zero-dependency CLI that reads the patch trail flaky tests leave in git history ("fix flaky" subjects, smuggled skips, wired-in retries, test-only commits) and turns it into an **alarm credit score** per test file — so you know which red lights nobody believes anymore.

---

## 一句话

每个团队都有那么几个测试：红了没人看，新人吓得不敢合并，老人说「rerun 一下就绿了」。这不是测试问题，是**警报系统信用破产**——就像医院里每天误鸣的监护仪：护士最终学会无视它，于是真警报响的时候也没人来（这个现象在医疗安全研究里叫 *alarm fatigue*，它杀死过病人）。`alarm-fatigue` 的立场：**CI 的可信度不取决于测试数量，而取决于最不可信的那个红灯**。flaky test 没有债主、不会报错、永不自然消失，但它每次被「修补」都在 git 历史里留了痕：`fix flaky` 的提交消息、diff 里混进来的 `@unittest.skip`、绕过断言的 `retries = 3`、只改测试不改实现的「调测试」commit。工具把这些痕迹读出来，给每个测试文件记一本**警报信用账**：从没哭过狼的 100 分；被静音、被重试、被反复修补的滑进**失聪区**——那里的红灯只是背景噪音，不是火警。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | CI 守门人 / 平台工程师（「为什么大家都不看红灯了」）；接手成熟代码库的 TL（「哪几个测试是从一开始就不可信的」）；想把 flaky 治理从感觉变成预算的工程负责人。 |
| **场景** | 季度质量复盘（「我们的测试套件信用还剩多少」）；新人 onboarding（「这 47 个红灯里哪几个可以无视」）；flaky 治理立项（「先修哪三个，修复预算按信用分排序」）；CI 门禁（`--fail-under` 拒绝套件中位信用继续下滑）。 |
| **问题** | **误鸣的警报没有账本**：① flaky test 侵蚀的是整个套件的信用，但伤害无法度量——「CI 不稳」永远停留在轶事；② 没人有动力修它（rerun 就绿，修它没人夸），于是它**永生**；③ 最隐蔽的破坏（加 skip、加 retry、删测试、把断言调松）都伪装成正常维护 commit，散落在几千条历史里无人回看。 |
| **价值与意义** | 1) **信用可计算**：五类信号 × 固定罚分 = 0-100 的警报信用，四档判定从 trusted 到 DEAF，修复预算不再靠感觉。<br>2) **读的是痕迹不是问卷**：所有信号来自 git 历史的确定性事实（消息词表、diff 新增行、commit 文件构成），不访谈、不主观打分。<br>3) **墓地说出那句没人敢说的话**：被删除的测试不是「清理」，是**拆掉了警报**——graveyard 记录每个被移除的测试死时的信用。<br>4) **信用不是责任**：认真修好 flaky 根因同样扣分——红灯的消费者只记得它哭过狼，这是信用账本与责任认定的刻意分离。<br>5) **零依赖 + 纯本地**：Python 3.8 标准库 + git，不碰 CI 平台 API，不上传。 |

---

## 核心思想：修补痕迹 → 信号 → 信用账

每个测试文件出生时都带着 100 分信用。此后每一次被「修补」的 commit 都按其**最重的信号**扣分：

| 信号 | 罚分 | 检测方式 | 直觉 |
|---|---|---|---|
| **mute** | -30 | diff 新增行出现 `skip`/`xfail`/`@Disabled`/`t.Skip`/`xit` 等标记 | 警报还挂在墙上，电池被抠了 |
| **focus** | -25 | 新增 `.only(`、`fit(`、`fdescribe(`、`focus: true` | 一次武装自己，静音所有同伴 |
| **retry** | -20 | 新增 `retries = 3`、`flaky(`、`@retry`、`rerunFailures` | 不修警报，改成自动重按 |
| **signal** | -10 | 提交消息命中 flaky 词表（`fix flaky`/`stabilize`/`intermittent`/`rerun`/偶现/随机失败/飘了/修测试） | 消息亲口承认：这个警报误鸣过 |
| **solo** | -5 | 该 commit 只改了测试、没动实现 | 大概率是在「调测试让它过」，不是修 bug |
| **burst** | -10 | 14 天窗口内 ≥3 次修补（`--burst-window`/`--burst-min` 可调） | 修了三次还飘，这不是意外是结构 |

同一次 commit 的其余信号作为 tag 附带展示（`signal + solo`），**不重复扣分**。四档判定：**trusted**（≥80，红了就是火警）/ **shaky**（≥60，rerun 一次再信）/ **habitual**（≥40，rerun 已经不用过脑）/ **deaf**（<40，**红灯失聪区**）。

三条诚实条款刻在实现里：**出生不算修补**——新建测试文件（`A` 状态）永远清白，TDD 不是 flaky；**解除静音是修复不是修补**——mute/retry 只检测新增行，删掉 `skip` 的 commit 不扣分；**删除的测试进墓地**——不进信用账，但 graveyard 会记下它死时的信用，因为拆掉警报比修好它更值得被看见。

## 安装（零依赖）

只需 Python 3.8+ 和 `git`，无需 `pip install` 任何东西。

```bash dd:ignore
python3 alarm_fatigue.py audit           # 你的套件里，哪些红灯已经没人信了？
```

## 命令速查

```bash dd:ignore
python3 alarm_fatigue.py audit                        # 信用总账：每测试文件的罚分史 + 信用 + 判定
python3 alarm_fatigue.py audit --top 30               # 看更多行（默认 15）
python3 alarm_fatigue.py audit --since 2026-01-01     # 只计窗口内的修补（老修补折旧=信用可偿还）
python3 alarm_fatigue.py audit --test-glob 'qa/*.py'  # 追加测试文件定义（默认按文件名模式识别 12 种语言）
python3 alarm_fatigue.py audit --fail-under 60        # 门禁：套件中位信用 < 60 则 exit 4
python3 alarm_fatigue.py audit --format json          # 机读
python3 alarm_fatigue.py explain tests/test_payment.py  # 单个测试的完整修补时间线（逐笔扣分）
python3 alarm_fatigue.py explain tests/test_payment.py --format json
```

## 一个真实样例

三人迷你仓库（`python3 examples/build_examples.py` 可从零重建，作者与全部时间戳钉死，提交哈希跨机器可复现）：dana 的警报一直干净，frank 独自调过一次测试，eva 跟 payment 警报搏斗了一整月。[`examples/sample-audit.txt`](examples/sample-audit.txt) 的判决：

```text dd:ignore
  file                    credit  grade        patches  last        signals
  tests/test_payment.py       20  !! DEAF            4  2026-02-02  mute x1 · retry x1 · signal x2 · burst
  tests/test_search.py        95  OK trusted         1  2026-01-30  solo x1
  tests/test_cart.py         100  OK trusted         0  -           -

  graveyard (alarms removed, not fixed):
    tests/test_legacy.py                      deleted 2026-02-05 · credit at death 70
```

读法：payment 测试在 8 天里被修了三次（burst），随后被接上 retry，最终电池被抠掉（`@unittest.skip`）——信用 20，**失聪区**：它再红也没人看了。而 legacy 测试的死法更隐蔽：先 `xfail` 静音（-30），两周后整个删除——墓地里那句 *credit at death 70* 就是它生前最后的样子。[`examples/sample-explain.txt`](examples/sample-explain.txt) 里 payment 的账本逐笔可查：

```text dd:ignore
  2026-01-12  Eva Edge     d0be781  fix flaky payment test on CI        signal + solo -10  -> 90
  2026-01-15  Eva Edge     b6e85ef  stabilize payment assertions        signal + solo -10  -> 80
  * burst: 3 patches in the 14d window (2026-01-12 .. 2026-01-20)  -10  -> 70
  2026-01-20  Eva Edge     746d050  make payment test tolerant on loa…  retry + solo -20  -> 50
  2026-02-02  Eva Edge     15fe3da  hold payment test on CI for now     mute + solo -30  -> 20

  final: credit 20 · DEAF · first patched 2026-01-12 · 4 attempt(s) later, nobody believes this red anymore
```

## dogfood：审计它自己出生的仓库

```text dd:ignore
-- Alarm Fatigue audit: newidea
  test files alive       : 11
  patched at least once  : 1 (9.1%)
  suite alarm credit     : 100 (median of alive tests)

  witching-hour/tests/test_witchinghour.py    95  OK trusted    1  2026-08-24  solo x1
```

这个「点子实验室」自身的套件信用近乎满分——因为每个点子的验收测试都是一次性写绿交付的，唯一的修补是 witching-hour 那次给测试仓库配置 git 身份的 CI 修复（一次 solo，-5）。这不是炫耀而是说明：**信用账本对「从不修补」与「反复修补」同样如实记账**。等哪一天某个点子的测试开始飘，它自己的工具会第一个看见。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_alarmfatigue.py`](tests/test_alarmfatigue.py)，47 个用例，`unittest` + 真实临时 git 仓库，`GIT_AUTHOR_DATE` 钉死每个时间戳）：

```bash
python3 -m unittest discover -s alarm-fatigue/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 测试文件识别：12 种语言的文件名模式、helpers/conftest/testdata 不误伤、`--test-glob` 追加 | `FilePatternTests`（4 例） |
| 词表信号：英文/中文 flaky 词汇命中；诚实的工作（"retry uploads"、"skip ci for docs"）不误伤；`--signal-regex` 可替换 | `SignalTests`（4 例） |
| diff 标记：skip/xfail/@Disabled/t.Skip/`.only`/`focus: true`/`retries = 3` 等新增行检测；**删除标记（解除静音）不扣分**；普通修改零命中 | `MarkDetectionTests`（5 例）<!-- dd:ignore: 该行为信号标记词列表，非文件引用 -->
| 信用模型：权重排序 mute>focus>retry>signal>solo、同 commit 多信号只按最重扣一次、clean=100、下限 0、四档边界 80/60/40 | `CreditTests`（6 例） |
| burst：14 天内 3 修补触发、分散不触发、窗口与阈值可调 | `BurstTests`（3 例） |
| 归因链：出生（A 状态）不算修补、solo 与 signal 共存只扣一笔、mute/retry/focus 的 diff 级扣分、改实现打破 solo、burst e2e、删除入墓地（含死时信用）、rename 不炸、`--since` 老修补折旧、diff 预算降级 | `GitIntegrationTests`（11 例） |
| 端到端：三人剧本的套件统计（patched/median/deaf）与 JSON 结构 | `ScenarioTests`（2 例） |
| CLI：audit/explain 的 text+json、未知文件 exit 3、非 git 目录 exit 3、无子命令 exit 2、`--fail-under` 门禁 exit 4、`--top` 截断 | `CliTests`（8 例） |
| **dogfood：对本仓库自身 audit/explain 不崩且信用恒在 [0,100]、判定一致** | `DogfoodTests`（3 例） |
| 样例同步：demo 树与两份报告可从零重建且逐字节一致 | `ExamplesSyncTests`（1 例） |

## 项目结构

```
alarm-fatigue/
├── alarm_fatigue.py
├── tests/test_alarmfatigue.py
├── examples/build_examples.py
├── examples/demo-repo/
├── examples/sample-audit.txt
├── examples/sample-explain.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
