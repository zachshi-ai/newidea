# 孝心工单 · Filial Desk

> 每一通「帮我看看手机」都是一张没有编号的工单；修好从来不是教会，复发才是唯一的回执。
> Every "help me with my phone" call is an unnumbered helpdesk ticket; fixing it is not teaching it — the relapse is the only receipt.

## 一句话

你在异地，爸妈的手机坏了就打给你：弹窗、断网、验证码、莫名多出来的话费。每通电话 10–40 分钟，修完就挂，没有任何账本——「我一年到底花了多少小时当爸妈的免费 IT 部」「上次教过的东西她学会了吗」「爸那台破手机值不值得换」，全凭感觉。`filial-desk` 把每次求助记成一行工单（TSV 手编：日期/谁/什么设备/什么题材/多少分钟/怎么解决的/有没有以教会结束），从同一本账开出五本账：**支持税**——样例一年 52.0 账本周 21 张工单 505 分钟，年化 **8.4 小时/年**（一个完整工作日花在远程运维上；给了 `--hourly 50` 才有钱账：¥420.83/年，一份没人预算过的无薪工资单）；**教会审计**——`taught=yes` 是你的声称，复发是唯一审计：样例 7 次声称，4 次撑过 90 天观察窗坐实 VERIFIED、2 次太年轻单列 OPEN（声称不是信用）、1 次 38 天后被打脸 **TAUGHT-BUT-BACK**（教学伪证）——「修好不是教会」这句话第一次有了回执；**复发链**——同一 (人, 题材) 在滚动 90 天内再犯即复发：爸的手机弹广告一年复发 4 次全部 UNTAUGHT（每次都「修好」，从未「教会」），话费莫名变多恰好第 90 天复发踩线立新案，复发率 33.3%；**设备经济 fleet**——红米 9A 一年吃掉 315 分钟 = 5.25 小时，`--hourly 50 --residual 红米 9A:200` 一对：年支持成本 ¥262.50 > 残值 ¥200，**SUNK exit 4——这台手机比你为它花的时间便宜，换机不是奢侈是摊销**；**教程债 curriculum**——题材级复发 ≥2 即教程债（弹广告 x4、WiFi 断网 x2），写一次图文教程永久摊销，`--tutorials` 清单盖不住的欠账 exit 4；**反事实 simulate**——cure（教程治好弹广告的全部复发：505→385 分钟/年，省 ¥100/年）与 retire（换掉红米 9A：505→190 分钟/年，省 ¥262.50/年），kept + removed == total 恒等式钉死。账本自锚定：缺省 as-of = 账本末日，`--as-of` 可钉死，同一本账任何机器任何一天跑出的结果逐字节一致。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 异地工作的子女——爸妈的「免费 IT 部」。微信打不开、验证码收不到、Wi-Fi 又断了、话费莫名变多，第一反应都是「问问孩子」；你在这头开会、通勤、午休，那头是 WaitFor 解决的一张张工单。 |
| **场景** | 周二下午的工作会议上妈妈的来电（样例：12:30 午休教微信静音）；早上一睁眼爸的电话就进来了（07:30，通勤路上指导卸载）；深夜 23:10 的「手机又弹广告了」；过年回家才发现上次远程没搞定、最后还是运营商上门的那类问题。 |
| **问题** | ① **支持税不可见**：每通电话修完就消失，从无账本——一年 8.4 小时的隐性工资单没人看见，因为它从不入账；② **修好 ≠ 教会**：上次「教了，妈说记住了」，三周后同一问题复发——教学失败没有回执，复发是你唯一的审计证据，而它散落在记忆里；③ **设备经济不可见**：哪台设备是无底洞、一年吃你多少小时、值不值得换机，没人算过——决定全靠情绪；④ **教程债**：复发两次以上的题材，写一次图文教程就能永久摊销，但它永远排在「下次再说」。 |
| **价值与意义** | ① **第一次有账**：支持税 8.4 小时/年从「我挺累的」变成可管理科目，给了时薪才折钱（¥420.83/年），不给就只报分钟——不发明收入；② **教学有审计**：教会率 35.0% 的分母、分子、4 VERIFIED / 2 OPEN / 1 TAUGHT-BUT-BACK 全部摊开——「教会」不是感觉，是撑过 90 天观察窗的复发检验；③ **换机有依据**：SUNK 灯把「那台破手机」翻译成 年支持成本 vs 残值 的一对数字；④ **教程有 backlog**：复发排行就是该写的图文教程清单，写一次、永久摊销；⑤ **诚实条款**：复发不是爸妈笨，是上次教学的失败证据，责任在教的人——这是你的运维台账，不是爸妈的成绩单。 |

