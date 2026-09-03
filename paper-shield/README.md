# 纸盾 · Paper Shield

> 备份的绿色对勾是软件的自我表扬：它证明「任务跑过了」，不证明「数据回得来」。
> Paper Shield — a zero-dependency ledger that splits "I have backups" into three auditable layers: they exist, they verify, they restore. A backup never tested by restore is a wish.

---

## 一句话

「我有备份」是这个时代最普遍的安全错觉：备份软件每天亮绿勾，网盘图标挂着同步完成的标记，直到硬盘异响、误删相册、勒索软件落锁的那一天你才发现——**绿勾只证明「任务跑过了」，不证明「数据回得来」**。备份的死亡是无声的：外接盘三个月没插上、NAS 空间满了静默失败、云订阅悄悄欠费、同步把误删也同步了；而三份「备份」可能全在同一块 NAS、同一个账号体系、同一间屋子里——**冗余在纸面上，不在物理上**。`paper-shield` 把「有备份」拆成可审计的三层信任：**存在（backup：任务跑过）→ 可信（verify：hash 校验/试读抽样）→ 可恢复（drill：真还原过文件）**——绿勾只覆盖第一层。工具从两本可手编的 TSV（目标账：目标/内容域/介质/存放地/周期；事件账：日期/目标/事件）确定性算出：**新鲜度三档**（FRESH ≤1× 周期 / STALE >1× / ROTTEN >2×——错过一次是人祸，错过两次是静默断链）、**3-2-1 审计**（按内容域聚合：副本 ≥3、介质 ≥2、异地 ≥1——同屋 NAS 和 office 抽屉都不算异地，勒索软件和火灾够不着的才算）、**灾难推演**（`simulate dead <介质>`：它今天全灭，每个内容域还剩几份、最坏丢最近多少天——RPO 第一次有了你自己的数字）、**演练史**（8 个备份目标、1 次恢复演练：恢复流程的第一次彩排排在了灾难当天）。诚实条款刻在实现里：账本只记你声称的事实、它不扫描磁盘——所以 verify 与 drill 才是唯二的硬通货；无周期不判新鲜度（UNKNOWN）；宁可 GREEN 不喊狼来。

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 有数字资产（照片库、作品源文件、代码仓库、证件扫描件、家庭视频）的创作者、自由职业者与普通家庭；「备份 = Time Machine 转圈 + 网盘自动同步」的每个人；帮父母配置过「重要文件备份」的子女。 |
| **场景** | 硬盘开始异响的那个下午；误删相册后打开网盘，发现同步早已把删除也同步了；NAS 空间满了，备份任务静默失败三个月；想给备份体系做年度体检；纠结「要不要再买一块盘 / 再订一个云」。 |
| **问题** | ① **存在性错觉**：绿勾是软件的自我表扬，备份第一次恢复失败通常发生在你唯一需要它的那天——此前每一天它都「看起来在工作」；② **静默断链**：备份的死亡没有通知——盘没插、订阅到期、空间爆满、路径变了，错过一个周期是意外，错过两个周期已经是另一份账本；③ **假冗余**：三份副本全在一类介质、一个账号体系、一间屋子里——纸面 3-2-1，物理 1-0-0，火灾/盗窃/勒索软件一次全收；④ **恢复从未排练**：恢复流程只在灾难当天第一次执行——缺权限、缺软件、密码在旧手机里，全部在那天集中爆发；⑤ **RPO 无概念**：「会丢多少」没人算过——最新可用副本是三天前的，你最坏丢三天，这件事应该在灾难前知道。 |
| **价值与意义** | ① **三层信任拆解**：backup / verify / drill 三种事件把「有备份」从一句话变成三个可审计的刻度，绿勾的含金量第一次被标定；② **新鲜度三档**：ROTTEN 的门槛是 2× 周期——它抓的不是「忘了备份」而是「备份体系已经断了而你不知道」；③ **3-2-1 按内容域审计**：冗余是内容的属性不是设备的属性，逐域回答「这份东西真丢得起吗」；④ **灾难推演**：`simulate dead disk` 把「假如笔记本今天被偷」变成逐域的副本清单与 RPO 数字——「剩几份」回答活不活得成，「丢多少天」回答疼不疼；⑤ **演练记账**：drill 过的才算盾，没 drill 过的算愿望——且 drill 不需要灾难，每月随手还原一个文件即可；⑥ 零依赖 + 纯本地 + `--today` 钉死逐字节可复现。 |

## 核心思想：把「我有备份」换成「它存在、它可信、它可恢复」

