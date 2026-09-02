# 讲台时刻 · Stage Time

> 超时从来不是在台上发生的——是在写稿的那一刻就注定的。
> A zero-dependency CLI that models how long a talk will *actually* take to deliver — digit-by-digit numbers, char-by-char code, structural pauses — then, when you're over budget, tells you what to cut **by sacrifice priority**, never touching your core argument.

---

## 一句话

「这份稿子念完到底要几分钟？」字数÷语速的粗算误差极大，因为**语速不是常数**：念数字要逐位、念代码要逐词、列表项之间要换气、翻页要停顿。`stage-time` 用**口播单位**模型把讲稿变成一条可计算的时间轴：汉字 1 单位/字、数字串逐位、英文词 1.8、代码逐字符另计，再叠加翻页/段落/列表停顿——写稿当晚就知道会不会超时；超时时不是均匀压缩，而是按**牺牲优先级**（客套 > 背景 > 细节，核心论证受保护）给出「删哪里最不痛」的清单；核心主张句出现太晚照样亮红灯。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 下周要上台做 15 分钟技术分享的工程师；同样适用于答辩研究生、路演创始人、年会汇报的产品经理——一切「要对着活人讲完一份稿子」的人。 |
| **场景** | 分享前夜，幻灯片和讲稿终于写完，时间槽 15 分钟，已经没有时间做一次带计时的完整彩排。 |
| **问题** | **超时在台上才暴露**：粗算字数误差巨大（语速非常数），完整彩排成本高所以很少做；结果上台才发现超了 40%，被迫现场砍结尾——砍掉的恰好是结论。超时的修复也不是均匀压缩，临场不知道删哪里，往往删到最痛的地方。此外还有个隐形失败模式：核心观点埋在稿子后 1/3，而听众注意力峰值在前几分钟。 |
| **价值与意义** | 1) **时机前移**：把「到底几分钟」的回答从台上提前到写稿时——30 秒静态分析替代一次彩排的计时功能。<br>2) **类型感知**：不是数字数，是建模口播——数字逐位、代码逐字符、停顿计入，这是字数统计工具给不了的。<br>3) **不均匀压缩**：超时时的删除建议按牺牲优先级排序，客套先死、论证永生——把「砍哪里」从台上临场决策变成写稿时的理性清单。<br>4) **可校准**：一次真实计时反推你的个人语速，越用越准。<br>5) **零依赖 + 纯本地**：Python 3.8+ 标准库，稿子不上传。 |

---

## 核心思想：口播单位 → 时间轴 → 牺牲优先级

```
讲稿 markdown ─→ 块解析（标题/段落/列表/引用/代码）
             ─→ 口播单位（汉字 1/字、数字逐位、英文词 1.8）
             ─→ 时间轴（单位 ÷ 个人语速 + 结构停顿 + 代码逐字符）
             ─→ 预算判定（超时 → 压缩清单；主张句位置 → 倒金字塔审计）
```

| 概念 | 定义 | 直觉 |
|---|---|---|
| **口播单位** | 汉字 1、数字串逐位 1/位（2024 → 二-零-二-四）、英文词 1.8 | 嘴巴实际要发的音，不是眼睛看的字符 |
| **叙述时长** | 口播单位 ÷ 个人语速（默认 4.0 单位/秒 ≈ 240 字/分钟） | 随语速缩放，可用真实计时校准 |
| **固定成本** | 代码逐字符 + 翻页 1.5s + 段落 0.6s + 列表项 0.4s + 引用 0.8s + 代码演示 2.0s | 物理性的慢：不随语速缩放，校准时必须与叙述分开 |
| **时长区间** | 预计 ±15% | 语速个体差异的诚实区间，不是点估计 |
| **牺牲优先级** | P0 客套元话语 > P1 冗长背景 > P2 次要细节 > 核心内容（保护） | 先删自己的客套，再删听众的时间，永不删论证 |
| **主张句位置** | 第一个「我认为/I argue」式信号句在时间轴上的百分比 | ≤25% 🟢 倒金字塔合格；>50% 🔴 埋伏笔失败模式 |

