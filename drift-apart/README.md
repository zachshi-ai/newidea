# 渐行渐远 · Drift Apart

> 友谊没有关机动画：它不会突然死亡，只会把聊天记录的日期越拉越远。
> A zero-dependency CLI that keeps a decay ledger for the friendships that fail silently — measuring each relation against **its own circle's rhythm**, not a universal guilt clock, and flagging the silence while it is still cheap to break.

---

## 一句话

成年人的友谊失效是**静默**的：没有告警、没有仪式，只是「上次联系」从上周滑成上月、从上月滑成「去年这时候还聊过」。等你听说老朋友结婚、搬家、离职的时候，那段关系早已在你看不见的地方漂远——而想联系又拖着的每一周，都在让「突然发消息」这件事变得更贵。`drift-apart` 的立场：**维系不是靠愧疚感，是靠一本知道节奏的账**。核心朋友一个月、老同学一年，每段关系本来就有自己的自然间隔；工具从两本手记账（一张花名册 + 一条互动流水）里算出每段关系的**欠费天数**（沉默时长 − 该圈层的节奏）、**沉默斜率**（互动间隔在拉长是漂移的领先指标——它会在「上次联系还是去年」成为事实之前半年就亮灯）、**单程指数**（最近几次全是你发起的关系，你一停它就死），最后给出一张**修复清单**：生日门优先（错过一次就是一年），其余按漂得最远的排——今天先联系谁，第一次有据可依。联系与否永远是人的决定，账本只负责拒绝继续沉默。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 工作/搬家/育儿后社交圈收缩的忙碌成年人；朋友散落多城、联系全靠主动的「游子」；清楚自己该多联系朋友、但愧疚感只能维持三天的内向者。 |
| **场景** | 年底翻通讯录盘点（「小满生日是不是快到了？我们多久没说了？」）；偶然听说老朋友的近消息时一愣（「我们曾经每周都见面」）；想联系却越拖越不敢（「隔了这么久突然找他很怪吧」——拖得越久越怪）；发现自己停手一个月后没有任何人找过你。 |
| **问题** | **友谊的失效没有任何症状**：① 静默——没有告警，沉默不是事件，是缺省；② 没有账本——人人都知道「该常联系」，但没人记得每段关系各自的节奏，于是用同一把愧疚的尺子量所有朋友；③ 修复成本随沉默上升——隔一个月一条消息就够，隔三年就要一场「蓄谋已久」的开口，于是越拖越不敢；④ 单程关系无人察觉——最近几次都是你发起的关系，其实在你停止的那天就已经死了，只是尸体还没凉；⑤ 生死节点错过不再来——生日错过一次，「下次」就是整整一年之后。 |
| **价值与意义** | 1) **圈层节奏 cadence**：inner 30 / close 90 / active 180 / outer 365 天（行级与命令行均可覆盖）——「多久没联系才算久」第一次按关系本身衡量，而不是按愧疚。<br>2) **欠费账本**：`欠费 = 沉默天数 − 节奏`，四档判定（FRESH / OVERDUE / DRIFTING / GONE，外加登记了却从未互动的 NEVER），排行第一行就是漂得最远的那段。<br>3) **沉默斜率**：最近一次间隔 vs. 之前间隔的中位——间隔翻倍意味着漂移正在加速，这条领先指标比「上次联系是半年前」早半年亮灯（⚠）。<br>4) **单程指数**（↺）：最近 5 次互动 80% 以上由你发起 → 标记「你一停它就停」。<br>5) **修复清单**：生日门（★，7 天内过生日的欠费关系）排最前——它是不需要理由的重联系场合；其余按漂移程度排序，每档给对应的开口建议。<br>6) **零依赖 + 纯本地**：Python 3.8 标准库，`--as-of` 钉死即逐字节可复现——一本记录「谁对谁重要」的账本，本来就不应该上云。 |

---

## 核心思想：用「各自的节奏」替代「统一的愧疚」

关系的全部误判，都来自拿一把尺子量所有人。工具引入**节奏（cadence）**——该圈层关系不联系也自然存活的最长间隔——并在这之上记账：

