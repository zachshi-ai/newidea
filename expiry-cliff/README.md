# 到期悬崖 · Expiry Cliff

> 名义有效期会撒谎：护照还剩 5 个月，对大多数目的地来说已经等于零。
> A zero-dependency CLI that keeps a validity ledger for the credentials that fail silently — passports, licenses, insurance, domains, TLS certs — and measures the *margin-adjusted* distance to the cliff, not the lying nominal one.

---

## 一句话

有一类资产失效时没有任何症状：护照、驾照、保单、域名、TLS 证书——它们安静地滑向悬崖，直到你在机场值机柜台、药房、或者凌晨三点的证书告警里发现它们已经死了。更糟的是**名义有效期会撒谎**：护照上印着「2026 年 3 月到期」，但大多数国家要求入境时剩余有效期 ≥6 个月——从 2025 年 9 月起它就已经不能用了，而你手里那张卡看起来还有整整半年。手动维护一张「什么什么时候到期」的表，人人都知道该做，没人真的在做。`expiry-cliff` 的立场：**到期管理的最小可行单元不是提醒，是提前量**。每类凭证有一个「至少还剩多少天才可用」的边际（六个月规则、换证体检、续费宽限期），工具从一张登记 CSV 里算出每份凭证的**边际调整视界**（effective horizon = 到期日 − 提前量），按「谁先坠崖」排序；一条命令把**整个出行窗口对着全部凭证过闸**（离怀日期任何一份失效都不行）；再从续期历史里挖出你自己的**续期节奏**——你习惯提前多久续、每次续几年——让「现在办是早是晚」第一次有据可依。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 一家人的「行政管家」（记得所有密码、所有到期日的那个人）；跨境差旅/旅行的上班族（护照、签证、驾照的复合约束）；持有域名和证书的独立开发者（失效即事故）。 |
| **场景** | 订机票之前（「归期之后所有凭证还有效吗？」）；年度行政盘点（「家里什么先到悬崖边？」）；收到续办通知时判断早晚（「现在续会不会白丢有效期？」）；接手家庭行政工作时建立第一本账。 |
| **问题** | **失效是静默且复合的**：① 单份凭证的失效没有症状，发现即事故——机场、药房、证书告警；② 名义有效期撒谎——六个月规则、体检窗口、宽限期把「还剩 X 天」偷走一大截，人的直觉从不扣除这部分；③ 失效是**合取**的——一次出行需要护照 × 签证 × 驾照 × 保险同时有效，任何一份掉队整个计划报废，但没有工具回答「这组凭证共同的最大可用窗口是什么」；④ 续期没有账本——你从不记得自己习惯提前多久续，于是永远在「太早怕白丢」和「太晚怕误事」之间裸奔。 |
| **价值与意义** | 1) **边际调整视界**：`有效剩余 = 到期日 − 提前量 − 今天`，提前量按类别默认（passport 180 / visa 90 / driver_license 60 / domain 30 / tls_cert 21…），行级与命令行均可覆盖——名义剩余第一次被诚实地折算。<br>2) **悬崖排行**：按有效剩余升序，第一行就是先坠崖的那份，四档判定（OVERDUE / CLIFF / CAUTION / CLEAR）直接对应行动。<br>3) **出行闸门**：`trip --end 归期` 把整个窗口对全部凭证过闸，一份失效就 exit 4——「能不能成行」从感觉变成可执行检查。<br>4) **续期节奏考古**：同名凭证的多段有效期是现成的账本——中位周期（~10y）、惯常提前量（提前 46 天）、断档检测（lapsed N 天），「现在办是早是晚」有了个人基线。<br>5) **零依赖 + 纯本地**：Python 3.8 标准库，`--as-of` 钉死即逐字节可复现，家庭数据不出电脑。 |

---

## 核心思想：提前量才是有效期的诚实度量

到期管理的全部错误，都来自把「名义到期日」当「可用边界」。工具引入**提前量（margin）**——凭证可用所需的最小剩余天数——并重新定义视界：

