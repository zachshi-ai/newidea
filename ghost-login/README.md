# 僵尸账号 · Ghost Login

> 你的攻击面不是你最强的密码，是你忘得最干净的那个账号。
> A zero-dependency CLI that reads a password-vault export (TSV: account / username / password / pw-set date / last login / sensitivity) and scores every account on four auditable zombie factors — how old the password is, how long since *you* last logged in, how many accounts share it, what it guards — so the 2011 forum you forgot in 2013 stops silently vouching for your 2026 inbox.

---

## 一句话

账号只增不减：注册是 30 秒的事，注销永远「明天再说」。你的真实攻击面 = **全部历史账号的总和**，而记忆只覆盖活跃的最近三年——最危险的不是你最好的那个密码，而是十年前注册、和别处共用、绑着主邮箱、你已彻底遗忘的僵尸账号：攻击者拖一个 2011 年的冷门站点，撞库撞的是你 2026 年的主邮箱。`ghost-login` 把这本没人记的账记出来：从一份可手编的密码库导出（TSV）给每个账号算**僵尸分**——四个各 0-25 分、全部可审的因子：密码多久没换（age）、你多久没用它登录过（stale，「从无登录记录」单独记档）、多少账号与它共用同一密码（reuse，一破俱破的多米诺簇）、它守着什么（sens）。三档判定：**SOUND**（<40，活着）/ **MUSTY**（40-59，受潮）/ **ZOMBIE**（≥60，统计意义上你永远不会再来登录，但它还握着你的一份资料）。外加：复用簇明细（**vital 落在簇里时单独亮牌**——簇里任何一处拖库，一破俱破）、**主邮箱暴露度**（多少僵尸拿你的身份根当找回通道）、最弱密码熵，以及 `simulate drop N`——动手前先看注销前 N 名僵尸的代价单。报告永不回显明文密码，只显示 sha256 指纹；删不删、改不改是你的决定；但没有清单，清理永远不会开始。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 上网十年以上、账号三位数的人——「密码都交给管理器/浏览器记」的人；从没做过数字大扫除的人；看到拖库热搜只想着「还好我密码够强」的人；想清数字足迹却对着密码管理器 423 行记录不知从哪下手的人。 |
| **场景** | 又见「XX 论坛 800 万条数据泄露」的热搜，你想不起自己是否注册过它；换手机号/主邮箱时，想不起哪些老账号还挂着旧找回通道；季度末想做一次「账号大扫除」，需要一份**从哪删起**的排序，而不是凭感觉挑顺眼的删。 |
| **问题** | **账号清单这个问题，第一次被认真问的时候答案已经是「不知道」**：① 注册无摩擦、注销高摩擦，存量只涨不跌，攻击面随年限单调膨胀，而人的心智清单只覆盖最近三年；② 真正的危险评分和直觉相反——直觉看「密码强不强」，现实看「账号老不老、久没用没用过、和谁共用、守着什么」：一个 2011 年设置、从未复登的弱密码论坛号，比一个上周设置的唯一强密码更接近你的主邮箱；③ 密码复用是**一破俱破的多米诺簇**，但没有任何工具回答「谁和谁共用」——尤其当簇里躺着银行；④ 主邮箱是身份的根，却可能正被一群僵尸账号当着找回通道。 |
| **价值与意义** | 1) **攻击面从感觉变成清单**：12 个账号 → 4 SOUND · 4 MUSTY · 4 ZOMBIE，第一次有了一个可以归零的数字。<br>2) **四因子各自可审**：age / stale / reuse / sens 每个 0-25 分、规则写在明处（每 2 年 +5、每静默年 +8、每复用伙伴 +8、vital 25/normal 12/trivial 4）——判决不是黑盒，是四张可以逐项反驳的收据。<br>3) **簇 = 一破俱破**：3 个簇、12 个账号里 7 个在簇上；**vital 在簇里**单独亮牌——「一处拖库、银行陪葬」这件事必须在你删除清单之前看见。<br>4) **主邮箱暴露度**：zhou@mail.com 挂在 4 个账号名下，其中 3 个是僵尸——「crack a ghost, own the identity root」第一次有了计量。<br>5) **simulate drop N**：注销前 N 名僵尸的代价单（僵尸数、簇、暴露度、均分前后对比），先看账再动手。<br>6) **零依赖 + 纯本地 + 不回显**：Python 3.8 标准库；报告只出现 sha256 指纹前 8 位，明文密码永不出账本。 |

