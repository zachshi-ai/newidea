# 凋萎点 · Wilting Point

> 植物不是在你发现那天死的，是在凋萎线被越过那一刻就注定死的。
> A zero-dependency CLI that turns a hand-kept plant ledger + watering log into a per-pot countdown: each species' safe line and wilting point, your real watering cadence, a rot lamp for the over-loved, a rebuy blacklist your own neglect wrote, a trip simulator, and a purchase gate that answers "can you keep this one alive?" from your own log.

---

## 一句话

室内植物的头号死因不是虫不是病，是**忘了浇水**和**浇水太勤**——而市面上的浇水提醒只回答「今天该浇吗」，从不回答三件事：**还有几天可以拖？十盆里谁先死？我到底适不适合养这种植物？**`wilting-point` 把这本没人记的账记出来：从两份可手编的 TSV（植物台账 + 浇水日志）确定性算出每盆植物的**水位计**——安全线（耐旱下限）与凋萎线（耐旱上限，土壤学的 permanent wilting point：越线即不可逆损伤）之间的剩余天数，四档状态 OK / DUE / PARCHED / WILTED；再往上叠三层对账：**烂根灯**（最近两次间隔都短于安全线一半——兰花和多肉死于爱比死于渴快得多）、**主人画像**（你的中位浇水间隔就是你的植物主人性格，收藏里多少盆的安全线比你紧，一目了然）、**失调账本**（哪些品种在你的照顾下反复越线 ≥2 次——那份「别再买了」的黑名单由你自己的日志写成）。外加 `simulate trip N`（不浇走 vs 浇完走，谁撑不到你回来）和 `advice`（购入门卫：你的中位间隔 × 它的安全线 = 三档判决，INCOMPATIBLE 直接 exit 4）。拔不拔那盆蕨是你的决定；但没有倒计时，阳台永远死于「下周一定浇」。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 养着 5–30 盆室内植物的人；被「忘了浇水 → 愧疚 → 再买一盆」循环困住的人；出差前对着一阳台植物发愁、不知道该托付谁的人；在花店被蕨类的美貌击中、又怕又一次养死的人。 |
| **场景** | 周末大扫除才发现一盆叶子全卷了；国庆七天假，回来收尸还是安心度假，出发前夜没有任何依据；花店老板说「很好养的」，App 说「记得浇水哦」——买之前没有一个人看过你的浇水日志。 |
| **问题** | ① **死亡不是事件，是越线**：浇水提醒回答「今天该浇吗」，不回答「还有几天可拖、谁先死」——没有倒计时，拖延永远赢；② **统一节奏是伪方案**：耐旱 30 天的多肉和 4 天就出事的蕨类住在同一个阳台，「每周浇一次」的时间表同时杀死两端；③ **第一死因不是忘，是勤**：蝴蝶兰和多肉死于烂根的速度远快于干旱，提醒类工具只会催你浇更多；④ **「我适合养什么」是玄学**：没人检查你的浇水日志——而那里写着你的中位间隔（你的植物主人性格）和你反复养死的品种（你的黑名单）。 |
| **价值与意义** | 1) **水位计**：十盆 → 四档（2 OK · 3 DUE · 3 PARCHED · 2 WILTED），每盆一个到天的倒计时（四年老桩玉树距凋萎线只剩 1 天）——「谁先死」第一次有了排序。<br>2) **凋萎点可审**：安全线/凋萎线写在台账里逐盆可调，判定是两行 if 不是黑盒；季节开关（夏 ×0.7 / 冬 ×1.3）解释「怎么突然就要浇了」。<br>3) **烂根灯**：兰花最近两次间隔 3d,3d < 3.5d 半线 → OVERWATER——「爱过量」第一次被计量；连对照人物 tang 的周日例行也被挑出两盏灯（虎皮兰/金钱树被统一节奏收税）。<br>4) **主人画像**：中位浇水间隔 6 天 + 4/10 收藏的安全线比你紧——问题不在记性，在选品；黑名单三种（boston-fern, calathea, nerve-plant）是你自己的日志写的。<br>5) **trip 7**：不浇走 6/10 出事；浇完走只剩网纹草（凋萎线 7d ≤ 旅程 7d）——「托付一盆，不用麻烦朋友照顾整个阳台」。<br>6) **零依赖 + 纯本地**：Python 3.8 标准库；账本留在本地，时钟默认取账本最大日期，`--today` 可拨表——账本是确定性的，时钟也是。 |

## 与仓库近邻的边界