| 概念 | 规则 | 回答的问题 |
|---|---|---|
| **三层信任** | backup（任务跑过）→ verify（校验过：hash/试读）→ drill（真还原过文件） | 「绿勾之外，还有什么证据？」 |
| **新鲜度** | 距上次 backup：≤1× 周期 FRESH；>1× STALE；>2× ROTTEN（静默断链） | 「这份副本还活着吗？」 |
| **3-2-1 审计** | 按内容域聚合：副本 ≥3、介质 ≥2、异地 ≥1（offsite/cloud 才算异地） | 「这份内容真丢得起吗？」 |
| **灾难推演** | `simulate dead <介质>`：该介质全灭后逐域重算副本/介质/异地与 RPO | 「它死了之后，我还剩什么？」 |
| **RPO** | 最坏丢失窗口 = 今天 − 存活副本中最新的 backup | 「最坏丢最近几天？」 |
| **演练史** | 每 target 的最近 verify / drill 距今；从未 drill 全局点名 | 「恢复流程排练过吗？」 |
| **样本纪律 UNKNOWN** | 无周期或无 backup 事件不判新鲜度 | 「这本账够不够格下判断？」 |

三条设计立场刻在实现里：**账本不扫描磁盘**——它只记你声称的事实，所以 verify/drill 才是唯二硬通货，工具如果假装能替你验证，绿勾的错觉只会换一个软件继续；**ROTTEN 定在 2× 周期**——错过一次是人祸（出差、忘带盘），错过两次是断链（盘坏了/订阅停了/路径变了），断链的副本已经不是你以为的那份；**异地只有 offsite 和 cloud**——同屋的 NAS 会被同一场火灾搬走，直连的盘会被同一款勒索软件加密，异地副本的唯一标准是「灾难摸不到它」。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

## 命令速查

```bash dd:ignore
python3 paper_shield.py audit targets.tsv events.tsv --today 2026-09-04   # 3-2-1 审计 + 三层信任分级（红 → exit 4）
python3 paper_shield.py fresh targets.tsv events.tsv                      # 逐目标新鲜度榜
python3 paper_shield.py simulate targets.tsv events.tsv dead disk         # 灾难推演：disk 全灭之后
python3 paper_shield.py drills targets.tsv events.tsv                     # 验证与演练史
python3 paper_shield.py validate targets.tsv events.tsv                   # 两本账体检
python3 paper_shield.py terms                                             # 3-2-1 与 RPO 术语速查
```

两本可手编的 TSV（Tab 分隔）。目标账——一个目标一行，同一块物理盘承载多个内容域就记多行（推演按介质连坐）：

```
目标	内容域	介质	存放地	周期天
硬盘·照片	photos	disk	home	7
照片云	photos	cloud	cloud	7
```

事件账——只有三种事件：`backup`（任务跑过）、`verify`（校验过：hash/试读）、`drill`（真还原过文件）：

```
日期	目标	事件	备注
2026-09-01	硬盘·照片	backup	每周例行
2026-05-20	文档云	drill	还原了 3 份合同 PDF，用时 25 分钟
```

## 一个真实样例

阿May（虚构人物），自由插画师，8 个备份目标、3 个内容域（photos / art / docs），见 [examples/targets.tsv](examples/targets.tsv) 与 [examples/events.tsv](examples/events.tsv)。2026-09-04 她做了一次审计：

```
纸盾审计 · 8 个备份目标 · 3 个内容域 · 13 条事件

  内容域      副本  介质             异地  最新备份   从未验证           判定
  art         3    disk/nas         0      3 天前 硬盘·作品、NAS·作品、工位冷备盘  ✗ RED（ROTTEN；从未验证；无异地）
  docs        2    cloud/nas        1      5 天前 —                 ✗ RED（3-2-1 不达标（副本 2<3））
  photos      3    cloud/disk/nas   1      2 天前 照片云            ✗ RED（ROTTEN（NAS·照片 静默断链）；从未验证（照片云））

判定  RED —— art、docs、photos 需要行动
```

（完整输出：[examples/sample-audit.txt](examples/sample-audit.txt)，exit 4）注意 **photos**：三个副本、三种介质、含异地——纸面 3-2-1 满分的教科书配置，却是 RED。因为 NAS·照片 已经 26 天没有成功的 backup（周期 7，2× 门槛 = 14 天）——空间满了，任务静默失败，绿勾停在 8 月 9 日；而唯一 FRESH 的照片云**从未 verify 过**——它看起来最新，但它只是「声称」最新。**看起来最安全的内容域，藏着最典型的两种病。**

灾难推演回答另一个维度的问题（[examples/sample-simulate-disk.txt](examples/sample-simulate-disk.txt)）：

```
灾难推演 · 「disk」今天全灭（3 个目标：工位冷备盘、硬盘·作品、硬盘·照片）

  art      剩 1 份 · 介质 nas · 异地 0 · 最坏丢最近 26 天（RPO）（从未验证：NAS·作品）
  docs     剩 2 份 · 介质 cloud/nas · 异地 1 · 最坏丢最近 5 天（RPO）
  photos   剩 2 份 · 介质 cloud/nas · 异地 1 · 最坏丢最近 2 天（RPO）（从未验证：照片云）
```

移动硬盘被偷只是一场演习：art 的三份副本瞬间只剩一份、从未验证、不在异地——**副本的冗余是给灾难准备的，不是给平时看的**。换成 `simulate dead cloud`（云跑路/封号，[examples/sample-simulate-cloud.txt](examples/sample-simulate-cloud.txt)）：docs 只剩那份已经断链 5 天边缘的 home NAS，全部内容域异地归零。`drills` 给出最后一层真相（[examples/sample-drills.txt](examples/sample-drills.txt)）：8 个目标、1 次恢复演练——「恢复流程的第一次彩排排在灾难当天」。

