# 药箱点名 · Medicine Rollcall

> 药品有两口钟：包装效期钟印在盒上，开封效期钟只活在「好像刚开没多久」的记忆里——盒上印着 2027 年的儿童布洛芬，作为药在 4 月就死了。
> A zero-dependency CLI that audits the family medicine cabinet as a readiness ledger: every box answers roll call on two clocks (packaging expiry vs. in-use expiry after opening), four半夜场景 gets a coverage verdict, and hoarding is cross-examined against shelf life.

## 谁在什么场景下的什么问题

**角色**：小陈，两岁孩子的爸爸。家里有个「什么药都有」的药箱——准确说，是「什么药都**有过**」。

**场景**：半夜 2 点，孩子烧到 38.9°C。他冲到药箱前翻出那瓶布洛芬混悬液——盒子上印着「有效期至 2027 年 6 月」，他松了口气。

**问题**：那瓶混悬液是 3 月 14 日开封的。糖浆类开封后 30 天用完，它作为药在 4 月 13 日就已经死了——**药盒没过期，药死了**。这不是小陈的疏忽，是结构性的盲区：

1. **药品有两口钟**。包装效期钟印在盒上，人人会看；开封效期钟（眼药水 28 天、糖浆 30 天、开封碘伏 30 天）取决于剂型，日期只存在于开封那一刻的记忆里——而没有人记得那一刻。
2. **药箱没有「场景」这个概念**。囤药按病种囤（感冒了→囤 4 盒感冒灵），但半夜真正会来的场景是发烧、腹泻、外伤、过敏。囤的是感冒药，半夜来的却是发烧——**囤积和战备从来是两本账**。
3. **过期药沉在箱底**，药箱是全家唯一「买完就再没被盘点过」的角落。战备率（打开药箱，几成弹药真的能用）的分母，从来没有存在过。
4. **存放是第三口暗钟**：儿童退热栓在浴室镜柜里待了三年——栓剂 35°C 就软化，浴室的夏天比栓剂的熔点热。

## 价值与意义

- **把「应该没事吧」变成一次点名**：每一盒药对两口钟各自报数，可用截止日精确到天——死因（包装钟 / 开封钟）逐一归因。
- **把「药箱挺全的」变成四个场景的裁决**：半夜真会来的四个场景各自过闸，儿童剂型单独一栏——**孩子的药箱比大人的先阵亡**（儿童药开封即弃、用不完即浪费，大人总舍不得补货）。
- **把「囤点药安心」对账**：同款 ≥3 盒点名，并与效期交叉质证——为感冒囤的 4 盒，感冒没来，效期先来。
- **把「以后收拾」变成一条衰减曲线**：什么都不做，90 天后战备率从 43.5% 掉到 26.1%——药箱不是仓库，是沙漏。

诚实条款：账本只记你**声称**的事实（快照自报，不扫药箱）；开封效期默认表是常识值不是药典，**盒上说明永远赢**（行内 `open_days` 覆盖）；工具不做医疗建议、永不提剂量，红灯文案指向药师和医生；补什么药、扔不扔，仍是人的决定。

## 形态与用法

零依赖 CLI（Python 3.8+ 标准库），账本是一张手编 TSV 库存快照：

```bash
python3 medicine_rollcall.py report   examples/medicine_cabinet.tsv --as-of 2026-09-04
python3 medicine_rollcall.py rollcall examples/medicine_cabinet.tsv --as-of 2026-09-04
python3 medicine_rollcall.py night    examples/medicine_cabinet.tsv --scene fever --who kid
python3 medicine_rollcall.py coverage examples/medicine_cabinet.tsv --as-of 2026-09-04
python3 medicine_rollcall.py hoard    examples/medicine_cabinet.tsv --as-of 2026-09-04
python3 medicine_rollcall.py stash    examples/medicine_cabinet.tsv
python3 medicine_rollcall.py simulate examples/medicine_cabinet.tsv --days 90 --as-of 2026-09-04
python3 medicine_rollcall.py validate examples/medicine_cabinet.tsv
```

账本列：`name / role / form / kids / qty / unit / expiry / opened / location / open_days / note`