- **vs 到期悬崖 expiry-cliff**：都给「静默逼近的线」记账。expiry-cliff 的线是**行政期限**（护照/保单——晚办 30 天没有不可逆损失，补办即可），本件的线是**生理水位**（每天在蒸发，越线即损伤，补浇救不回枯死的根）；一个管「什么时候去办」，一个管「还有几天可以拖」。
- **vs 余燃 afterburn**：都建模「一次事件在系统里的余效」。afterburn 建模咖啡因浓度按半衰期衰减（对手是睡眠），本件建模土壤水量按蒸腾消耗（对手是遗忘）；咖啡因账本回答「几点前喝完」，水位计回答「还有几天可拖」。
- **vs 渐行渐远 drift-apart**：都从「间隔的历史分布」挖领先指标。drift-apart 用沉默斜率预警友谊漂移（比「上次联系是去年」早半年），本件用间隔漂移预警植物死亡（Fern 从 4 天一轮滑到 13 天）——区别在对象：朋友不会蔫给你看，植物会，所以这里能给精确到天的凋萎日。
- **vs 加量红线 redline**：都装「刻度盘 + 红线」。redline 的转速表防**过量**（跑多了受伤），本件有两根轴：忘性轴（干死）与手勤轴（烂死）——OVERWATER 灯是 redline 的镜像：**爱过量也是伤**，而且多肉死于爱比死于渴常见得多。
- **vs 绝活生锈 repertoire-rust**：都给「不维护就衰减」的存量记倒计时。repertoire-rust 的半衰期由你的回忆**自己挣来**（练得好就拉长，砸了就封顶），本件的两根线写在品种里（生物学给的，不因你勤恳而改变）；一个管人的技能存量（衰减总能被练习重置），一个管盆里的生命（倒计时只能被浇水重置，且有一个真正的终点）。

---

## 核心思想：两根线，两根轴

从每行一盆植物（`plant / species / dry_min / dry_max / acquired[/notes]`）加每行一次浇水（`date / plant[/note]`）确定性导出：

**忘性轴（水位计）**：`d` = 今天 − 上次浇水。两根线写在品种里、逐盆可调：

| 状态 | 判定 | 含义 |
|---|---|---|
| **OK** | d < 0.7 × 安全线 | 土壤还撑得住 |
| **DUE** | 0.7 × 安全线 ≤ d < 安全线 | 浇水窗口已开 |
| **PARCHED** | 安全线 ≤ d < 凋萎线 | 伤害区间——今天浇，别等晚上 |
| **WILTED** | d ≥ 凋萎线 | 越过凋萎点，损伤不可逆 |

**手勤轴（烂根灯）**：最近两次间隔都 < 安全线 ÷ 2 → OVERWATER。半线判定是**严格的**（等于不算），单次手勤不算，连续两次才亮——它抓的是「养护习惯」，不是偶然手滑。兰花 8 月的三连日浇（3,3,3）+ 8 月 22 日起的彻底遗忘，就是这盏灯被发明出来的剧本。

**主人画像**：全部浇水间隔（跨盆合并）的中位数 = 你的**中位浇水间隔**。安全线比你中位间隔还紧的植物占比 = **失配率**——失配的不是你的记性，是你的选品。

**失调账本**：某盆的任一间隔 > 安全线记 1 次失调（严格大于：恰好在安全线那天浇不算）。按品种聚合，**≥2 次进再购黑名单**——「你养不活这个」这句话从此有证据链。零失调且不在伤害区的盆是**绿色队友**：你的性格养得活它们，问题从来只在选品。

**出差推演** `simulate trip N`：两个场景对跑——不浇走（谁的凋萎日落在旅途内）与浇完走（离开当天统一补浇，凋萎线 ≤ N 的依然会沉）。「浇完走」的差集就是**托付清单**：多数假期只需要托付一盆，不需要麻烦朋友照顾整个阳台。

**购入门卫** `advice`：中位间隔 m 对某物种安全线 s 的三档判决——**COMPATIBLE**（s ≥ 1.5m，容忍你的迟钝一个半周期）/ **RISKY**（m ≤ s < 1.5m，迟到一次就进伤害区）/ **INCOMPATIBLE**（s < m，你的正常节奏就是它的干旱）→ exit 4。若你已养着这个物种且日志里有失调，附上**证据行**。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash dd:ignore
python3 wilting_point.py report ledger.tsv log.tsv      # 水位计全景 + 主人画像
```

台账格式（TSV，`#` 注释，首行表头可选；`dry_min/dry_max` 用天，查 `species` 命令的内置表或按盆校准）：

```text dd:ignore
plant      species      dry_min  dry_max  acquired    notes
Fern       boston-fern  4        8        2025-03-15  花市促销抱回来的
SnakePlant snake-plant  21       45       2021-04-10  搬新家朋友送的
```

日志格式（一行一次浇水，同盆同日只一行）：

```text dd:ignore
date        plant
2026-08-26  Calathea
2026-09-02  Haworthia   今天顺手浇的
```