## 与仓库近邻的边界

- **vs 静默扣款 silent-debit**：都从「设置后遗忘」的存量里挖账。silent-debit 的账本是**钱**（银行流水 → 惯性账单，对手是涨价），本件的账本是**身份**（密码库导出 → 僵尸账号，对手是拖库）；订阅死了亏一笔月费，僵尸账号死了丢的是主邮箱这个身份根。
- **vs 积灰订阅 dusty-subs**：dusty-subs 管**还在扣费的服务**（关系仍在持续），本件管**还在放着的凭证**（身份碎片早已失联）；一个回答「这个订阅还要不要续」，一个回答「这个账号还该不该存在」——两个问题在「设置后遗忘」的存量表面汇合，在损失类型处分开。
- **vs 承诺锈蚀 todo-rot**：都判「僵尸」。todo-rot 用 2× 承诺半衰期判**永远不会被偿还的承诺**，本件用 60 分线判**永远不会被再次登录的账号**；一个管写出去的支票，一个管交出去的身份——共同点是：超过某个统计门槛后，「明天再说」在概率上等于「永远不做」。

---

## 核心思想：四因子，三档线

从每行一个账号（`name / username / password / pw_set / last_used / tier`）确定性导出：

| 因子 | 刻度（0-25） | 回答的问题 |
|---|---|---|
| **age** | 密码每 2 年未换 +5，25 封顶（10 年即满） | 这把钥匙用了多少年了？ |
| **stale** | 每静默 1 年 +8，25 封顶；**从无登录记录记 18**（「never」档） | 你上次用它是什么时候——还想得起来吗？ |
| **reuse** | 每多一个共用此密码的账号 +8，25 封顶 | 它倒下时拖几个垫背？ |
| **sens** | vital 25 / normal 12 / trivial 4 | 它守着什么？ |

总分 0-100。三档判定线：**SOUND**（< 40，活着，正常维护）/ **MUSTY**（40-59，受潮——开始发霉，还在伸手可及处）/ **ZOMBIE**（≥ 60，统计意义上你永远不会再来登录，但它还握着你的一份资料、你的一个用户名、可能还有你的找回邮箱）。60 分线的意义是可解释的组合：一个 10 年没换密码（25）+ 3 年未登（25）+ 一处复用（8）的普通账号就刚好越线——四个因子**不必全坏**，够老够静默就足以致命。判定线是**记账的阈值，不是风险评估的终点**：删不删、先删谁、要不要顺手改密，仍是你的决定。

两条配套刻度：**复用簇**按密码精确匹配聚簇，簇内任何一处拖库即全簇沦陷——vital 落在簇里时单独亮牌；**密码熵**（位数 × log₂ 字符集，NIST 800-63B 的「长度优先」立场）只做辅助标尺：< 28 bits 弱 / 28-45 中 / > 45 强。注销清僵尸，**改密才拆簇**——两种修复不可混淆。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash dd:ignore
python3 ghost_login.py report vault.tsv      # 僵尸分排行 + 攻击面摘要
```

账本格式（TSV，`#` 注释，首行表头可选；从密码管理器导出后整理，或直接手编）：

```text dd:ignore
name      username      password        pw_set      last_used  tier
OldForum  zhou@mail.com hunter22        2011-03-01  -          normal
EmailMain zhou@mail.com Corr3ct-Horse!9 2024-02-01  2026-08-29 vital
```

`pw_set` = 密码**最后一次设置**的日期（不是注册日——天天登录的老账号上周改过密码就不老）；`last_used` = 你自己最近一次登录，`-` 表示记录上从未复登；`tier` = vital（钱、身份、工作）/ normal / trivial。「今天」默认取账本最大日期，`--today` 可拨表——账本是确定性的，时钟也是。