---

## 核心思想：修好是止痛，教会才是治愈，复发是唯一的审计

支持父母用手机这件事，做完就消失：没有工单号、没有回访、没有结案标准。本件把它补进账本，并给「帮忙」这件事装上运维世界的两根标尺——**结案标准**（什么是「解决」？修好只是止痛，教会才是治愈）和**回访机制**（怎么知道治好了？90 天内没复发）：

| 概念 | 规则 | 回答的问题 |
|---|---|---|
| **支持税 report** | 账本周 = 首工单所在周一 → 末工单所在周日（含两端）；年化 = 总分钟 ÷ 账本周数 × 52；按人/设备/题材三重分解（分钟加总恒等）；教会账 claimed/judged → VERIFIED（撑过观察窗）/ OPEN（太年轻，声称不是信用）/ TAUGHT-BUT-BACK（被打脸）；夜间求助占比只数记了 clock 的工单；钱是翻译，`--hourly` 才给钱账 | 「我一年花多少小时当爸妈的 IT 部？教的东西真教会了吗？」 |
| **复发审计 relapse** | 复发键 = (人, 题材归一)；滚动链：相邻两张工单间隔 ≤ `--window`（默认 90）天则同链，链头不算复发；复发的上一张标过 taught=yes → **TAUGHT-BUT-BACK**（教学伪证），否则 UNTAUGHT（预期复发）；复发率 > 50% 或伪证 ≥2 → exit 4 | 「上次到底教会了没有？教学失败率多高？」 |
| **设备经济 fleet** | 每设备：票数、分钟、间隔中位、年化小时（按账本周折算）；间隔中位 < `--freq-line`（默认 21 天）→ HIGH-FREQ exit 4；`--residual DEV:金额` + `--hourly` 都给了才有钱账：年支持成本 > 残值 → **SUNK exit 4**；只给残值不给时薪 → 明示「add --hourly」，永不发明钱 | 「这台设备是无底洞吗？该换了吗？」 |
| **教程债 curriculum** | 题材级复发 ≥ `--min`（默认 2）= 教程候选（一次复发可能是运气，两次是模式）；`--tutorials` 清单（一行一个题材，归一化对齐）盖不住的候选 = UNCOVERED DEBT exit 4；复发 x1 的进 WATCH 观察位 | 「该写哪几篇图文教程？写了有没有盖住？」 |
| **反事实 simulate** | `cure --topic T`：该题材的复发全部治愈（链头保留——教一次就该教会）；`retire --device D`：这台设备连人带票消失；kept + removed == total 恒等式钉死；恒 exit 0，红线在 relapse/fleet | 「写了教程 / 换了手机，一年能省多少？」 |
| **账本体检 validate** | 三重恒等式：按人 / 按设备 / 按题材分钟加总 == 总分钟；完全相同的重复行是手抄事故 exit 2；披露 taught 未记录数、clock 覆盖数 | 「这本账配不配得上结论？」 |

三条边界刻在实现里：

- ** taught 是自报，复发才是审计**——你在工单上写「教会了」只是一句声称；账本给每句声称 90 天的观察窗，撑过去才记 VERIFIED，撑不过去记 TAUGHT-BUT-BACK，还没到期的老老实实躺在 OPEN 里。声称不是信用。
- **钱是翻译，不是前提**——不给 `--hourly`，fleet 只报小时、verdict 明写 hours only；只给残值不给时薪，绝不替你定价。支持税的本质是时间，钱只是让它可比较的那一步。
- **账本自锚定**——缺省 as-of = 账本末日，`--as-of` 钉死；所有窗口钉在账本自己的日期上，同一本账在任何机器、任何日期跑出的报告逐字节一致（examples 快照有 CI 字节级校验）。报告只打印账本文件名，绝不回显调用方路径。