「今天」默认取台账与日志的最大日期，`--today` 可拨表；`--season summer`（线 ×0.7）/ `--season winter`（×1.3）处理蒸腾的季节差异——账本是确定性的，时钟也是。

## 命令速查

```bash dd:ignore
python3 wilting_point.py report ledger.tsv log.tsv          # 水位计 + 烂根灯 + 画像 + 黑名单
python3 wilting_point.py report ledger.tsv log.tsv --format json   # 机读
python3 wilting_point.py report ledger.tsv log.tsv --fail-wilted 1 # 门禁：WILTED ≥ 1 则 exit 4
python3 wilting_point.py due ledger.tsv log.tsv             # 今天该浇谁（倒计时排序）
python3 wilting_point.py simulate ledger.tsv log.tsv trip 7 # 出差七天：不浇走 vs 浇完走
python3 wilting_point.py advice ledger.tsv log.tsv boston-fern  # 购入门卫
python3 wilting_point.py species                            # 内置品种表（16 种安全线/凋萎线）
python3 wilting_point.py validate ledger.tsv log.tsv        # 账本体检
```

## 两个真实样例

两个阳台、两种诊断（`python3 examples/build_examples.py` 可从零重钉全部样例，逐字节可复现）。**che** 的阳台十盆、浇水全凭「哪天想起来」——[`examples/sample-report-che.txt`](examples/sample-report-che.txt) 的判决：

```text dd:ignore
  bands           : 2 OK · 3 DUE · 3 PARCHED · 2 WILTED
  overwater       : 1 flagged — Orchid (rot kills faster than drought)
  cadence         : 6d median gap between your waterings
  mismatch        : 4 of 10 plants have a safe line shorter than your cadence
  neglect ledger  : 9 misses on 4 plant(s)
  blacklist       : 3 species (≥2 misses) — stop rebuying: boston-fern, calathea, nerve-plant
  green teammates : 4 — Aloe, Haworthia, Monstera, Pothos
```

读法有四层。**其一，倒计时比提醒有用**：玉树（Jade）四年从没让你操过心，此刻距凋萎线只剩 **1 天**——「最放心的那盆快死了」这件事，提醒类 App 永远不会告诉你；[`examples/sample-due-che.txt`](examples/sample-due-che.txt) 把十盆排成一条从「已过线 7 天」到「窗口还有 7 天才开」的队列。**其二，烂根灯抓的是剧本不是失误**：兰花 7 月还是七天一轮的自律，8 月搬进空调房后突然一天一浇（3,3,3 < 3.5 半线），8 月 22 日起又彻底遗忘——先是爱过量、后是断供，杀兰花的两个阶段都亮了牌。**其三，间隔漂移是领先指标**：Fern 的间隔从 4 天一轮漂到 5、11、8、8、13，四次失调写进黑名单（同案的还有网纹草 2 次、竹芋 2 次）——[`examples/sample-advice-fern.txt`](examples/sample-advice-fern.txt) 的 `advice boston-fern` 判 INCOMPATIBLE 并 exit 4，证据行就是你自己的日志：**你的中位节奏 6 天，它的安全线 4 天，你的正常就是它的干旱**。**其四，假期答案比想象便宜**：[`examples/sample-simulate-che.txt`](examples/sample-simulate-che.txt) 显示 trip 7 不浇走 6/10 出事，浇完走只剩网纹草会沉（凋萎线 7d ≤ 旅程 7d）——**托付一盆，不用麻烦朋友照顾整个阳台**。对照组 **tang**（[`examples/sample-report-tang.txt`](examples/sample-report-tang.txt)）：五盆耐旱收藏、周日例行 7 天一轮——5 OK · 0 失调 · 失配 0/5，verdict 一句话「your cadence and your shelf agree with each other」；但工具连他也挑出了两盏烂根灯（虎皮兰、金钱树，安全线 21d 的盆被 7d 例行收税）：**全绿的是干旱轴，不是浇水轴**。

## dogfood：数字从哪来，就由谁验证

