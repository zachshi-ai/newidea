# references/ — 参考数据审计链

内嵌在 `../off_track.py` 里的 LMS 参考表不是手抄的,是从这三个官方文件逐节点生成的:

| 文件 | 内容 | 覆盖 |
| --- | --- | --- |
| `lenageinf.csv` | Length-for-age, WHO 2006 标准 | 0-24 月(账本取 ≤24.0) |
| `statage.csv` | Stature-for-age, CDC 2000 | 2-20 岁(账本取 >24.0) |
| `bmiagerev.csv` | BMI-for-age, CDC 2000 | 2-20 岁 |

来源:<https://www.cdc.gov/growthcharts/percentile_data_files.htm>
(下载于 2026-09-06,只保留 `Sex,Agemos,L,M,S` 五列;原文件中段自带的重复表头行已删。)

## 再生成内嵌表

```bash
cd references && python3 embed_tables.py
# 输出写入 /tmp/embedded_tables.py,拼回 ../off_track.py 文件尾部的 HFA_DATA / BMI_DATA 段
```

## 核对内嵌表与原件一致

`../off_track.py validate` 与测试套件对每个内嵌节点做 LMS 往返自检;再对回原件:

```python
import csv, off_track as T
for f, tag in (('statage.csv','HFA'), ('lenageinf.csv','HFA'), ('bmiagerev.csv','BMI')):
    for r in csv.DictReader(open(f)):
        ...  # 每个 (Sex, Agemos) 节点的 L/M/S 与内嵌值差 < 1e-9
```

原始文件不进 git 的取舍:三者合计 ~200KB 且逐字节可从官方 URL 重取;内嵌子集(922 节点)已由测试与 validate 双向钉死。若官方文件将来改版,以儿保手册和医生为准——本件永远不打补丁式的"新标准"。
