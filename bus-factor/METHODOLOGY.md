# 知识单点 · Methodology

> 本文回答「为什么这么算」，以及「这个工具**不**该怎么用」。
> All numbers are deterministic and recomputable from `git log --numstat` — no randomness, no scoring voodoo.

---

## 1. 为什么按「新增行数」加权，而不是提交数

候选度量至少有三种，各有盲区：

| 度量 | 盲区 |
|---|---|
| 提交次数 | 一次 typo 修复与一次核心模块重写等权；不同人的提交粒度差异巨大 |
| 当前行数的 blame 归属 | 只看「最后一笔」，大量重写会抹掉前人认知 |
| **累计新增行数（本工具）** | 会受大文件复制粘贴 / 生成代码膨胀影响（见 FAQ） |

「谁懂这份代码」最好的代理变量是「谁累计往里写过多少」。新增行数对「从零写出」和「持续深耕」都敏感，对「顺手修一行」不敏感——这正是我们想要的形状。当前文件大小（行数）独立用于风险门槛（小文件不进风险清单），与份额计算解耦。

**度量的对象是「谁懂」，不是「谁产出」**——所以 pair programming 的两位都拿学分（见 §3），重复计入是有意设计而非 bug。

## 2. 指标定义

对文件 f，作者集合 A，作者 a 的累计新增行数为 `added(a, f)`：

```
share(a, f) = added(a, f) / Σ_a' added(a', f)          每人份额
TF(f)       = min n : Σ (前 n 大份额) ≥ 50%            卡车因子
HHI(f)      = Σ share(a, f)²                           集中度（0~1）
eff(f)      = 1 / HHI(f)                               有效人数
guardian(f) = argmax share(a, f)  if max share ≥ 80%   独守人
critical(f) = { a : share(a, f) ≥ 50% }                关键作者
```

风险分级：`TF = 1 → RED`，`TF = 2 → AMBER`，`TF ≥ 3 → GREEN`（仅对 ≥ `--min-lines` 行的文件生效）。

**50% 规则的直接后果**：50/50 的两人共写，TF 是 **1** 不是 2——单人恰好覆盖一半即「一卡车撞得垮」。若想更保守，把 RED 门槛理解为「存在任一 critical 作者」即可（`file` 子命令会同时标出）。

### 与学术 Truck Factor 的关系

Truck Factor 的学术定义（Avelino et al., *A Novel Approach for Estimating Truck Factors*, ICPC 2016；及 COSBAS toolchain 系列工作）用作者贡献的**概率覆盖模型**（DOSE / exponential）估计「以 x% 置信失去全部知识所需最少人数」。本工具刻意选择**确定性累积 50% 规则**：

- 可手算、可复算、无超参——审计友好，写进周报不怕被问「这数怎么来的」；
- 不做「作者离开 = 知识消失」的独立性假设（现实中共写者知识相关）；
- 代价是比概率模型略保守。赫芬达尔指数（HHI）本身是产业集中度的经典度量，这里借来刻画知识集中度。

## 3. Co-Authored-By：pair 的双重计入

`Co-Authored-By: Name <email>` 尾注（GitHub / git 的标准约定）会让 pair 的**双方**各计入该提交的全部新增行。于是 60 行的 pair 提交后两人各 50% 份额。理由：结对写代码时**两个人都获得了对这段代码的理解**——度量「谁懂」就必须双记。用 `--no-coauthored` 可关闭（比如只想看「谁名下提交」的口径）。

顺带修复了一个真实缺陷：作者解析必须**先匹配邮箱、再匹配显示名**，否则 `radius chen` 会命中 "Alice **Chen**" 而不是 chen@corp.dev。姓氏查询在企业仓库里太常见，这个顺序已固化成回归测试。

## 4. rename 链：`git mv` 不是失忆