本件与仓库同源：README 与样例里的每一个数字（6d、9 misses、4 of 10、2 WILTED、trip 7 的 6/10 与 1/10、玉树的 1 天……）都由同一个 CLI 生成，`python3 examples/build_examples.py --check` 保证提交的两本账与七份样例输出逐字节可复现，验收套件里的 `DogfoodTests` / `ExamplesSyncTests` 每次跑测试都重新验证这条链。夹具数字全部手工验算：178 个浇水间隔的中位数 6d、Fern 的失调 {11,8,8,13}−4 = 4 次、最重越线 13−4 = 9 天、兰花半线 7/2 = 3.5d。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_wilting_point.py`](tests/test_wilting_point.py)，84 个用例，`unittest`，夹具数字全部手工验算）：

```bash
python3 -m unittest discover -s wilting-point/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 品种表：16 种、键唯一、0 < 安全线 < 凋萎线、`species` 命令全列 | `SpeciesTableTests`（3 例） |
| 台账解析：表头/注释可选、notes 列可选、坏数字/非正数/安全线>凋萎线带行号报错、重名报首次出现行号、空台账与缺文件报错、坏 acquired 带行号 | `LedgerParseTests`（9 例） |
| 日志解析：未知植物/浇水早于购入/同盆同日重复/坏日期均带行号报错、note 列可选 | `LogParseTests`（5 例） |
| 水位四档边界：d<0.7×safe=OK、=0.7×safe 开窗、=safe 进伤害区、=wilt 判 WILTED；夏季 ×0.7（4→OK, 5→DUE, 7→PARCHED, 14→WILTED）、冬季 ×1.3；never-watered 回退购入日并亮牌；as_of 取两本账最大；`--today` 早于日志日期 exit 3 | `WaterlineTests`（13 例） |
| 主人画像：中位数奇偶口径、跨盆合并间隔、单次浇水无 cadence、che 夹具 = 6d 与 178 gaps、失配只数安全线严格小于 cadence 的盆 | `CadenceTests`（5 例） |
| 失调账本：严格大于才计失调（恰在安全线不算）、最重越线 Fern 9 天、黑名单 ≥2 次按品种聚合（单次失调的 ivy 不入榜）、绿色队友排除伤害区（零失调但 PARCHED 的 Jade 不算）、tang 全净 | `NeglectTests`（6 例） |
| 烂根灯：连续两次 < 半线才亮（兰花 3,3 < 3.5）、半线判定严格（等于不算）、单次手滑不算、che 只点名 Orchid、tang 的统一节奏被点名 SnakePlant/ZZPlant | `OverwaterTests`（7 例） |
| 报告渲染：表头/bands/cadence/neglect 逐字钉死、WILTED 区最严重在前、verdict 两分支（有凋萎/全绿）、NEVER-WATERED 亮牌、季节注记进表头 | `ReportTextTests`（7 例） |
| JSON：as_of/cadence/盆数、Fern 字段逐值（band/days 15/misses 4/worst 9）、黑名单有序 | `JsonTests`（3 例） |
| due：十盆顺序逐位钉死（已越线最重者最先）、行尾倒计时文案逐字 | `DueTests`（2 例） |
| simulate：trip 7 全要素钉死（6/10 名单+死期、浇完走剩 1/10、托付裁决）、trip 0 只剩已凋萎 2/10、trip 45 浇完走也全沉、tang 幸存分支、负数天数 exit 2 | `SimulateTests`（5 例） |
| advice：INCOMPATIBLE exit 4 + 证据行逐字、RISKY 区间（兰花 7d ∈ [6d, 9d)）、COMPATIBLE（21d ≥ 1.5×6d）、未知物种 exit 2 并列可选键、冷启动（无间隔）延期判决 | `AdviceTests`（5 例） |
| validate：che 计数逐字（10 plants / 188 events / 178 gaps）、never/single 名单 | `ValidateTests`（2 例） |
| 门禁：--fail-wilted 精确在阈值触发、超阈放行；due 亦支持 | `GateTests`（2 例） |
| CLI 契约：无子命令 exit 2、坏 --today exit 3、坏 season/trip 词/非整数天数 exit 2、缺文件 exit 3 | `CliTests`（6 例） |
| 样例同步：[`examples/build_examples.py`](examples/build_examples.py) `--check` 逐字节 | `ExamplesSyncTests`（1 例） |
| dogfood：七份提交样例与新鲜输出逐字节相等；JSON/text 恒等式（bands 计数一致）；simulate 的 at-risk 名单与水位 JSON 的凋萎日逐盆一致 | `DogfoodTests`（3 例） |

## 项目结构

```
wilting-point/
├── wilting_point.py
├── tests/test_wilting_point.py
├── examples/build_examples.py
├── examples/che-ledger.tsv           # che：十盆失守阳台，2 WILTED / 黑名单 3 种
├── examples/che-log.tsv              # 188 次浇水、178 个间隔的完整日志
├── examples/tang-ledger.tsv          # tang：五盆耐旱收藏的对照阳台
├── examples/tang-log.tsv             # 周日例行，全绿但有两盏烂根灯
├── examples/sample-report-che.txt
├── examples/sample-due-che.txt
├── examples/sample-simulate-che.txt
├── examples/sample-advice-fern.txt   # INCOMPATIBLE，exit 4
├── examples/sample-advice-snake.txt  # COMPATIBLE，exit 0
├── examples/sample-report-tang.txt
├── examples/sample-simulate-tang.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