| 概念 | 规则 | 回答的问题 |
|---|---|---|
| **圈层节奏 cadence** | 默认表（inner 30、close 90、active 180、outer 365），行级 cadence 列 > `--circle-cadence` > 默认表 | 「这段关系多久联系一次算正常？」 |
| **欠费 arrears** | `欠费 = 今天 − 最近互动 − cadence`；比率 = 沉默 ÷ 节奏 | 「我欠这段关系多少天？」 |
| **漂移带 band** | 比率 ≤1× FRESH（健康）/ ≤2× OVERDUE（欠一次，一条消息够）/ ≤4× DRIFTING（需要一个理由开口）/ >4× GONE（沉默已活过你的节奏四倍，重新联系需要场合而非问候）；另有 NEVER——登记了却从未互动 | 「现在该做什么级别的动作？」 |
| **沉默斜率 slope** | 最近间隔 ÷ 之前间隔的中位数：≥2× LENGTHENING（⚠ 间隔在拉长）/ ≤0.5× WARMING / 其余 STEADY；不足 3 次互动 UNKNOWN | 「沉默是常态波动，还是在加速漂远？」 |
| **单程指数 balance** | 最近 5 次互动中你发起的比例 ≥80% → UNILATERAL（↺） | 「如果我停手，这段关系还有呼吸吗？」 |
| **生日门 occasion** | 7 天内过生日的欠费关系 → ★ 置顶；错过即闭门一年 | 「今天有没有一个不需要理由的开口机会？」 |
| **修复清单 repair** | 生日门按剩余天数 → 其余按漂移程度 → 按圈层亲疏；有欠费 exit 4 | 「今天先联系谁，说什么级别的开场？」 |

四条诚实条款刻在实现里：**「今天」只属于真实使用**——`--as-of` 默认今天，钉死它即逐字节可复现（仓库样例全部钉在 2025-12-01）；**账本只收真实双向互动**——点赞不算、群聊不算，一条私聊也算，工具无法验证真伪，但表结构里每行都有发起者，这个字段就是账本的良心；**NEVER 不是废票**——登记了却没互动的人单列一档，账本在提醒你做一个决定（约，或从名单上取下），而不是假装名单是诚实的；**GONE 不是判决**——它只说明开口的价格已经变了，联系与否永远是人的决定。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash dd:ignore
python3 drift_apart.py ledger roster.csv interactions.csv   # 谁漂得最远？
```

## 命令速查

```bash dd:ignore
python3 drift_apart.py ledger roster.csv interactions.csv                       # 欠费排行：谁在漂远
python3 drift_apart.py ledger roster.csv interactions.csv --as-of 2025-12-01    # 钉死参照日 → 逐字节可复现
python3 drift_apart.py ledger roster.csv interactions.csv --circle close        # 只看亲密圈
python3 drift_apart.py ledger roster.csv interactions.csv --format json         # 机读
python3 drift_apart.py ledger roster.csv interactions.csv --redact              # 名字哈希脱敏，报告可外发
python3 drift_apart.py repair roster.csv interactions.csv --within 7            # 修复清单：今天先联系谁（有欠费 exit 4）
python3 drift_apart.py show roster.csv interactions.csv 陈默                    # 单人档案：斜率 + 单程指数 + 互动史
python3 drift_apart.py ledger roster.csv interactions.csv --circle-cadence close=45   # 覆盖亲密圈节奏
```

账本格式：`roster.csv` 一人一行（`姓名,圈层,生日`，生日可选 `MM-DD`）；`interactions.csv` 一次真实双向互动一行（`姓名,日期,发起者`，发起者 `我`/`对方`）。中英文表头均可。

## 一个真实样例

一本八人的老友花名册（`python3 examples/build_examples.py` 可从零重建，日期全部钉死，`--check` 逐字节校验）：三个月没消息的核心室友、四天后过生日的前同事、每轮都是你发起的老邻居、一个登记了却从未开口的泛泛之交。参照日钉在 2025-12-01，[`examples/sample-ledger.txt`](examples/sample-ledger.txt) 的判决：

```text dd:ignore
  relations     : 8 relations
  bands         : 3 fresh · 2 overdue · 0 drifting · 2 gone · 1 never contacted
  signals       : 1 stretching gaps (⚠) · 2 unilateral (↺) · 1 birthday door open (★)
  farthest gone : 陈默 (silent 388d · 12.9× your 30d rhythm)

  name             circle              last cadence   silent  band
  陈默             inner 核心    2024-11-08     30d     388d  !! GONE⚠↺
  老周             outer 社交    2021-02-12    365d    1753d  !! GONE↺
  苏黎             close 亲密    2025-08-01     90d     122d  ~ OVERDUE
  林小满           close 亲密    2025-08-20     90d     103d  ~ OVERDUE★
  ...

  何朗             outer 社交             —    365d        —  ?? NEVER