## 命令速查

```bash dd:ignore
python3 ghost_login.py report vault.tsv                 # 僵尸分 + 攻击面摘要
python3 ghost_login.py report vault.tsv --format json   # 机读
python3 ghost_login.py report vault.tsv --fail-zombies 3  # 门禁：ZOMBIE >= 3 则 exit 4
python3 ghost_login.py report vault.tsv --primary me@x.com  # 指定主身份（默认取最高频用户名）
python3 ghost_login.py clusters vault.tsv               # 谁和谁共用密码
python3 ghost_login.py simulate vault.tsv drop 3        # 注销前 3 名僵尸的代价单
python3 ghost_login.py validate vault.tsv               # 账本体检
```

## 两个真实样例

两份密码库、两种诊断（`python3 examples/build_examples.py` 可从零重建，逐字节可复现）。**zhou** 网龄 11 年、12 个账号、从未清理过——[`examples/sample-report-zhou.txt`](examples/sample-report-zhou.txt) 的判决：

```text dd:ignore
  grades                 : 4 SOUND · 4 MUSTY · 4 ZOMBIE
  reuse clusters         : 3  (7 of 12 accounts share a password)
  vital in a cluster     : yes — 2 cluster(s) hold a vital account
  primary identity       : zhou@mail.com (4 accounts · 3 zombie(s) behind it)
  weakest password       : StreamVideo  26.6 bits (weak)

  ZOMBIE — score >= 60: statistically, you are never logging in again
  score 76  CloudDrive   vital   ZOMBIE   #e16f29ae  zhou@mail.com
    set 2016 · never re-logged · age 25 · stale 18 · reuse 8 · sens 25
  score 71  OldForum     normal  ZOMBIE   #20d2fe5e  zhou@mail.com
    set 2011 · never re-logged · age 25 · stale 18 · reuse 16 · sens 12
```

读法有四层。**其一，直觉的排序是反的**：zhou 最得意的 EmailMain（强唯一密码、天天登录）30 分 SOUND，而 2016 年设置、从未复登、还和 NewsSite 共用密码的网盘账号 76 分全库最高——**它守着的是 vital**。**其二，簇是暗沟**：[`examples/sample-clusters-zhou.txt`](examples/sample-clusters-zhou.txt) 里三簇七号，两个簇里躺着 vital——`Tidy!Quilt7Lamp` 同时是银行 App 和一个水电缴费站的密码，后者 48 分 MUSTY、7 年前的密码从未换过：**拖垮一个缴费站，陪葬的是银行**。**其三，主邮箱是身份根**：zhou@mail.com 挂在 4 个账号名下，其中 3 个僵尸——找回链接的目的地正是攻击者的目的地。**其四，注销和改密是两种修复**：[`examples/sample-simulate-drop3.txt`](examples/sample-simulate-drop3.txt) 显示注销前 3 名僵尸后，僵尸归零的**同时** hunter22 簇还活着（PizzaApp + MusicSite 仍在共用）、银行与缴费站的簇纹丝不动——「Zombies are removed by deletion; clusters only by a password change.」对照组 **mei**（[`examples/sample-report-mei.txt`](examples/sample-report-mei.txt)）：3 个账号、密码全唯一、银行密码去年刚换——3 SOUND · 0 簇，verdict 只剩一句话：你的簇问题不存在，保持。

## dogfood：数字从哪来，就由谁验证

