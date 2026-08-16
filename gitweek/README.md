# gitweek · 不可见工作考古

> 从 git 历史确定性重建「我上周到底做了什么」，并浮出**周报最容易遗忘的那部分——维护性工作**。
> A zero-dependency CLI that reconstructs your week from git history and surfaces the invisible work (test / docs / refactor / chore) your weekly report forgets.

---

## 一句话

写周报时你能想起来的，往往是本周最大的那个新功能和最惊险的那次救火；而**修 bug、补测试、写文档、升依赖、重构**这类让系统活着的工作——往往占一周的一半以上——会被记忆系统性抹掉。`gitweek` 把这些工作从 git 历史里**挖**出来，摆在你面前：一行命令，一份如实反映工作结构的周报草稿。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 软件工程师、技术负责人——同时在多个仓库工作、需要定期产出周报 / 双周报 / 述职材料的人。 |
| **场景** | 周五下午（或绩效季）要回答「这周我做了什么」。工作散落在 3~10 个仓库：写代码的主仓库、修文档的内部库、提 PR 的开源项目。 |
| **问题** | **记忆对工作量的估计有系统性偏差**：新功能大而可见，容易被记住；测试、文档、重构、杂务小而分散，会被「_DURATION bias_（时长低估）」和「峰终定律」抹掉——但它们恰恰是维持系统不塌方的部分。逐个仓库翻 `git log` 费时且同样只看到「大石头」。结果：周报失真 → 维护工作在团队里持续不可见 → 没人愿意做维护 → 系统加速腐化。 |
| **价值与意义** | 1) **如实还原**：一行命令跨仓库重建一周工作全貌，10 秒出草稿。<br>2) **浮出不可见工作**：显式统计并单列「维护性工作占比」，提醒你别忘了写进周报。<br>3) **让维护被看见**：当「这周 60% 是维护」成为可见的事实，它才能进入团队对话。<br>4) **零依赖 + 纯本地**：不联网、不上传，公司代码也适用。 |

---

## 核心思想：工作的可见性光谱

把一周的提交按「周报记忆偏差」分成两段：

- **可见工作** `feat` / `fix` —— 大块头，你自己会记得写。
- **不可见工作** `test` / `docs` / `refactor` / `chore` / `perf` / `ci` / `build` / `style` —— 碎、杂、不出彩，但它们让系统活着。

每条提交经**确定性三层分类**归入类别（不打分、不猜权重，只做忠实归类）：

```
第 1 层  Conventional Commits 前缀   feat(api): ... → feat
第 2 层  主题关键词（中英）          "add tests for X" → test（关键词顺序保证 "add" 不误判为 feat）
第 3 层  变更文件路径                只有 *_test.py / yarn.lock / docs/ 变更 → test / chore / docs
兜底     other
```

报告单列一节 **Invisible work**，并给出占比——它不是价值判断，只是一个防止遗忘的锚点。

---

## 安装（零依赖）

只需 Python 3.8+ 和 `git`，无需 `pip install` 任何东西。

```bash
python3 gitweek.py report                    # 当前仓库，最近 7 天

# 想用 gitweek 这个命令名？做个软链（可选）
chmod +x gitweek.py
ln -s "$(pwd)/gitweek.py" /usr/local/bin/gitweek
gitweek report
```

作者默认取**每个仓库自己的 git 身份**（`git config user.name/email`，local 优先、global 兜底），所以多个仓库用不同身份也能一次收齐。

---

## 命令速查

```bash
gitweek report                                  # 最近 7 天（[今天-6, 今天]，含两端）
gitweek report --scan -p ~/dev                  # 工作区根目录，向下扫一层，收齐所有仓库
gitweek report -p ~/dev/api -p ~/dev/web        # 显式指定多个仓库
gitweek report --author "zach"                  # 指定作者（名字或邮箱的正则）
gitweek report --since 2026-08-03 --until 2026-08-09   # 自定义窗口（含两端）
gitweek report --format md                      # 可粘贴的周报草稿（markdown）
gitweek report --format json                    # 机器可读，接你自己的工具链
gitweek report --top 5                          # 最热文件显示 5 个
gitweek report --no-status                      # 跳过未提交改动（WIP）检测
```

---

## 一个真实样例

见 [`examples/`](examples/)。工程师 Ava 在 `2026-08-14`（周五）跑 `gitweek report --scan -p ~/dev`，覆盖 `api`、`web` 两个活跃仓库和一个空闲仓库：

