# newidea · 点子实验室

> 一个想法的完整生命周期：**明确谁在什么场景下的什么问题 → 定价值 → 设计 → 定验收标准 → 落地 → 自动化验证 → 文档**。
> 每个点子都是可运行、可测试的成品，不是 PPT。

| # | 点子 | 一句话 | 形态 | 状态 |
|---|---|---|---|---|
| 1 | [决策债务 · Decision Debt](decision-debt/) | 把「悬而未决的决策」当成一笔**会自动计息的债务**来管理 | 方法论 + 零依赖 CLI | ✅ 23 tests |
| 2 | [gitweek · 不可见工作考古](gitweek/) | 从 git 历史确定性重建一周工作全貌，浮出**被周报遗忘的维护性工作** | 方法论 + 零依赖 CLI | ✅ 25 tests |

## 仓库约定

- 每个点子一个子目录，自带 `README.md`（问题定义 / 设计 / 验收标准）、`METHODOLOGY.md`（方法论与 FAQ）、实现、测试、示例。<!-- dd:ignore: 文件名为类型提及，非具体引用 -->
- 零依赖：Python 3.8+ 标准库即可运行，`python3 -m unittest` 即可验证。
- 验收标准全部转成自动化测试，随代码一起交付。

```bash
# 验证全部点子
python3 -m unittest discover -s decision-debt/tests
python3 -m unittest discover -s gitweek/tests
```

## License

MIT © 2026