| 概念 | 规则 | 回答的问题 |
|---|---|---|
| **提前量 margin** | 类别默认表（passport 180、visa 90、driver_license 60、id_card 30、domain 30、tls_cert 21、warranty 14、membership 7、insurance 0），行级 margin 列 > `--category-margin` > 默认表 | 「这份凭证要求至少剩多少天才可用？」 |
| **有效视界 effective horizon** | `到期日 − margin`；`有效剩余 = 有效视界 − 今天` | 「我真正还有多少天可以用它？」 |
| **悬崖带 band** | 有效剩余 <0 OVERDUE（已不能用了）/ <30 CLIFF（本周就办）/ <90 CAUTION（这个季度）/ ≥90 CLEAR（忘掉它） | 「现在该做什么？」 |
| **出行闸门 trip gate** | 每份凭证的有效视界 ≥ 归期、生效日 ≤ 出发日；任何一份 fail → exit 4 | 「这次出行能不能成行？」 |
| **续期节奏 rhythm** | 同名凭证 ≥2 段有效期：中位周期、惯常提前量（上一次到期日 − 这次生效日）、断档 | 「按我自己的习惯，现在办是早是晚？」 |
| **惯常续办窗口** | 节奏存在且有效剩余 ≤ 惯常提前量 → 标记 ↻ | 「是不是已经进了我通常会动手的窗口？」 |

四条诚实条款刻在实现里：**「今天」只属于真实使用**——`--as-of` 默认今天，但钉死它即逐字节可复现（仓库里的样例报告全部钉在 2025-12-01）；**FUTURE 不是数据错误**——还没生效的凭证单列一档，出行闸门对它的检查是「生效日 ≤ 出发日」，不是报错；**断档（lapse）如实显示**——两段有效期之间的空窗不抹平，前一段的到期日与后一段的生效日之差就是你不设防的天数；**未分类不算废票**——没写类别的凭证按 margin 0 处理照常入账，名义有效期就是它的诚实边界。

## 安装（零依赖）

只需 Python 3.8+，无需 `pip install` 任何东西。

```bash dd:ignore
python3 expiry_cliff.py horizon family-registry.csv   # 家里什么先坠崖？
```

## 命令速查

```bash dd:ignore
python3 expiry_cliff.py horizon registry.csv                        # 悬崖排行：谁先坠崖
python3 expiry_cliff.py horizon registry.csv --as-of 2025-12-01     # 钉死参照日 → 逐字节可复现
python3 expiry_cliff.py horizon registry.csv --format json          # 机读
python3 expiry_cliff.py horizon registry.csv --redact               # 持有人哈希脱敏，报告可外发
python3 expiry_cliff.py trip registry.csv --start 2026-04-30 --end 2026-05-08  # 出行过闸，一份失效 exit 4
python3 expiry_cliff.py horizon registry.csv --category-margin passport=120        # 覆盖类别提前量
python3 expiry_cliff.py show registry.csv "Passport Aya"            # 单凭证全部有效期 + 续期节奏
```

## 一个真实样例

张家的登记账（`python3 examples/build_examples.py` 可从零重建，日期全部钉死，`--check` 逐字节校验）：一本用了十年的护照、即将到期的车险、一个域名、一张 TLS 证书、一张健身卡、一本刚办的新护照。参照日钉在 2025-12-01，[`examples/sample-horizon.txt`](examples/sample-horizon.txt) 的判决：

```text dd:ignore
  credentials    : 8 credentials · 1 overdue · 2 in the cliff band · 3 cautioning · 2 clear
  first to fall  : Passport · Aya Zhang (effective 2025-09-02, -90d behind you)

  name             holder       category       ends         margin left(eff)  band
  Passport         Aya Zhang    passport       2026-03-01      180      -90d  !! OVERDUE
  HomeTLS          Zhang Family tls_cert       2026-01-04       21       13d  ! CLIFF
  DriverLicense    Aya Zhang    driver_license 2026-02-28       60       29d  ! CLIFF
  ...

  inside your usual renewal window (history says you renew early):
  ↻ Passport         you usually renew ~46d early · every ~10y
```

