# 文档漂移 · Doc Drift

<!-- verified: 2026-08-16; ttl: 180d -->
> 给文档装上「编译器」：引用失效自动报警，过期声明自动催审。
> A methodology + a zero-dependency CLI that makes doc rot loud instead of silent.

---

## 一句话

代码有编译器和测试守门，**文档没有任何守门人**——文件改名、符号挪走、示例过时，全都静默发生，直到某个新人在第 37 次踩坑时才发现，此后文档沦为「仅供参考」。`doc-drift` 把「文档还不可信」变成一个**机器可判定**的问题：仓库内引用是否仍然存在（ERROR），关键声明是否还在保鲜期内（WARN）。

---

## 它解决谁的、什么场景下的、什么问题

| 维度 | 说明 |
|---|---|
| **角色** | 开源项目维护者、团队文档负责人、平台/开发者体验工程师——任何维护「长寿命文档」的人。 |
| **场景** | 仓库里的 Markdown 文档（README、CONTRIBUTING、docs/、设计文档）引用着文件路径、本地链接、代码符号、示例命令；而代码在持续重构演进。 |
| **问题** | **文档腐烂是静默的**。代码改名有编译器报错、行为回归有测试拦截，唯独文档引用失效没有任何信号——没有编译错误，没有红灯，只有链接 404 和「按文档做做不通」。等发现时，信任已经没了：团队开始说「别看文档，看代码」，文档投入全部沉没。 |
| **价值与意义** | 1) **把「文档可信度」变成 CI 信号**：漂移即红灯，与编译错误同级。<br>2) **保鲜期制度**：关键声明带 `verified` 日期与 TTL，过期自动催审——「没人复核过」第一次变得可见。<br>3) **可量化**：漂移密度（问题/百引用）让文档健康度可跟踪、可考核。<br>4) **防御的是信任**：文档的价值不在被写出来，而在被相信；doc-drift 守的是后者。 |

---

## 核心思想：文档漂移三分类

| 类型 | 定义 | 检测方式 |
|---|---|---|
| **引用漂移** | 文档提到的文件/目录/符号已不存在或已改名 | ✅ 全自动（存在性验证） |
| **保鲜漂移** | 声明依赖当时的环境/版本，没人知道现在是否仍成立 | 🔶 半自动（`verified` 保鲜期，过期催人工复审） |
| **语义漂移** | 文档字面仍「正确」，但意图已偏 | ❌ 纯人工（保鲜期把该复审的行推到你面前） |

工具只负责前两类——这是确定性可判定的部分；第三类通过保鲜期制度转化为「定期人工复审」的仪式。

---

## 安装（零依赖）

只需 Python 3.8+ 标准库，无需 `pip install` 任何东西。

```bash
python3 doc_drift.py scan .            # 扫描当前目录
```

退出码对 CI 友好：`0` = 文档一致 · `1` = 发现漂移 · `2` = 用法错误。

---

## 引用与保鲜期语法

```markdown dd:ignore
用反引号写文件路径，才会被验证：`src/live.py`、`docs/guide.md`

符号引用用 path::Symbol 语法（验证符号真的在文件里）：`src/live.py::run_checks`

普通本地链接自动验证（外链/锚点跳过）：[指南](docs/guide.md)

关键声明打保鲜期戳（默认 TTL 180 天，过期 → WARN 催审）：
<!-- verified: 2026-08-16; ttl: 90d -->
本节描述的构建方式适用于 1.x 系列。

豁免一行（类型提及、历史路径等非实例引用）：
文件名 `METHODOLOGY.md` 泛指各点子目录 <!-- dd:ignore: 类型提及，非具体引用 -->
```

规则细节：带斜杠的路径在**正文、行内代码、代码块**三种位置都会验证；裸文件名（无斜杠）只在**代码内**验证（精度优先）；`https://` 外链、`#锚点`、版本号（`3.12`）、系统绝对路径（`/etc/hosts`）一律不误报。

---

## 命令速查

```bash
doc-drift scan [路径...]            # 扫描 markdown（默认当前目录；默认命令可省略）
doc-drift scan --json               # 机器可读输出（CI 摘要、趋势统计）
doc-drift scan --exclude demo-repo  # 排除路径（glob 匹配路径或任一部分，可重复）
doc-drift scan --fail-on warn       # error（默认）/ warn / never 控制退出码
doc-drift scan --ttl-days 90        # 无自定义 TTL 的保鲜期戳的默认天数（默认 180）
doc-drift scan --today 2026-08-16   # 固定"今天"，报告可复现（测试/归档用）
doc-drift stamp --ttl 90            # 生成一条保鲜期戳，粘贴进文档
```

