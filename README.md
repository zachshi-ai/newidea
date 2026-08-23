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
| 7 | [深夜灯火 · Midnight Oil](midnight-oil/) | 过劳不在问卷里，在 git 时间戳里：按**作者本地挂钟**测出深夜/周末/无休 streak，趋势对比回答「这是常态还是正在燃烧」——在人提离职之前看见信号 | 方法论 + 零依赖 CLI | ✅ 58 tests |

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
python3 -m unittest discover -s midnight-oil/tests
python3 -m unittest discover -s churn-hotspot/tests

# 文档漂移扫描（CI 中亦会运行，见 .github/workflows/docs.yml）
python3 doc-drift/doc_drift.py scan . --exclude demo-repo --exclude gitweek
```

## License

MIT © 2026