```

读法：**陈默是账本上最痛的一行**——核心圈节奏 30 天，实际沉默 388 天（12.9 倍），更刺眼的是两个标记：⚠ 互动间隔已拉长到旧中位的 3.1 倍（从每月一次掉到四个月一次——漂移在加速），↺ 最近五次全是你发起（你一停它就停，事实上你已经停了）。林小满行尾的 ★ 是生日门：四天后生日，这是唯一不需要任何理由的开口机会。然后是修复清单（[`examples/sample-repair.txt`](examples/sample-repair.txt)）：

```text dd:ignore
  birthday doors open now (miss one and the next is a year away):
  ★ 林小满 — birthday in 4d

  today's order (birthday doors first, then farthest gone):
  ~ 林小满    close 亲密 · silent 103d · one message is enough — a nudge inside your rhythm reopens it
  !! 陈默     inner 核心 · silent 388d · silence this old needs an occasion (a birthday, a shared memory) — a bare 'hi' will stall
      ↳ gaps stretching (3.1× the old median); you initiated 5 of the last 5
  ...
  gate: FAIL — 5 relations still outside their rhythm
```

注意开口建议的分档：对苏黎（欠一次）是「一条消息就够」，对陈默（沉默近四年、按你俩的旧节奏早已超期 258 天）是「需要一个场合，一句『在吗』只会把对话晾死」。[`examples/sample-show.txt`](examples/sample-show.txt) 里陈默的完整档案：六次互动的时间线、间隔从 30 天膨胀到 130 天的斜率、单程指数 100%——一段关系的漂移史，一屏读完。

## dogfood：样例账本即狗粮

```text dd:ignore
$ python3 examples/build_examples.py --check
examples in sync
```

友谊数据比密码更敏感——它记录的是「谁对谁重要」。本件不内置任何真实花名册。dogfood 的形式与仓库传统一致：**三份样例报告由交付代码本身渲染**（`examples/build_examples.py` 走与 CLI 完全相同的代码路径），CI 用 `--check` 逐字节校验——报告里的每一个数字都能从钉死的账本与 `--as-of` 复现，一份手写的样例都不存在。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_driftapart.py`](tests/test_driftapart.py)，62 个用例，`unittest` + 合成账本）：

```bash
python3 -m unittest discover -s drift-apart/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 双表解析：中英文表头别名、BOM 与空行、四种日期写法、缺必填/非法圈层/重名/非法发起者报行号、幽灵互动（互动里的人不在花名册）拒绝、生日三格式、无表头报错、cadence 必须为正整数 | `ParserTests`（12 例） |
| 节奏解析：四圈默认表、行级 cadence > `--circle-cadence` > 默认表 | `CadenceTests`（4 例） |
| 漂移带数学：1×/2×/4× 的六个边界（90/91/180/181/360/361 天）、欠费与比率、NEVER 档 | `BandTests`（3 例） |
| 沉默斜率：<3 次互动 UNKNOWN、STEADY/LENGTHENING（含 2× 边界）/WARMING、基线中位不受最近间隔污染、全零间隔安全、按历史节奏的超期判定 | `SlopeTests` + `SlopeOverdueLineTests`（7 例） |
| 单程指数：K=5 窗口、全 me 标记、0.5 不标、<2 次互动 UNKNOWN | `UnilateralTests`（4 例） |
| 生日节点：同年/跨年、2 月 29 → 3 月 1、7 天窗边界、FRESH 不置顶 | `OccasionTests`（4 例） |
| 总账排行：GONE > OVERDUE > FRESH > NEVER、同档按比率、farthest-gone 摘要、⚠/↺/★ 标记、`--circle` 过滤（计数同步）、未知圈层 exit 3、json 结构与关键数字 | `LedgerTests`（7 例） |
| 修复清单：生日门置顶按天数、其余按漂移程度、分档开口建议、exit 4/0、`--within` 截断、全绿 PASS、json gate、单程/斜率理由行 | `RepairTests`（7 例） |
| 隐私：`--redact` 隐藏名字（ledger/repair/show、text/json） | `RedactTests`（3 例） |
| 档案：单人全部字段、NEVER 档案、未知名 exit 3 并按首字给相近名提示 | `ShowTests`（3 例） |
| CLI：无参数 exit 2、文件缺失 exit 3、`--as-of` 缺省今天 / 非法报 usage 错、`--circle-cadence` 三种非法、改节奏换档 | `CliTests`（6 例） |
| **dogfood：样例逐字节同步 + 样例数字核验** | `DogfoodTests`（2 例） |

## 项目结构

```
drift-apart/
├── drift_apart.py
├── tests/test_driftapart.py
├── examples/build_examples.py
├── examples/roster.csv
├── examples/interactions.csv
├── examples/sample-ledger.txt
├── examples/sample-repair.txt
├── examples/sample-show.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