读法：**名义剩余 90 天，有效剩余 −90 天**——那本护照事实上已经死了整整一个季度，而卡片上还印着 2026。TLS 证书名义上还有 34 天，扣掉 21 天宽限期只剩 13 天。下面的 ↻ 是历史账本在说话：过去两本护照你都是提前 46 天续的，这次已经晚了 136 天。然后是出行闸门（[`examples/sample-trip.txt`](examples/sample-trip.txt)）——五一假期想走？8 份凭证 6 份过不了：

```text dd:ignore
  8 credentials checked, 6 fail the gate:
  ! Passport         ends 2026-03-01 · margin 180 · effective 2025-09-02 — dead 248d before you return
  ! HomeTLS          ends 2026-01-04 · margin  21 · effective 2025-12-14 — dead 145d before you return
  ...
  gate: FAIL
```

[`examples/sample-show.txt`](examples/sample-show.txt) 里护照的完整档案：两段有效期、46 天的续期提前量、节奏 ~10 年——一本凭证的行政生命史，一屏读完。

## dogfood：样例账本即狗粮

```text dd:ignore
$ python3 examples/build_examples.py --check
examples in sync
```

家庭凭证数据天然敏感，本件不内置任何真实登记。dogfood 的形式与仓库传统一致：**三份样例报告由交付代码本身渲染**（`examples/build_examples.py` 走与 CLI 完全相同的代码路径），CI 用 `--check` 逐字节校验——报告里的每一个数字都能从钉死的登记与 `--as-of` 复现，一份手写的样例都不存在。

## 验收标准与测试

验收标准全部转成自动化测试（[`tests/test_expirycliff.py`](tests/test_expirycliff.py)，39 个用例，`unittest` + 合成登记表）：

```bash
python3 -m unittest discover -s expiry-cliff/tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 登记表解析：中英文表头别名、最小三列即可、BOM 与空行、四种日期写法、margin 缺省、end<start 报行号、无表头报错 | `ParserTests`（7 例） |
| 提前量解析：行级 margin > `--category-margin` > 类别默认表 > 未分类 0 | `MarginTests`（4 例） |
| 悬崖带数学：−1/0/29/30/89/90 六个边界、有效视界 = 到期 − margin、未生效 FUTURE 档 | `BandTests`（3 例） |
| 视界排行：按有效剩余升序、counts 统计、名义剩余 vs 有效剩余的差值、`--top` 截断 | `HorizonTests`（4 例） |
| 出行闸门：FAIL exit 4 与失败清单、`dead Nd before you return` 措辞、全过 PASS exit 0、`--end` 缺省 `--start`、归期早于出发日报错 | `TripTests`（5 例） |
| 续期节奏：中位周期与提前量、单段历史无节奏、惯常续办窗口标记、断档提前量钳到 0、show 的历史期排序 | `RhythmTests`（5 例） |
| 隐私：`--redact` 隐藏持有人保留条目名（text/json） | `RedactTests`（2 例） |
| CLI：无参数 exit 2、文件缺失 / `--as-of` 非法 / show 未匹配 exit 3、同名多持有人歧义列持有人、`--as-of` 缺省今天 | `CliTests`（6 例） |
| **dogfood：样例逐字节同步 + demo 数字核验** | `DogfoodTests`（3 例） |

## 项目结构

```
expiry-cliff/
├── expiry_cliff.py
├── tests/test_expirycliff.py
├── examples/build_examples.py
├── examples/family-registry.csv
├── examples/sample-horizon.txt
├── examples/sample-trip.txt
├── examples/sample-show.txt
├── METHODOLOGY.md
└── README.md
```

## License

MIT © 2026