- `role`（场景角色）：`antipyretic` 退烧止痛 · `antidiarrheal` 腹泻肠胃 · `disinfectant` 外伤消毒 · `antihistamine` 抗过敏 · `dressing` 敷料辅助 · `supplement` 补剂 · `other`
- `form`（剂型，决定开封钟默认效期）：`blister` 铝箔/袋装密封（无开封钟）· `bottle` 瓶装片剂 180d · `syrup` 糖浆混悬液 30d · `eyedrops` 眼药水 28d · `cream` 软膏 180d · `iodine` 碘伏消毒液 30d · `suppository` 栓剂 30d · `lozenge` 含片泡腾 90d · `spray` 喷雾 90d · `other` 90d
- `expiry` 包装效期；`opened` 开封日（可空，开封钟的起点）；`open_days` 可空，按说明书覆盖默认开封效期
- 缺省 as-of = 账本最近一次开封日（快照账本没有事件流，「账本的今天」就是最后一次开封），`--as-of` 显式钉死后任何机器逐字节复现

## 验收标准（全部转为自动化测试）

- **A1 双钟**：可用截止 = min(包装效期, 开封日+开封效期)；`blister` 无开封钟；`open_days` 覆盖剂型默认；到期日当天算在期内。
- **A2 判决阶梯**：EXPIRED > OPENED_OUT > LOW > READY 优先级唯一；Σ(四状态) = 总盒数，恒等式精确钉死；LOW 线可调（默认 qty ≤ 3）。
- **A3 场景矩阵**：fever/gut/wound/allergy 四场景 GREEN/YELLOW/RED 判定；场景弹药恒等式 = 该 role 的 READY 盒数；任一 RED → exit 4。
- **A4 半夜测试**：`night` 场景全灭判 BARE exit 4；`--who kid` 只认儿童剂型（全量 GREEN 同时儿童栏 BARE）；弹药全 LOW 判 AMMO-LOW 黄牌 exit 0；未知场景 exit 2。
- **A5 囤积**：同名 ≥3 盒点名；组内 ≥half 将在 90 天内过期 → exit 4。
- **A6 存放**：温湿敏感剂型 × 浴室关键词 → 警告；热敏剂型（栓剂/糖浆）× 车内/阳台/窗台/暖气 → exit 4；密封 blister 免疫。
- **A7 衰减推演**：simulate 第 0 天战备率 == report 战备率（恒等式）；曲线对天数单调不增；翻牌事件精确到天。
- **A8 拒答**：盒数 <5 → THIN exit 3（report/coverage/simulate）；`night` 恒开庭——半夜不等样本。
- **A9 护栏**：坏日期 / qty≤0 / opened 晚于 as-of / 未知 role 或 form → exit 2；opened 晚于 expiry → 矛盾披露。
- **A10 可复现**：`--as-of` 钉死后两次运行逐字节一致；缺省 as-of = 最近开封日且报告头部披露；全账无开封记录时拒绝猜测、要求显式 `--as-of`（exit 2）。

## 测试与示例

```bash
python3 -m unittest discover -s medicine-rollcall/tests   # 57 tests
python3 medicine-rollcall/examples/build_examples.py --check  # 快照 CI 字节级校验
```

示例账本：小陈家的药箱，as-of 2026-09-04，23 盒——10 READY · 3 LOW · 4 OPENED_OUT · 6 EXPIRED，战备率 43.5% 亮红灯 exit 4。儿童退烧双保险全部阵亡（混悬液开封死、退热栓包装死还搁在浴室）、外伤场景三个消毒剂全灭、感冒灵 4 盒里 3 盒在 90 天内过期、眼药水的开封钟只剩 2 天。

## 与近邻的边界

- **expiry-cliff** 管会静默失效的**凭证**（护照/保单/域名）的续期提前量——「什么时候该去办」；本件管**实物药品**的第二口钟与场景战备——「今晚接不接得住」。开封效期这口钟凭证没有。
- **fridge-void** 记食物的**结局**（吃了/扔了，以天计）；本件记药箱的**可用性**（能不能用，快照审计），不追踪结局。
- **odometer-illusion** 的双钟是里程钟/日历钟（汽车保养）；本件的双钟是包装/开封（药品效期）——结构同构，领域无关。
- **borderline** 管化验指标的方向；本件管急救弹药的存量。二者都不做诊断。