---

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash
python3 filial_desk.py report examples/ledger.tsv
```

## 命令速查

```bash
python3 filial_desk.py report     examples/ledger.tsv --hourly 50     # 年化支持税 + 教会审计 + 节奏
python3 filial_desk.py report     examples/ledger.tsv --as-of 2026-01-20  # 钉死 as-of 重放
python3 filial_desk.py relapse    examples/ledger.tsv                 # 复发链 + 教学伪证
python3 filial_desk.py relapse    examples/ledger.tsv --back-line 1   # 伪证零容忍
python3 filial_desk.py fleet      examples/ledger.tsv --residual "红米 9A:200" --hourly 50   # SUNK 判定
python3 filial_desk.py curriculum examples/ledger.tsv                 # 教程债 backlog
python3 filial_desk.py curriculum examples/ledger.tsv --tutorials examples/tutorials.txt  # 覆盖审计
python3 filial_desk.py simulate   examples/ledger.tsv cure --topic 手机弹广告 --hourly 50     # 教程反事实
python3 filial_desk.py simulate   examples/ledger.tsv retire --device "红米 9A"              # 换机反事实
python3 filial_desk.py validate   examples/ledger.tsv                 # 恒等式与披露
```

## 账本格式（可手编 TSV，一行一张工单）

```text
date	parent	device	topic	minutes	mode	taught	clock	note
2025-10-13	妈	iPhone 12	WiFi 断网	25	视频	yes		教了重启路由器，妈说这有什么难的
2025-11-20	妈	iPhone 12	WiFi 断网	20	电话	no	21:40	又断了，这回远程没搞定，运营商上门
2026-08-30	妈	iPhone 12	字体太小	10	电话	no		直接远程替她调好——修好不是教会
```

- 前 5 列必填：`date`（YYYY-MM-DD）/ `parent`（妈/爸/岳母…谁打来的）/ `device`（什么设备）/ `topic`（什么题材，归一化对齐：大小写、空白与标点折叠，`WiFi 断网` 与 `wifi断网` 是同一问题）/ `minutes`（≥1，这张工单吃掉你多少分钟）。
- 后 4 列可选、按位补空：`mode`（电话/视频/远程/现场 或 phone/video/remote/onsite）/ `taught`（yes|是 = 这张票以**教会**结束——是自报，等复发审计；no|否；留空 = 不知道）/ `clock`（HH:MM，来电时刻，喂夜间占比）/ `note`。
- 完全相同的两行是手抄事故，exit 2；同日多工单合法。
- 记录纪律：挂了电话就记一行，30 秒的事；漏记只会低估支持税，宁可低估不虚报。
- **这是你的运维台账，不是爸妈的成绩单**——复发键带「人」是因为教学是人对人的：教妈妈的 WiFi 不覆盖爸的平板。别把这份账给他们看排名，它是给你自己排优先级的。

## 验收标准（全部转为自动化测试，68 个）

1. **解析守卫**：表头缺失、列数（5–9）、坏日期、空 人/设备/题材、分钟（0/负/小数/非整数/空）、非法 mode、非法 taught、clock 格式与越界（24:00）、完全相同重复行、文件不可读、空账——全部 exit 2；注释与空行跳过；中英别名（是/否、电话/视频/远程/现场）归一；5 列最小行合法。
2. **题材归一**：大小写/空白/标点折叠（`Wi-Fi，断网!` ≡ `wifi断网`）；归一键串链、显示名用原始题材（报表永不出现归一键）。
3. **复发链语义**：间隔恰 90 天 = 复发、91 天 = 新链（边界钉死）；滚动链延伸；同题材不同人不成链；taught=yes 后复发 = TAUGHT-BUT-BACK 且伪证归因于**声称那张票**（falsified claim line），untaught 复发不背伪证。
4. **总账口径**：账本周 = 首周一 → 末周日含两端（样例恰 52.0 周）；样例手算钉死 505 分钟 / 8.4 h/年 / 教会率 7/20 = 35.0% / 复发率 7/21 = 33.3% / verified 4 + open 2 + back 1 / 夜呼 2/8 = 25.0% / 四 mode 计数；by-parent/by-device 分钟加总恒等。
5. **诚实条款**：unpriced 全命令可用、无钱行、明示 NOTE；`--hourly 0` 拒绝；fleet 只给残值不给时薪 → 「add --hourly」，永不发明钱；同一账本两次运行逐字节一致。
6. **as-of 剪切**：`--as-of` 截断一切计算（10 张票 257 分钟 21.0 周手算钉死）；切掉所有票 exit 2；边界日含当票。
7. **薄账分层**：<8 票或覆盖 <90 天 → 算术照常出账（票数/分钟/分解/链表），统计判级拒绝 exit 3（report/relapse/fleet 三处一致，stderr 保留 `too thin` 约定）。
8. **门禁**：relapse 复发率 >50% 或伪证 ≥2 → exit 4（`--rate-line/--back-line` 可调，伪证零容忍可设）；fleet HIGH-FREQ（间隔中位 <21 天，样例 31.5 天不触发、40 触发且优先于 SUNK）与 SUNK（262.50 > 200 exit 4，150/h×30 不触发）；curriculum 覆盖审计欠账 exit 4、全盖住 exit 0、题材级 x1 进 WATCH。
9. **反事实**：cure 弹广告 21→17 票、505→385 分钟/年、33.3%→17.6%、省 ¥100/年（手算钉死）；retire 红米 9A 21→10 票、505→190、20.0%；kept+removed==total 恒等式；查无题材/设备 exit 2；恒 exit 0。
10. **exit 语义**：0 正常 / 2 账目或用法错误 / 3 样本不足拒判统计 / 4 红线击穿；simulate 无参用法报错指向 `--topic/--device`。

## 样例输出

见 [examples/](examples/)，由 [build_examples.py](examples/build_examples.py) 从同一本样例账（[ledger.tsv](examples/ledger.tsv)，一年 52.0 账本周、两位老人三台设备 21 张工单：四连复发的弹广告、38 天被打脸的 WiFi、恰 90 天踩线的话费、三句撑过观察窗的声称、和一张「我直接替她调好了」的工单）确定性生成：[sample-report.txt](examples/sample-report.txt)（年化 8.4 h/yr，教会审计全摊开）、[sample-report-hourly.txt](examples/sample-report-hourly.txt)（50 元/时：¥420.83/年的无薪工资单）、[sample-relapse.txt](examples/sample-relapse.txt)（三条复发链，含 +90d 踩线）、[sample-fleet.txt](examples/sample-fleet.txt)（红米 9A SUNK exit 4）、[sample-curriculum.txt](examples/sample-curriculum.txt)（两笔教程债 + 一个 WATCH）、[sample-curriculum-debt.txt](examples/sample-curriculum-debt.txt)（教程清单盖不住 → 欠账 exit 4）、[sample-simulate.txt](examples/sample-simulate.txt)（治好弹广告一年省 2 小时）、[sample-simulate-retire.txt](examples/sample-simulate-retire.txt)（换掉红米 9A 一年省 5.2 小时）、[sample-validate.txt](examples/sample-validate.txt)（三重恒等式 OK）。

## 与近邻的边界

drift-apart 记的是**联系的频率**（友情/亲情的心跳间距），本件记的是**支持的事件与教学的结果**——你可以每周都打电话（心跳健康）却每次都在重复修同一个问题（教学全败）；ghost-login 盘的是**你自己账号的存量攻击面**，本件盘的是**爸妈设备的增量事件流**；search-tax 同用「惯犯/复发」机制但领域是**找不到自己的东西**，本件是**教不会自己的人**——而且复发键是 (人, 题材) 二元组，因为教学不迁移；leave-debt 同守「不发明钱」条款（那边不给月薪只报天数，这边不给时薪只报小时）；full-house 的人时计量同构，但量的是会议、不是亲情。方法论细节见 [METHODOLOGY.md](METHODOLOGY.md)。