---

## 一个真实样例

见 [`examples/`](examples/)。`examples/demo-repo/` 是一个故意埋了漂移的迷你仓库，`examples/expected-report.txt` 是工具的真实输出（`--today` 固定，永不变化）：

```text dd:ignore
README.md
     6  WARN   stale           '2026-01-05'  ttl 90d expired 133d ago
    15  ERROR  missing-file    'src/gone.py'  referenced in code span
    16  ERROR  missing-file    'old_notes.txt'  referenced in code span
    17  ERROR  missing-file    'docs/missing.md'  referenced in link
    18  ERROR  missing-symbol  'src/live.py::gone_fn'  symbol not found (from code span)
    20  ERROR  future-stamp    '2026-12-01'  verified date is in the future
```

可用 `python3 examples/build_examples.py` 重新生成（脚本会自校验埋入的漂移计数，变了就报警）。

**首次 dogfood 即抓到真实漂移**：本工具完成后第一件事是扫描本仓库（newidea），立刻发现 [#1 决策债务](../decision-debt/) 重组进子目录后，README 里的项目结构树还是旧的扁平布局——5 处引用失效。已修复，并把该场景固化为验收测试 `DogfoodTests`。

---

## 融入工作流

```yaml
# .github/workflows/docs.yml —— 文档漂移与编译错误同级
name: docs
on: [push, pull_request]
jobs:
  drift:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python3 doc-drift/doc_drift.py scan . --exclude demo-repo
```

本地节奏：提交前跑一次 `scan`（等于给文档做 `make`）；每周文档复审日看一次 WARN（哪些保鲜期到了该重验）。

详见 [`METHODOLOGY.md`](METHODOLOGY.md)。

---

## 验收标准与测试

验收标准全部转成自动化测试（`tests/test_drift.py`，44 个用例，`unittest` 标准库）：

```bash
python3 -m unittest discover -s tests -v
```

| 验收标准 | 对应测试 |
|---|---|
| 提取：正文/行内代码/代码块三类位置的路径全部识别 | `ExtractionTests`（11 例） |
| 精度：URL、`#锚点`、`//协议相对`、版本号、系统绝对路径、无扩展目录零误报 | `FalsePositiveTests`（5 例） |
| 解析：相对文档目录与扫描根两个基准，链接 URL 解码、站内绝对链接 | `ResolutionTests`（6 例） |
| 符号：`path::Symbol` 命中/未命中/文件缺失三态 | `ResolutionTests` |
| 保鲜期：默认/自定义 TTL、过期 WARN、未来日期 ERROR、非法日期 ERROR、超期天数 | `StampTests`（5 例） |
| 端到端：退出码（0/1/2）、`--fail-on`、`--exclude`、`--today`、`--json` 字段完整 | `EndToEndTests`（7 例） |
| 样例同步：demo-repo 扫描 == expected-report.txt，且漂移计数为手写硬断言（防生成器自我循环） | `ExamplesSyncTests`（3 例） |
| 子进程独立可运行（版本、扫描、JSON、stamp） | `CliTests`（5 例） |
| **dogfood：本仓库自身文档 0 漂移** | `DogfoodTests`（1 例） |

---

## 项目结构

```
doc-drift/
├── doc_drift.py               # 核心 CLI（单文件，纯标准库）
├── tests/test_drift.py        # 验收测试套件
├── examples/build_examples.py # 重建 demo-repo 并自校验漂移计数
├── examples/demo-repo/        # 故意漂移的迷你仓库（4 个文件）
├── examples/expected-report.txt
├── METHODOLOGY.md             # 方法论与 FAQ
└── README.md
```

---

## 设计取舍

- **为什么只查「存在性」不查「内容」**：存在性是确定性的（在/不在），内容匹配是启发式的（必然误报）。语义漂移交给保鲜期制度 + 人工，不伪装成机器能解的问题。
- **为什么裸文件名只在代码内验证**：正文里「详见 README」这类自然语言提及太随意，验证必然误报满天飞；反引号内的文件名则是明确的「我在指称这个文件」——把反引号变成一种轻量的引用规范。
- **为什么保鲜期默认 WARN 而非 ERROR**：过期≠错误，只是「没人复核过」。把它做成错误会逼人撕掉戳；做成催审才可持续。
- **为什么不用 markdown 解析库**：零依赖（Python 3.8+ 裸机可跑）换来的部署面，远大于解析库在常见文档上的收益；行级正则 + 围栏状态机覆盖 95% 的真实写法，其余用 `dd:ignore` 显式豁免。

---

## License

MIT © 2026
