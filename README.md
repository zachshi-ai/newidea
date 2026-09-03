# newidea · 点子实验室

> 一个想法的完整生命周期：**明确谁在什么场景下的什么问题 → 定价值 → 设计 → 定验收标准 → 落地 → 自动化验证 → 文档**。
> 每个点子都是可运行、可测试的成品，不是 PPT。

| # | 点子 | 一句话 | 形态 | 状态 |
|---|---|---|---|---|
| 1 | [决策债务 · Decision Debt](decision-debt/) | 把「悬而未决的决策」当成一笔**会自动计息的债务**来管理 | 方法论 + 零依赖 CLI | ✅ 23 tests |
| 2 | [gitweek · 不可见工作考古](gitweek/) | 从 git 历史确定性重建一周工作全貌，浮出**被周报遗忘的维护性工作** | 方法论 + 零依赖 CLI | ✅ 26 tests |
| 3 | [文档漂移 · Doc Drift](doc-drift/) | 给文档装上「编译器」：引用失效自动红灯，过期声明自动催审 | 方法论 + 零依赖 CLI | ✅ 46 tests |
| 4 | [知识单点 · Bus Factor](bus-factor/) | 把「这段代码只有一个人懂」变成可测量的风险账本：谁在独守哪些文件，他离开的**爆炸半径**有多大 | 方法论 + 零依赖 CLI | ✅ 62 tests |
| 5 | [承诺锈蚀 · TODO Rot](todo-rot/) | TODO 是写给未来的支票：用已偿还承诺的寿命算出项目的**承诺半衰期**，超过 2× 半衰期还没还的就是**僵尸承诺**——统计意义上永远不会被偿还 | 方法论 + 零依赖 CLI | ✅ 65 tests |
| 6 | [变更热点 · Churn Hotspot](churn-hotspot/) | 前五件都在「发现问题」，这件回答**先修哪个**：hotspot score = churn × size 找出每季度真实流血最多的文件，趋势轴再告诉你谁在恶化、谁在自愈（**自愈的别投预算**） | 方法论 + 零依赖 CLI | ✅ 40 tests |
| 7 | [深夜灯火 · Midnight Oil](midnight-oil/) | 过劳不在问卷里，在 git 时间戳里：按**作者本地挂钟**测出深夜/周末/无休 streak，趋势对比回答「这是常态还是正在燃烧」——在人提离职之前看见信号 | 方法论 + 零依赖 CLI | ✅ 59 tests |
| 8 | [危险时刻 · Witching Hour](witching-hour/) | 每个 bug 都有两个时间戳：**写下它的那一刻**，和**发现它的那一刻**——工具只给你第二个。本件用 blame 把 fix 删掉的行归因回**出生时刻**，风险比 RR 回答「几点写下的代码单位返工率最高」 | 方法论 + 零依赖 CLI | ✅ 38 tests |
| 9 | [讲台时刻 · Stage Time](stage-time/) | 超时不是在台上发生的，是写稿那一刻就注定的：**口播单位**模型（数字逐位、代码逐字符、翻页换气计入）在分享前夜告诉你会不会超时；超时按**牺牲优先级**删（客套先死、论证永生），主张句藏在 64% 处照样亮红灯 | 方法论 + 零依赖 CLI | ✅ 36 tests |
| 10 | [复现那杯 · Rebrew](rebrew/) | 你以为在调参，其实在抽奖：先量出**复现半径**（同配方重复冲的评分波动 = 你的手抖幅度 σ̂），再排**旋钮排行**，σ̂ 超线就拒绝调参建议——把玄学冲煮变成厨房里的单因素实验 | 方法论 + 零依赖 CLI | ✅ 91 tests |
| 11 | [警报疲劳 · Alarm Fatigue](alarm-fatigue/) | flaky test 不是坏测试，是**误鸣的火警**——误鸣多了没人再看警报。本件从 git 修补痕迹（fix flaky 词表、混入的 skip、绕道的 retry、只改测试的 commit）重建每个测试的**警报信用账**：从没哭过狼的 100 分，被静音重试反复修补的滑进**失聪区**——那里的红灯只是背景噪音，不是火警 | 方法论 + 零依赖 CLI | ✅ 47 tests |
| 12 | [加量红线 · Redline](redline/) | 伤病不住在跑量里，住在跑量的**斜率**里：四周慢性负荷当刻度盘、本周急性负荷当指针，给身体装一个**转速表**（ACWR 甜区 0.8–1.3、红线 1.5）；出门前先模拟计划转速并给出甜区余额，伤停后不给爆表的比率、给 40/60/80/100% 归队阶梯——校准门/归零重启/判据冻结三条规则把 ACWR 的三种著名误用结构性挡住 | 方法论 + 零依赖 CLI | ✅ 108 tests |
| 13 | [乐观税 · Optimism Tax](optimism-tax/) | 你的 3 天从来不是 3 天：每完成一个任务记一张收据（估算 vs 实际），账本算出**个人乐观税率**（中位膨胀比）与 P80 安全报价——全局 1.25x 看着无害，总税额已 56 人日；分桶后 research 类 3.55x 重灾区、ops 类 0.71x 在藏 buffer，规划谬误第一次有了对账的地方，报价从此有据可依 | 方法论 + 零依赖 CLI | ✅ 69 tests |
| 14 | [社交时差 · Social Jetlag](social-jetlag/) | 「困」把两本账记成一笔：睡眠债（睡了多久）与社交时差（睡在钟面哪里）。本件从可手编的睡眠日志算出 MSW/MSF 两只钟、\|SJL\| 是否越过 2h 流行病学红线、扣掉还债超睡后的 MSFsc、年化睡眠债与周末还债率；再用三个反事实（flat/target/anchor）分离两本账——**钟的病别用早睡治** | 方法论 + 零依赖 CLI | ✅ 60 tests |
| 15 | [每穿成本 · Cost Per Wear](cost-per-wear/) | 衣服的真实价格 = 吊牌价 ÷ 穿的次数，但购买决策只看了第一本账。本件从换季快照清单算出 CPW 排行（1200 的风衣穿 96 次后每穿 12.5，699 的衬衫只穿 1 次每穿 699）、衣柜坟场与**沉睡资金**（49.6% 的投入在睡觉，含 180 天豁免期）、品类堆积区、品类×季节覆盖矩阵，再加**剁手模拟器**：购物车逐条过堆积否决与孤儿否决——「第 8 件白 T」在下单前就被拦下，扔与不扔仍是人的决定 | 方法论 + 零依赖 CLI | ✅ 49 tests |
| 16 | [漏带时刻 · Left Behind](left-behind/) | 漏带不是在机场发生的，是装箱那一刻就注定的：通用清单是「平均人」的清单，它不记得你上次忘了什么。本件把每次行程记成「物品×行程」错题本——同一物品漏带两次是**盲区**、反复原样往返的是**幽灵货物**、前后半程漏带率不降反升说明**清单没在迭代**——`pack` 生成的下一张清单由你的错误喂养：盲区置顶、常备在列、惯犯幽灵降级到「想清楚再带」 | 方法论 + 零依赖 CLI | ✅ 74 tests |
| 17 | [到期悬崖 · Expiry Cliff](expiry-cliff/) | 名义有效期会撒谎：护照还剩 5 个月，对多数目的地已经等于零。本件给「会静默失效的凭证」（护照/驾照/保单/域名/证书）记一本**提前量调整的 validity 账本**：有效剩余 = 到期日 − 提前量 − 今天，按谁先坠崖排行；出行窗口对全部凭证过闸（一份失效 exit 4）；再从多段有效期里挖出你自己的**续期节奏**（每 ~10 年、惯常提前 46 天）——「现在办是早是晚」第一次有个人基线 | 方法论 + 零依赖 CLI | ✅ 39 tests |
| 18 | [贡献错觉 · Contribution Gap](contribution-gap/) | 「这个家总是我在撑」：双方自报的家务贡献之和常年超 100%，各自都在真心高估（Ross & Sicoly）。本件把家务记成分钟账本，给四个读数——**实测份额**、**公平基尼**（总账 0.033 balanced 可同时挂 5 个部门垄断）、**领地清单**（厨房归她、户外归他，该轮换的是部门不是全家）、**感知对账**（自报 70% vs 实测 53.3%，全家感知盈余 +30 分），28 天趋势让下滑先于争吵被看见——它不裁判谁更爱这个家，它回答：你们吵的是同一个家吗 | 方法论 + 零依赖 CLI | ✅ 96 tests |
| 19 | [渐行渐远 · Drift Apart](drift-apart/) | 友谊没有关机动画：它不会突然死亡，只会把聊天记录的日期越拉越远。本件按**各自的圈层节奏**（核心 30 天/老同学 365 天）给每段关系记**欠费账**，挖**沉默斜率**（间隔翻倍是漂移的领先指标，比「上次联系是去年」早半年亮灯）和**单程指数**（最近五次全是你发起的关系，你一停它就停），修复清单把 7 天内的**生日门**置顶——那是唯一不需要理由的开口机会；联系与否永远是人的决定，账本只拒绝继续沉默 | 方法论 + 零依赖 CLI | ✅ 62 tests |
| 20 | [稍后永不 · Later Never](later-never/) | 稍后读的「稍后」统计意义上就是「永不」：收藏按钮是注意力唯一**只刷不还的信用卡**，点星即结算焦虑、代价全部延期。本件从手编 TSV 账本量出**消化半衰期 t½**（中位口径，收藏后 2×t½ 没读大概率永不）、封棺/断代两种读法的**老化曲线**、近一季摄入/消化速度，再给出没人回答过的结论——收藏 ≥ 阅读时**清空 ETA = ∞**（你不需要更努力地读，需要更少地收藏）；手术单按「越老越死（>4×t½）+ 类型幻觉」给出归档名单，收 ≥10 条且读率 <20% 的 tag 被点名为**幻觉类型**——为理想自我收藏的实锤，扔与不扔仍是你的决定 | 方法论 + 零依赖 CLI | ✅ 48 tests |
| 21 | [续命账 · Repair Ledger](repair-ledger/) | 修还是换从来不是报价 vs 新机价——修买的是残命、新机买的是整条命，可比的只有**边际每服务年成本**。本件把每笔维修记成续命收据：师傅宣称「再战三年」由你的维修史自动对账成**画饼系数**（median 实际/宣称，样例 0.49——三年按一年半听）、同一台机器实际续命越修越短亮**续命递减**灯、累计维修（含本次报价）追平购价触发**沉没护栏**直接判废；FIX / REPLACE / SCRAP 三裁决带 exit code 可进脚本——舍不得的感情溢价第一次被标了价：每留一年，多付 64% | 方法论 + 零依赖 CLI | ✅ 66 tests |
| 22 | [余燃 · Afterburn](afterburn/) | 那杯拿铁下午三点就喝完了，火到半夜还没熄：直觉把咖啡因当**饮用事件**，身体把它当**持续浓度**（半衰期 ~5h）。本件从可手编的摄入账本算出**就寝残留**（逐杯贡献分解，越 50mg 红灯 exit 4）、`cutoff` 闭式反解**今天最晚几点前喝完这杯**（额度尽时诚实说「窗口已关」而非给负时间）、稳态晨基线（天天喝的你醒来就带着昨天的余燃——「没醒透」由此有解）、戒断推演（头痛达峰 20–51h 排进你的日历）；半衰期与阈值全可调——同一杯咖啡，快代谢者绿灯、慢代谢者红灯，**基因不是道德问题，是参数** | 方法论 + 零依赖 CLI | ✅ 56 tests |
| 23 | [僵尸账号 · Ghost Login](ghost-login/) | 你的攻击面不是最强的密码，是忘得最干净的账号：注册 30 秒、注销永远明天再说，攻击面随年限单调膨胀，而记忆只覆盖活跃的最近三年——2011 年注册、和别处共用、绑着主邮箱的僵尸账号，正是拖库撞库通向你 2026 年身份根的暗道。本件从密码库导出给每个账号算**僵尸分**（四因子各 0-25 全部可审：密码每 2 年未换 +5、每静默年 +8、从无登录记录记 18、每复用伙伴 +8、vital 25/normal 12/trivial 4）：12 个账号 → 4 SOUND · 4 MUSTY · 4 ZOMBIE；复用簇精确聚簇、**vital 落在簇里单独亮牌**（拖垮缴费站陪葬银行）、主邮箱暴露度给「身份根被几个僵尸当找回通道」计量、`simulate drop N` 动手前先给注销代价单——注销清僵尸，**改密才拆簇**；报告永不回显明文，指纹即身份 | 方法论 + 零依赖 CLI | ✅ 74 tests |
| 24 | [求职漏斗 · Job Funnel](job-funnel/) | 投出去的简历石沉大海，大脑把每一份沉默都读成一次「你不行」。本件把求职记成一本漏斗账：投递→回复→面试→offer 逐环转化率配 **Wilson 置信下界**（0/12 和 0/40 不是同一个 0%，样本不足的环节标 THIN、永不判漏，全员 THIN 时判决「先加量，后优化」）；渠道按下界排行——2/2 的猎头漂亮但站不住，5/12 的内推才是**被证明的最好渠道**，「努力冠军 ≠ 被证明冠军」的错配被点名（65% 的力气在下界只有冠军 1/3 的贫矿上）；沉默线从你自己的回复延迟里挖出（P90），超过线的 pending 统计上已经死了，关掉 7 条死账后真实的转化率才浮出来（25.5% → 22.6%）——「该改简历还是该练面试」从玄学变成三行账 | 方法论 + 零依赖 CLI | ✅ 58 tests |