本件与仓库同源：README 与样例里的每一个数字（76 / 71 / 65、7 of 12、3 zombie(s) behind it、26.6 bits、49.8 → 42.8……）都由同一个 CLI 生成，`python3 examples/build_examples.py --check` 保证提交的两份账本与四份样例输出逐字节可复现，验收套件里的 `DogfoodTests` / `ExamplesSyncTests` 每次跑测试都重新验证这条链。账本里是演示用的假密码；工具对你真实导出的承诺只有一条——**报告永不回显明文**（测试套件里有专门的用例拿明文密码在全部三份输出里做缺席断言）。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_ghost_login.py`](tests/test_ghost_login.py)，74 个用例，`unittest`，夹具数字全部手工验算）：

```bash
python3 -m unittest discover -s ghost-login/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 熵算术：8 位纯数字 = 26.6 bits（weak）、字母+数字 8 位 = 41.4（fair）、四类字符按 95 求对数、只计出现的字符类、28/45 档位边界 | `EntropyTests`（5 例） |
| 账本解析：注释/表头/空行、第 6 列缺省 normal、`-` = 从未复登、坏 tier/坏日期带行号报错、空密码拒收、重名账号拒收且报首次出现行号、空账本与缺文件、同密码多账号放行 | `VaultParseTests`（10 例） |
| 因子刻度：age 每 2 年 +5（1.99y → 0，整 2y → 5，10y+ 封顶）、pw_set 在未来钳 0、stale 缺失记 18、静默 1.08y → 8、5y+ 封顶、未来日期钳 0、reuse 每伙伴 +8 封顶 25、sens 三档映射、三档判定边界（39/40/59/60） | `ScoreFactorTests`（8 例） |
| zhou 夹具钉死：CloudDrive 76（25+18+8+25，簇 2）、OldForum 71（簇 3）、NewsSite 65、MusicSite 63、BankApp **38 SOUND**（vital 不拖好账号下水）、计数 4/4/4、排序降序、最弱 StreamVideo 26.6 bits、never_logged=3 及警告、vital 簇覆盖 {CloudDrive, NewsSite, BankApp, UtilityBill} | `ZhouFixtureTests`（11 例） |
| 主身份：默认取最高频用户名（zhou@mail.com 4 次）、并列按字典序、`--primary` 覆盖生效 | `PrimaryTests`（2 例）+ `ZhouFixtureTests` |
| **报告不回显明文**：五组真实密码在 text / clusters / json 三类输出中全部缺席；同密码同指纹 | `FingerprintTests`（2 例） |
| 报告渲染：表头快照逐字钉死、ZOMBIE 区块降序且因子行逐字钉死、verdict（有僵尸 / 无僵尸两分支）逐字钉死 | `ReportTextTests`（4 例） |
| 簇明细：三簇尺寸与 vital 亮牌逐字钉死、footer 条件化（vital 簇「start from the vital one」/ 普通簇「any member」）、无簇分支 | `ClustersTests`（3 例） |
| simulate：drop 3 全表钉死（dropped 名单、grades 4/4/4→1/4/4、簇 3→2、暴露 4→1、均分 49.8→42.8）、drop 4 剩 1 簇（**删不掉 Tidy 簇——银行与缴费站仍共梗**）、drop 0 无操作、超额 drop 有 note、无僵尸分支 | `SimulateTests`（6 例） |
| 门禁：--fail-zombies 4 触发 exit 4、5 放行 | `GateTests`（2 例） |
| validate：行数/唯一用户名/pw_set 区间/as_of 逐字钉死、未来日期行警告 | `ValidateTests`（2 例） |
| CLI 契约：report/clusters/simulate/validate、缺文件与坏行 exit 3、坏 --today exit 3、坏场景与负数 drop 与无子命令 exit 2、--primary 透传 | `CliTests`（10 例） |
| 样例同步：[`examples/build_examples.py`](examples/build_examples.py) `--check` 逐字节 | `ExamplesSyncTests`（1 例） |
| dogfood：提交的账本重跑 CLI 必须逐字节复现四份样例输出；JSON 恒等式（score ≡ 四因子之和、ZOMBIE ≥ 60、SOUND < 40、同指纹同簇尺寸） | `DogfoodTests`（5 例） |

## 项目结构

```
ghost-login/
├── ghost_login.py
├── tests/test_ghost_login.py
├── examples/build_examples.py
├── examples/zhou-vault.tsv           # zhou：11 年网龄 12 账号，4 ZOMBIE / 3 簇
├── examples/mei-vault.tsv            # mei：对照账本，3 SOUND / 0 簇
├── examples/sample-report-zhou.txt
├── examples/sample-report-mei.txt
├── examples/sample-clusters-zhou.txt
├── examples/sample-simulate-drop3.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
