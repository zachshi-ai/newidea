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

# 文档漂移扫描（CI 中亦会运行，见 .github/workflows/docs.yml）
python3 doc-drift/doc_drift.py scan . --exclude demo-repo --exclude gitweek
```

## License

MIT © 2026