```text
gitweek — 不可见工作考古报告
Period : 2026-08-08 .. 2026-08-14 (7 days)
Repos  : 3 scanned · 2 active · 1 idle
...
── Work shape ───────────────────────────
  feat     ██████  2  20%
  fix      ███     2  20%  ...
  test     ███     2  20%  ← invisible
  docs     █▌      1  10%  ← invisible
  refactor █▌      1  10%  ← invisible
  chore    █▌      1  10%  ← invisible
  style    █▌      1  10%  ← invisible
...
  → 6/10 classified commits (60%) were maintenance work.
```

**60% 的提交是维护性工作**——这就是不跑 gitweek 就会从周报里消失的那部分。完整报告见 [`examples/sample-report.txt`](examples/sample-report.txt)，周报草稿见 [`examples/sample-report.md`](examples/sample-report.md)。可用 `python3 examples/build_examples.py` 重新生成。

---

## 周五仪式（每周一次，5 分钟）

1. `gitweek report --scan -p ~/dev` —— 先看全貌：工作结构、每日节奏、最热文件。
2. 盯住 **Invisible work** 一节，对每条问自己：「这项工作的**成果**是什么？」
   - 有成果 → 进周报（用成果语言，见 [METHODOLOGY.md](METHODOLOGY.md)）。
   - 纯杂务（bump 依赖之类）→ 合并成一行「工程健康度」条目。
3. `gitweek report --scan -p ~/dev --format md > week.md` —— 生成草稿，把「活动」改写成「成果」，补上「下周计划」。
4. 顺手看一眼 **WIP**：未提交的改动是最容易被周末冲掉的工作，要么提交、要么 stash 写进下周计划。

---

## 验收标准与测试

验收标准全部转成自动化测试（`tests/test_gitweek.py`，25 个用例，`unittest` + 真实临时 git 仓库，所有日期固定、输出确定）：

```bash
python3 -m unittest discover -s gitweek/tests -v
```

覆盖：默认窗口 `[as_of-6, as_of]` 含两端与显式窗口校验；三层分类（前缀 / 关键词顺序 / 路径 / other / 可见-不可见集合互斥）；作者默认取仓库身份、`--author` 覆盖、无身份时报错；窗口边界（起止当天计入、窗外排除）；numstat 聚合（提交数 / 唯一文件 / 增删行 / 活跃天）；不可见占比计算；WIP 检测（脏工作区 / 干净 / `--no-status`）；idle 与空仓库的优雅处理；`--scan` 发现嵌套仓库与普通目录拒绝；部分仓库失败不影响整体报告；text/md/json 三种格式断言；以及两条端到端子进程 smoke 测试（含错误退出码）。

---

## 项目结构

```
gitweek/
├── gitweek.py               # 核心 CLI（单文件，纯标准库 + git）
├── tests/
│   └── test_gitweek.py      # 验收测试套件
├── examples/
│   ├── build_examples.py    # 用真实 CLI 复现样例的脚本
│   ├── sample-report.txt    # 样例报告（text）
│   └── sample-report.md     # 样例周报草稿（md）
├── METHODOLOGY.md           # 方法论：认知偏差、成果语言、FAQ
├── README.md
└── (LICENSE 在仓库根目录)
```

---

## 设计取舍

- **为什么作者过滤在 Python 侧做**：`git log --author` 是 POSIX basic 正则，不支持 `|` 交错，表达不了「名字 OR 邮箱」；git 只按宽松窗口取数，窗口和作者都在 Python 侧精确过滤，跨 git 版本行为一致、可测试。
- **为什么用 commit date 而不是 author date**：周报回答的是「这周仓库里落了什么」，rebase / squash 后 author date 会漂移到过去，commit date 稳定。
- **为什么跳过 merge commit**：`Merge branch ...` 不承载工作内容，留在报告里只有噪音。
- **为什么不给工作「打分」**：分类是事实（有确定性规则），权重是观点（因团队而异）。gitweek 只负责让事实可见，判断留给你。
- **为什么不算 code review**：本地 git 历史里没有 review 数据，gitweek 的诚实边界是「本地可见的提交历史」；review 统计需要平台 API，那是另一个工具的事。

---

## License

MIT © 2026（见[仓库根目录](../LICENSE)）