## 与哪些点子不混淆

- 与 **ghost-login**（僵尸账号）：都是个人数据的安全，但僵尸账号管**攻击面**（别人进得来吗：旧密码、复用、找回通道），纸盾管**存活性**（灾难之后你拿得回来吗：副本、验证、演练）。一个防贼进门，一个防房子塌了没地方住。
- 与 **slow-leak**（暗漏）：都抓「静默失败」，但暗漏管房子的用量账单（数据是自动计量、连续的），纸盾管备份事件（数据是手工声称、离散的）——所以暗漏靠同比对照，纸盾靠事件信用：账本不扫描磁盘，verify/drill 才是硬通货。
- 与 **expiry-cliff**（到期悬崖）：都是「名义有效 ≠ 真有效」，但悬崖管会过期的凭证（护照/保单，失效时间是外界规定的），纸盾管会断链的副本（备份的失效是静默自发的）——一个倒数到已知的日子，一个不知道哪天已经断了。
- 与 **dusty-subs**（吃灰订阅，WIP）：订阅账管「钱花了没用上」，纸盾管「以为在保护、其实在裸奔」——网盘订阅照付不误和备份真的可恢复，是两本账。

## 验收标准（已全部转成自动化测试）

| # | 标准 | 测试 |
|---|---|---|
| A1 | 目标账解析：坏行带行号 exit 2（列数/重复目标/存放地非法/周期非法）；周期留空或 `-` 合法（不判新鲜度） | `test_a02`–`test_a06` |
| A2 | 事件账解析：坏行带行号 exit 2（列数/日期/未来日期/目标不在目标账/事件类型非法） | `test_a07`–`test_a12` |
| A3 | 空目标账或空事件账 exit 3；注释行（#）与空行跳过 | `test_a13`–`test_a15` |
| B1 | 新鲜度三档：FRESH（≤1× 周期）/ STALE（>1×）/ ROTTEN（>2×） | `test_b01`–`test_b03` |
| B2 | 边界钉死：恰 1× FRESH、恰 2× STALE、2×+1 ROTTEN | `test_b04` |
| B3 | UNKNOWN：无周期或无 backup 事件不判；距今天数照给 | `test_b05`、`test_a06` |
| C1 | 3-2-1：副本数、介质种数、异地（offsite/cloud）逐项聚合 | `test_c01` |
| C2 | 假冗余：三副本同介质不达标；office 不算异地；offsite 与 cloud 都算 | `test_c02`–`test_c04` |
| D | 验证/演练信用：never_verified 列表、verified 有记录、drilled 计数 | `test_d01`–`test_d03` |
| E1 | audit 门禁：ROTTEN / 从未验证 / 3-2-1 不达标 → RED exit 4，三种文案齐 | `test_e01` |
| E2 | 全绿账本 GREEN exit 0；免责声明恒在（含红灯） | `test_e02`、`test_e03` |
| F1 | simulate dead：逐域 RPO 钉死（2/26/5 天）、从未验证注记、被推掉的目标点名 | `test_f01` |
| F2 | 单介质内容域 → 全灭文案 exit 0；死介质不存在 exit 3 并列出现有介质；非法场景 exit 2 | `test_f02`–`test_f04` |
| G | drills：零演练全局点名（灾难当天首演）；有演练计数（1/8）与距今 | `test_g01`、`test_g02` |
| H | validate 计数（目标/事件/分型）；terms 覆盖全部术语 | `test_h01`、`test_h02` |
| I | `--today` 钉死输出逐字节可复现；`--version` exit 0 | `test_i01`、`test_i02` |
| J | 示例端到端：photos 纸面 3-2-1 满分却 RED（ROTTEN + 云从未验证）；fresh 三档齐；drill 1/8 | `test_j01`–`test_j03` |

```bash dd:ignore
python3 -m unittest discover -s paper-shield/tests   # 43 tests
python3 paper-shield/examples/build_examples.py      # 重建全部样例（钉死 --today，逐字节可复现）
```

## 仓库结构

```text dd:ignore
paper-shield/
├── README.md            # 本文件：问题定义 / 设计 / 验收标准
├── METHODOLOGY.md       # 方法论：三层信任、2× 断链门槛、异地判据、FAQ
├── paper_shield.py      # 零依赖 CLI（Python 3.8+ 标准库）
├── tests/
│   └── test_paper_shield.py  # 43 个验收测试
└── examples/
    ├── targets.tsv            # 示例目标账：阿May 8 个备份目标 3 个内容域
    ├── events.tsv             # 示例事件账：13 条 backup/verify/drill
    ├── build_examples.py      # 样例重建器（钉死 --today，逐字节可复现）
    └── sample-*.txt           # 6 份子命令真实输出
```

## License

MIT © 2026