按路径匹配历史时，`git mv` 移动文件会让旧路径的历史成为孤儿——文件的知识瞬间「蒸发」。<!-- dd:ignore: 花括号内为 rename 形态示例，非真实路径 -->本工具用 `git log -M --diff-filter=R --name-status` 重建 `旧路径 → 新路径` 的映射，对每条历史记录做传递闭包解析到最终路径。这不是理论风险：首次对本仓库（newidea）dogfood 时，8ac5fc4 的一次目录重组就曾让 decision-debt 全部文件的作者归零。

局限：跨仓库搬移（sparse checkout / filter-repo 重写历史）无法自动追踪；极老的提交里 rename 检测（相似度）可能漏判。

## 5. 时间窗口：知识会过期

默认统计全部历史，但「五年前写过 500 行」不等于「今天还懂」。`--window 365` 只统计近一年的提交——它回答的是**当下**的知识分布，代价是把回归老将的贡献视作过期。两种口径都合法：盘点用窗口，述职用全史。报告里始终写明窗口，避免口径混淆。

## 6. FAQ

**Q: 能拿这个做个人绩效吗？**
**不能，这是明确的反模式。** 份额度量的是「团队对某文件的理解是否集中」，不是产出或能力。独守一个 RED 文件往往说明的是**管理者**没有安排第二人（review 轮岗、onboarding 路径缺失），而恰恰是那位独守者在替组织扛风险。用 bus-factor 考核个人，团队会学会「少碰别人的文件」——正好毁掉工具想激励的协作。正确用法：把 RED 清单当**组织债务**处理掉。

**Q: 和 CODEOWNERS / OWNING 文件什么区别？**
CODEOWNERS 记录的是**声明的**所有权（谁该 review），bus-factor 测量的是**事实的**知识分布（谁真的写过）。两者对照才是完全体：某文件声明 owner 是 A、事实 guardian 是 B，就是一份「声明与事实的漂移」——和本仓库 [#3 文档漂移](../doc-drift/) 同构的问题。

**Q: squash merge 会怎样？**
PR squash 后贡献折叠成发起人一人（GitHub 会在 squash 消息里保留 Co-Authored-By，本工具能识别；自建 squash 流水线可能丢）。重度 squash 的仓库份额会向 PR 发起人集中，读数时心里有数即可。

**Q: 生成代码 / 复制粘贴 / vendor 目录会污染份额吗？**
会。「一行命令生成 3000 行」与「手写 3000 行」在读数上无法区分。缓解：`--min-lines` 抬门槛、`--exclude`（在仓库层用路径过滤后再跑）、以及对明显生成物（protobuf 产物、lockfile 之类）先做归档。<!-- dd:ignore: 此处为文件类型举例，非具体引用 -->零依赖 CLI 刻意不做启发式猜测——宁可读数朴素，不可魔法调参。

**Q: bot 怎么处理？**
dependabot / renovate / codecov 等（内置名单）默认整体忽略，`--include-bots` 可关掉该行为。CI 提交高频但零知识，计入只会稀释人类份额。

**Q: 为什么小文件不算风险？**
`--min-lines`（默认 30）以下的文件知识总量太小，逐一报警只会制造噪声。爆炸半径（`radius`）不受此限：交接收尾时你会想看到**每一个**孤儿文件。

**Q: 和同仓库其它点子的关系？**
四件套，各管一种「不可见」：[#1 决策债务](../decision-debt/) 管**未决的决策**；[#2 gitweek](../gitweek/) 管**个人的不可见劳动**；[#3 文档漂移](../doc-drift/) 管**声明与现实的漂移**；本工具管**知识在人上的集中**。四者共享同一套世界观：软件工程的真正风险都藏在「没人看的地方」，而事实数据（git / 文件系统 / 文档）总是比记忆和直觉更诚实。

---

## 参考

- Avelino, G., Passos, L., Hora, A., & Valente, M. T. (2016). *A Novel Approach for Estimating Truck Factors.* IEEE ICPC.
- Herfindahl–Hirschman Index — 集中度度量，本工具用于知识分布。
- [Truck factor](https://en.wikipedia.org/wiki/Bus_factor)（bus factor）词条——「几辆卡车撞倒团队才失控」的原始隐喻。