## 仓库约定

- 每个点子一个子目录，自带 `README.md`（问题定义 / 设计 / 验收标准）、`METHODOLOGY.md`（方法论与 FAQ）、实现、测试、示例。<!-- dd:ignore: 文件名为类型提及，非具体引用 -->
- 零依赖：Python 3.8+ 标准库即可运行，`python3 -m unittest` 即可验证。
- 验收标准全部转成自动化测试，随代码一起交付。

```bash
# 验证全部点子
python3 -m unittest discover -s decision-debt/tests
python3 -m unittest discover -s gitweek/tests
python3 -m unittest discover -s doc-drift/tests
python3 -m unittest discover -s bus-factor/tests
python3 -m unittest discover -s todo-rot/tests
python3 -m unittest discover -s witching-hour/tests
python3 -m unittest discover -s midnight-oil/tests
python3 -m unittest discover -s churn-hotspot/tests
python3 -m unittest discover -s stage-time/tests
python3 -m unittest discover -s rebrew/tests
python3 -m unittest discover -s alarm-fatigue/tests
python3 -m unittest discover -s redline/tests
python3 -m unittest discover -s optimism-tax/tests
python3 -m unittest discover -s social-jetlag/tests
python3 -m unittest discover -s cost-per-wear/tests
python3 -m unittest discover -s left-behind/tests
python3 -m unittest discover -s expiry-cliff/tests
python3 -m unittest discover -s contribution-gap/tests
python3 -m unittest discover -s drift-apart/tests
python3 -m unittest discover -s later-never/tests
python3 -m unittest discover -s repair-ledger/tests
python3 -m unittest discover -s afterburn/tests
python3 -m unittest discover -s ghost-login/tests
python3 -m unittest discover -s job-funnel/tests

# 文档漂移扫描（CI 中亦会运行，见 .github/workflows/docs.yml）
python3 doc-drift/doc_drift.py scan . --exclude demo-repo --exclude gitweek
```

## License

MIT © 2026