两条诚实条款刻在实现里：主张句**未检出就明说未检出**，不硬猜；压缩清单**覆盖不了需求就明说需要动结构**（删客套救不回来的超时不是删字问题），不凑数。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash dd:ignore
python3 stage_time.py estimate examples/demo_talk.md --budget 15
```

## 命令速查

```bash dd:ignore
python3 stage_time.py estimate talk.md --budget 15        # 时长估算 + 预算判定
python3 stage_time.py estimate talk.md --budget 15 --json # 机读输出
python3 stage_time.py cuts talk.md --budget 15            # 超时 → 按牺牲优先级的压缩清单
python3 stage_time.py thesis talk.md                      # 核心主张句位置审计
python3 stage_time.py calibrate talk.md --actual 12.5 --save  # 用真实时长校准个人语速
python3 stage_time.py estimate talk.md --budget 15 --rate 3.6 # 手动指定语速（单位/秒）
```

`--profile` 可指定语速档案路径（默认 `~/.stage-time.json`）；校准一次，`estimate`/`cuts`/`thesis` 自动复用。

## Dogfood

`examples/demo_talk.md` 是一篇真实的 15 分钟级分享稿（主题致敬本仓库的 gitweek：《你的周报在说谎——从 git 历史打捞不可见工作》），刻意设计成「三病齐发」：

```bash dd:ignore
python3 stage_time.py estimate examples/demo_talk.md --budget 15
# → 预计 15.8 分钟 ⚠️ 超时 +0.8 分钟

python3 stage_time.py thesis examples/demo_talk.md
# → 主张句「我认为真正的问题不是员工懒于写周报……」出现在 64% 处 🔴 太晚

python3 stage_time.py cuts examples/demo_talk.md --budget 15
# → #1 [P0 客套] 省 30 秒  #2 [P1 冗长背景] 省 41 秒 ✅ 已覆盖需求（核心 49 块受保护）
```

三份输出以快照形式锁定在 `examples/sample-estimate.txt`、`examples/sample-thesis.txt`、`examples/sample-cuts.txt`，随验收测试逐字节比对（确定性：同输入同输出，无时间戳）。

---

## 验收标准（全部转成自动化测试）

`python3 -m unittest discover -s tests` — 36 个用例，逐条对应：

| # | 验收标准 | 测试 |
|---|---|---|
| 1 | 口播单位：汉字 1/字；数字串逐位（「2024」=「二零二四」）；英文词 1.8；行内代码不占叙述单位 | `TestUnits`（5 例） |
| 2 | 基线时长：480 单位 @ 4 单位/秒 = 120 秒整 | `test_baseline_narrative` |
| 3 | 代码比散文慢：同内容按代码念（逐字符+演示停顿）> 按英文读 | `test_code_block_slower_than_prose` |
| 4 | 结构停顿计入：列表项间 0.4s、标题翻页 1.5s + 段落间 0.6s（对照同字数整段） | `test_list_pauses_counted` / `test_heading_pause_counted` |
| 5 | 预算判定：120 秒稿 @ 1 分钟预算 → over +60s；@ 2 分钟 → within -60s | `TestBudget` |
| 6 | 压缩清单按牺牲优先级升序，核心论证块永不出现；累计节省 ≥ 超时 × 1.05 | `test_priority_order_and_protection` / `test_cuts_cover_overrun_with_margin` |
| 7 | 省 5 秒以下的块不进清单（噪音过滤） | `test_min_cut_filter` |
| 8 | 可牺牲池不足时 `covered=False`（明说需要动结构，不凑数） | `test_uncoverable_when_pool_too_small` |
| 9 | 主张句：可检出含位置；前置（≤25%）与太晚（>50%）判定正确；未检出返回 None 不硬猜 | `TestThesis`（4 例） |
| 10 | 校准闭环：真实时长反推语速，重放总时长还原真实值（停顿正确归入固定成本） | `test_roundtrip_recovers_rate` |
| 11 | 校准拒不可能输入：实际时长 ≤ 固定成本 → ValueError | `test_rejects_impossible_actual` |
| 12 | `--save` 写档案，`estimate --profile` 复用后回放到真实分钟数 | `test_cli_save_and_reuse_profile` |
| 13 | CLI 契约：文件缺失退 2；`--json` 结构完整；输出确定性；中英双语稿；子进程入口 | `TestCli`（5 例） |
| 14 | Dogfood：示例稿三病齐发全部检出，输出与快照逐字节一致；压缩清单永不触碰主张块 | `tests/test_dogfood.py`（5 例） |

## 设计取舍

- **数字逐位念是保守估计**：「2024」也可能被整念成「两千零二十四」（更慢）或跳过（更快），逐位是中位且可解释的选择；系统性偏差交给 `--rate`/校准吸收。
- **停顿是固定值而非随语速缩放**：翻页的物理时间不因为你说话快而变短。校准时把停顿与代码归入固定成本、只反推叙述速率，正是为了让这两类时间各归各位。
- **主张句检测是信号词启发式**：宁可漏报（明说未检出）也不误报——检出的那一句一定写明了「我认为/I argue」，作者意图明确。
- **压缩清单建议到块、不建议到句**：删一个段落是可执行决策，逐句改写不是工具该替你做的。

更多模型依据与 FAQ 见 [METHODOLOGY.md](METHODOLOGY.md)。

## License

MIT © 2026
