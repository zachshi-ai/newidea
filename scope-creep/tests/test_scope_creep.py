# -*- coding: utf-8 -*-
"""scope-creep acceptance tests — hand-computed figures nailed first."""

import argparse
import atexit
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")))
import scope_creep as sc  # noqa: E402

TMP = tempfile.mkdtemp(prefix="scope_creep_tests_")


@atexit.register
def _cleanup():
    shutil.rmtree(TMP, ignore_errors=True)


_counter = [0]


def write_ledger(quote, changes, meta):
    _counter[0] += 1
    d = os.path.join(TMP, "case%03d" % _counter[0])
    os.makedirs(d)
    paths = []
    for name, text in (("quote.tsv", quote), ("changes.tsv", changes),
                       ("meta.tsv", meta)):
        p = os.path.join(d, name)
        if text is not None:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(text)
        paths.append(p)
    return paths


def run_cli(args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = sc.main(args)
    return code, out.getvalue(), err.getvalue()


def cli_args(cmd, paths, extra=None):
    a = ["--quote", paths[0], "--changes", paths[1], "--meta", paths[2],
         cmd]
    return a + (extra or [])


def load(paths, as_of=None):
    return sc.load_ledger(paths[0], paths[1], paths[2], as_of)


# ------------------------------------------------------------ sample

SAMPLE_Q = """# 老陈家的 89m² 全包合同
category	item	unit	qty	price	amount
拆改	墙体拆改及渣土装袋	m²	17	112	1904
水电	水电改造（预收 100m，按实结算）	m	100	80	8000
瓦工	卫生间厨房墙地砖铺贴	m²	52	95	4940
瓦工	地面找平	m²	40	45	1800
吊顶	客厅双眼皮吊顶	m	34	88	2992
油漆	墙面基层处理及乳胶漆	m²	230	56	12880
瓷砖	墙地砖主材（含阳台）	m²	58	135	7830
地板	强化复合地板（含安装）	m²	62	178	11036
室内门	实木复合门（含门套五金）	樘	4	1580	6320
橱柜	整体橱柜（地柜+吊柜 4.2m）	m	4.2	1880	7896
卫浴洁具	马桶+花洒+浴室柜	套	2	3900	7800
灯具开关	全屋灯具及开关面板	项	1	4200	4200
封窗	阳台断桥铝封窗	m²	12	680	8160
美缝	全屋瓷砖美缝	m²	85	28	2380
保洁	开荒保洁	次	1	800	800
"""

SAMPLE_C = """date	type	category	item	unit	qty	price	amount	who	reason
2025-10-12	add	垃圾清运	装修垃圾外运	车	2	600	1200	contractor	说好全包
2025-10-20	add	防水	卫生间墙面防水返高	m²	12	200	2400	contractor	不做防水楼下遭殃
2025-11-05	add	瓦工	墙面挂网找平	m²	36	50	1800	contractor	原墙不平
2025-11-18	upgrade	瓷砖	全屋瓷砖升级差价	m²	58	33	1900	owner	主材升级
2025-11-18	upgrade	卫浴洁具	花洒升级差价	项	1	1400	1400	owner	恒温花洒
2025-11-26	add	水电	开关插座移位增补	位	8	85	680	contractor	位置不顺手
2025-12-08	reaudit	水电	水电按实结算（100m→156m）	m	56	80	4480	contractor	米数超预估
2025-12-22	deduct	室内门	窗套减项	樘	2	650	1300	owner	不做了
2025-12-30	reaudit	橱柜	橱柜米数复核（4.2m→4.9m）	m	0.7	1880	1316	contractor	多 0.7m
2026-01-05	add	灯具开关	晾衣架及挂件安装	项	1	850	850	contractor	要晾衣服
	add	瓦工	卫生间壁龛砌筑	个	2	550	1100	contractor	顺手做
"""

SAMPLE_M = """mode	full
start	2025-10-01
plan	2026-01-10
settle	2026-01-18
settle_amount	103664
"""


def sample():
    return write_ledger(SAMPLE_Q, SAMPLE_C, SAMPLE_M)


# ------------------------------------------------------- tiny ledgers

def base_quote(rows=10, amount=10000):
    head = "category	item	unit	qty	price	amount\n"
    return head + "".join(
        "瓦工	项%d	m²	1	%d	%d\n" % (i, amount, amount)
        for i in range(rows))


def change_line(date_, typ, cat, item, amt, who, reason="x"):
    return "%s\t%s\t%s\t%s\t项\t1\t%s\t%s\t%s\t%s\n" % (
        date_, typ, cat, item, amt, amt, who, reason)


class TestSampleLedger(unittest.TestCase):
    """The demo ledger: hand-computed, byte-nailed."""

    @classmethod
    def setUpClass(cls):
        cls.paths = sample()
        cls.st = load(cls.paths)

    def test_quote_total(self):
        # 1904+8000+4940+1800+2992+12880+7830+11036+6320+7896+7800+4200
        #  +8160+2380+800
        self.assertAlmostEqual(self.st["quote_total"], 88938.0, places=6)

    def test_net_and_settlement(self):
        # adds 1200+2400+1800+680+850 = 6930; upgrades 1900+1400 = 3300;
        # reaudits 4480+1316 = 5796; deduct 1300
        self.assertAlmostEqual(self.st["net"], 14726.0, places=6)
        self.assertAlmostEqual(self.st["settlement"], 103664.0, places=6)

    def test_change_rate(self):
        self.assertAlmostEqual(self.st["rate"], 14726 / 88938 * 100,
                               places=9)
        self.assertGreater(self.st["rate"], 15.0)  # AMBUSH territory

    def test_passive_share(self):
        # contractor positive 12726 / gross positive 16026
        self.assertAlmostEqual(self.st["gross_pos"], 16026.0, places=6)
        self.assertAlmostEqual(self.st["passive"], 12726 / 16026 * 100,
                               places=6)
        self.assertGreater(self.st["passive"], 50.0)  # LOWBALL

    def test_reaudit_share(self):
        self.assertAlmostEqual(self.st["rea_share"], 5796 / 16026 * 100,
                               places=6)

    def test_monthly_split(self):
        m = self.st["monthly"]
        self.assertAlmostEqual(m["2025-10"], 3600.0, places=6)
        self.assertAlmostEqual(m["2025-11"], 5780.0, places=6)
        self.assertAlmostEqual(m["2025-12"], 4496.0, places=6)  # 4480-1300+1316
        self.assertAlmostEqual(m["2026-01"], 850.0, places=6)
        self.assertAlmostEqual(sum(m.values()), 14726.0, places=6)

    def test_final_audit_report(self):
        code, out, _ = run_cli(cli_args("report", self.paths))
        self.assertEqual(code, sc.EXIT_GATE)
        self.assertIn("AMBUSH", out)
        self.assertIn("LOWBALL", out)
        self.assertIn("16.56%", out)
        self.assertIn("79.41%", out)
        self.assertIn("103,664.00", out)
        self.assertIn("FINAL AUDIT", out)

    def test_in_progress_report(self):
        code, out, _ = run_cli(cli_args(
            "report", self.paths, ["--as-of", "2025-12-01"]))
        self.assertEqual(code, sc.EXIT_GATE)
        self.assertIn("FORESHADOW", out)
        self.assertIn("IN PROGRESS", out)
        self.assertNotIn("FINAL AUDIT", out)
        # only orders up to 2025-12-01: 1200+2400+1800+1900+1400+680
        self.assertIn("+¥9,380.00", out)
        # declared settlement must NOT be shown mid-flight
        self.assertNotIn("declared settlement", out)

    def test_projection_value(self):
        st = load(self.paths, as_of=sc.parse_date("2025-12-01", "x"))
        self.assertEqual(st["elapsed_days"], 61)
        self.assertEqual(st["total_days"], 101)
        want = 9380 / 88938 * 100 * 101 / 61
        self.assertAlmostEqual(st["projection"], want, places=9)
        self.assertAlmostEqual(want, 17.46, places=2)
        self.assertGreater(want, 15.0)

    def test_census_high_absences(self):
        code, out, _ = run_cli(cli_args("census", self.paths))
        self.assertEqual(code, sc.EXIT_GATE)
        for trade in ("防水", "垃圾清运", "管理费"):
            self.assertIn("! %s" % trade, out)
        for trade in ("木工", "监理"):
            self.assertIn("- %s" % trade, out)
        self.assertIn("AMBUSH PRE-LOADED", out)

    def test_census_ignores_as_of(self):
        code, out, _ = run_cli(cli_args(
            "census", self.paths, ["--as-of", "2025-10-01"]))
        self.assertEqual(code, sc.EXIT_GATE)
        self.assertIn("防水", out)

    def test_court_redo(self):
        code, out, _ = run_cli(cli_args("court", self.paths))
        self.assertEqual(code, sc.EXIT_GATE)
        self.assertIn("REDO", out)
        self.assertIn("+1,100.00", out)
        # final audit: no projection theatre, the after-rate speaks
        self.assertIn("17.79%", out)
        self.assertNotIn("projection", out)

    def test_court_attribution(self):
        _c, out, _ = run_cli(cli_args("court", self.paths))
        self.assertIn("+12,726.00", out)   # contractor gross
        self.assertIn("+3,300.00", out)    # owner gross
        self.assertIn("36.17%", out)       # reaudit share

    def test_pending_excluded_from_money(self):
        # pending 1100 must stay out of net, settlement, monthly
        self.assertAlmostEqual(self.st["net"], 14726.0, places=6)
        self.assertNotIn("2026-02", self.st["monthly"])
        st = load(self.paths, as_of=sc.parse_date("2026-02-01", "x"))
        self.assertAlmostEqual(st["net"], 14726.0, places=6)

    def test_compare_two_bids(self):
        q2 = os.path.join(os.path.dirname(self.paths[0]), "quote2.tsv")
        with open(q2, "w", encoding="utf-8") as fh:
            fh.write(BID_B)
        code, out, _ = run_cli(cli_args(
            "compare", self.paths, ["--quote2", q2]))
        self.assertEqual(code, sc.EXIT_GATE)
        self.assertIn("8,492.00", out)     # headline gap
        self.assertIn("2,572.00", out)     # common subtotal gap
        self.assertIn("5,920.00", out)     # trades only B prices
        self.assertIn("6,234.00", out)     # settlement overshoots bid B
        self.assertIn("systematic", out)

    def test_validate_green(self):
        code, out, _ = run_cli(cli_args("validate", self.paths))
        self.assertEqual(code, sc.EXIT_OK)
        self.assertNotIn("FAIL", out)
        self.assertIn("PASS", out)


BID_B = """category	item	unit	qty	price	amount
拆改	墙体拆改及渣土装袋	m²	17	112	1904
水电	水电改造（预收，按实结算）	m	100	85	8500
防水	卫生间墙地面防水	m²	12	185	2220
瓦工	卫生间厨房墙地砖铺贴	m²	52	95	4940
瓦工	地面找平	m²	40	45	1800
吊顶	客厅双眼皮吊顶	m	34	88	2992
油漆	墙面基层处理及乳胶漆	m²	230	58	13340
瓷砖	墙地砖主材（含阳台）	m²	58	140	8120
地板	强化复合地板（含安装）	m²	62	182	11284
室内门	实木复合门（含门套五金）	樘	4	1650	6600
橱柜	整体橱柜（地柜+吊柜 4.2m）	m	4.2	1950	8190
卫浴洁具	马桶+花洒+浴室柜	套	2	3950	7900
灯具开关	全屋灯具及开关面板	项	1	4600	4600
封窗	阳台断桥铝封窗	m²	12	680	8160
美缝	全屋瓷砖美缝	m²	85	28	2380
保洁	开荒保洁	次	1	800	800
垃圾清运	装修垃圾外运	车	2	450	900
管理费	工程管理费	项	1	2800	2800
"""


# ------------------------------------------------------ verdict lines

class TestVerdictBoundaries(unittest.TestCase):
    """Rate boundaries nailed at 5% / 15%, passive at 50% (1e-9).
    All verdict ledgers are FINAL (settle anchor) so the projection
    theatre stays out of the assertion."""

    def ledger(self, changes_text, net_want, rate_want,
               quote_rows=10, quote_amount=10000):
        q = base_quote(quote_rows, quote_amount)
        m = ("mode	full\nstart	2025-10-01\nplan	2026-01-10\n"
             "settle	2025-10-31\nsettle_amount	%.2f\n"
             % (quote_amount * quote_rows + net_want))
        p = write_ledger(q, changes_text, m)
        st = load(p)
        self.assertAlmostEqual(st["net"], net_want, places=4)
        self.assertAlmostEqual(st["rate"], rate_want, places=4)
        self.assertTrue(st["final"])
        return p

    def test_exactly_at_creep_line(self):
        # net 5000 on 100000 == 5.00% exactly -> HEALTHY (<= line)
        p = self.ledger(
            "date	type	category	item	unit	qty	price	amount	who	reason\n"
            "2025-10-05	add	瓦工	加项1	项	1	3000	3000	owner	x\n"
            "2025-10-06	add	瓦工	加项2	项	1	3000	3000	owner	x\n"
            "2025-10-07	deduct	瓦工	减项	项	1	1000	1000	owner	x\n",
            5000.0, 5.0)
        code, out, _ = run_cli(cli_args("report", p))
        self.assertEqual(code, sc.EXIT_OK)
        self.assertIn("HEALTHY", out)

    def test_just_over_creep_line(self):
        p = self.ledger(
            "date	type	category	item	unit	qty	price	amount	who	reason\n"
            "2025-10-05	add	瓦工	加项	项	1	3000	3000	owner	x\n"
            "2025-10-06	add	瓦工	加项2	项	1	3000	3000	owner	x\n"
            "2025-10-07	deduct	瓦工	减项	项	1	999	999	owner	x\n",
            5001.0, 5.001)
        code, out, _ = run_cli(cli_args("report", p))
        self.assertEqual(code, sc.EXIT_OK)
        self.assertIn("CREEP", out)
        self.assertNotIn("HEALTHY", out)

    def test_exactly_at_ambush_line(self):
        p = self.ledger(
            "date	type	category	item	unit	qty	price	amount	who	reason\n"
            "2025-10-05	add	瓦工	加项1	项	1	10000	10000	owner	x\n"
            "2025-10-06	add	瓦工	加项2	项	1	5000	5000	owner	x\n"
            "2025-10-07	add	瓦工	加项3	项	1	0.01	0.01	owner	x\n",
            15000.01, 15.00001)
        code, out, _ = run_cli(cli_args("report", p))
        self.assertEqual(code, sc.EXIT_GATE)
        self.assertIn("AMBUSH", out)

    def test_just_under_ambush_line(self):
        # 14999.99 on 100000 = 14.999999% -> CREEP, not AMBUSH
        p = self.ledger(
            "date	type	category	item	unit	qty	price	amount	who	reason\n"
            "2025-10-05	add	瓦工	加项1	项	1	10000	10000	owner	x\n"
            "2025-10-06	add	瓦工	加项2	项	1	4999	4999	owner	x\n"
            "2025-10-07	add	瓦工	加项3	项	1	0.99	0.99	owner	x\n",
            14999.99, 14.999999)
        code, out, _ = run_cli(cli_args("report", p))
        self.assertEqual(code, sc.EXIT_OK)
        self.assertIn("CREEP", out)
        self.assertNotIn("AMBUSH", out)

    def test_passive_exactly_at_line(self):
        # contractor 5000 / owner 5000 = 50% exactly -> no LOWBALL
        p = self.ledger(
            "date	type	category	item	unit	qty	price	amount	who	reason\n"
            "2025-10-05	add	瓦工	甲	项	1	5000	5000	contractor	x\n"
            "2025-10-06	add	瓦工	乙	项	1	5000	5000	owner	x\n"
            "2025-10-07	add	瓦工	丙	项	1	0.01	0.01	owner	x\n",
            10000.01, 10.000001)
        code, out, _ = run_cli(cli_args("report", p))
        self.assertEqual(code, sc.EXIT_OK)
        self.assertNotIn("LOWBALL LAMP", out)

    def test_passive_just_over_line(self):
        # 6100/12100 = 50.41% -> LOWBALL fires; 50.00% exactly would not
        p = self.ledger(
            "date	type	category	item	unit	qty	price	amount	who	reason\n"
            "2025-10-05	add	瓦工	甲	项	1	6100	6100	contractor	x\n"
            "2025-10-06	add	瓦工	乙	项	1	3000	3000	owner	x\n"
            "2025-10-07	add	瓦工	丙	项	1	3000	3000	owner	x\n",
            12100.0, 12.1)
        code, out, _ = run_cli(cli_args("report", p))
        self.assertEqual(code, sc.EXIT_GATE)
        self.assertIn("LOWBALL LAMP", out)

    def test_negative_net_is_healthy(self):
        p = self.ledger(
            "date	type	category	item	unit	qty	price	amount	who	reason\n"
            "2025-10-05	deduct	瓦工	砍价	项	1	2000	2000	owner	x\n"
            "2025-10-06	deduct	瓦工	砍价2	项	1	1000	1000	owner	x\n"
            "2025-10-07	deduct	瓦工	砍价3	项	1	500	500	owner	x\n",
            -3500.0, -3.5)
        code, out, _ = run_cli(cli_args("report", p))
        self.assertEqual(code, sc.EXIT_OK)
        self.assertIn("HEALTHY", out)

    def test_custom_lines(self):
        p = self.ledger(
            "date	type	category	item	unit	qty	price	amount	who	reason\n"
            "2025-10-05	add	瓦工	加项1	项	1	3000	3000	owner	x\n"
            "2025-10-06	add	瓦工	加项2	项	1	3000	3000	owner	x\n"
            "2025-10-07	deduct	瓦工	减项	项	1	1000	1000	owner	x\n",
            5000.0, 5.0)
        code, out, _ = run_cli(cli_args(
            "report", p, ["--creep-line", "3.0", "--ambush-line", "20.0"]))
        self.assertEqual(code, sc.EXIT_OK)
        self.assertIn("CREEP", out)


# -------------------------------------------------------------- census

class TestCensus(unittest.TestCase):
    BASE_Q = ("category	item	unit	qty	price	amount\n"
              "防水	卫生间防水	m²	12	200	2400\n"
              "垃圾清运	垃圾外运	车	2	600	1200\n"
              "水电	水电改造	m	100	80	8000\n"
              "瓦工	贴砖	m²	52	95	4940\n"
              "油漆	乳胶漆	m²	230	56	12880\n")

    def test_half_mode_no_mgmt_scan(self):
        m = "mode	half\n"
        p = write_ledger(self.BASE_Q, None, m)
        code, out, _ = run_cli(cli_args("census", p))
        self.assertEqual(code, sc.EXIT_OK)
        self.assertNotIn("AMBUSH PRE-LOADED", out)
        self.assertNotIn("管理费", out)

    def test_full_mode_flags_mgmt(self):
        m = "mode	full\n"
        p = write_ledger(self.BASE_Q, None, m)
        code, out, _ = run_cli(cli_args("census", p))
        self.assertEqual(code, sc.EXIT_GATE)
        self.assertIn("! 管理费", out)

    def test_mode_default_is_full_with_banner(self):
        p = write_ledger(self.BASE_Q, None, None)
        code, out, _ = run_cli(cli_args("census", p))
        self.assertEqual(code, sc.EXIT_GATE)
        self.assertIn("mode full assumed", out)

    def test_alias_normalization(self):
        q = self.BASE_Q.replace("防水	卫生间防水",
                                "waterproofing	卫生间防水") \
                       .replace("瓦工	贴砖", "泥工	贴砖")
        p = write_ledger(q, None, "mode	full\n")
        code, out, _ = run_cli(cli_args("census", p))
        self.assertEqual(code, sc.EXIT_GATE)
        # 防水 covered through its alias; 管理费 remains the only HIGH
        self.assertNotIn("! 防水", out)
        self.assertIn("! 管理费", out)

    def test_extend_adds_high(self):
        p = write_ledger(self.BASE_Q, None, "mode	half\n")
        code, out, _ = run_cli(cli_args(
            "census", p, ["--extend", "瓦工找平:HIGH"]))
        self.assertEqual(code, sc.EXIT_GATE)
        self.assertIn("瓦工找平", out)

    def test_extend_low_does_not_gate(self):
        p = write_ledger(self.BASE_Q, None, "mode	half\n")
        code, out, _ = run_cli(cli_args(
            "census", p, ["--extend", "阳台贴砖"]))
        self.assertEqual(code, sc.EXIT_OK)

    def test_thin_quote_still_scans(self):
        q = ("category	item	unit	qty	price	amount\n"
             "防水	x	m²	1	1	1\n")
        p = write_ledger(q, None, "mode	half\n")
        code, out, _ = run_cli(cli_args("census", p))
        self.assertEqual(code, sc.EXIT_GATE)
        self.assertIn("垃圾清运", out)


# --------------------------------------------------------------- court

class TestCourt(unittest.TestCase):
    Q = base_quote(10, 10000)  # 100000

    def verdict_of(self, changes, meta=None):
        # no start/plan here: the after-rate judges directly, the
        # projection tests live below
        m = meta or "mode	full\n"
        p = write_ledger(self.Q, changes, m)
        return run_cli(cli_args("court", p))

    HDR = ("date	type	category	item	unit	qty	price	amount	who	reason\n")

    def test_accept(self):
        # settled 1000 (1%), pending 2000 -> after 3% <= 5% ACCEPT
        c = self.HDR + change_line("2025-10-05", "add", "瓦工", "已签",
                                   1000, "owner")
        c += "	add	瓦工	口头加	项	1	2000	2000	contractor	顺手\n"
        code, out, _ = self.verdict_of(c)
        self.assertEqual(code, sc.EXIT_OK)
        self.assertIn("ACCEPT", out)
        self.assertNotIn("REDO", out)

    def test_negotiate(self):
        # settled 8000 (8%), pending 2000 -> after 10% -> NEGOTIATE
        c = self.HDR + change_line("2025-10-05", "add", "瓦工", "已签",
                                   8000, "owner")
        c += "	add	瓦工	口头加	项	1	2000	2000	contractor	顺手\n"
        code, out, _ = self.verdict_of(c)
        self.assertEqual(code, sc.EXIT_OK)
        self.assertIn("NEGOTIATE", out)
        self.assertNotIn("REDO", out)

    def test_redo(self):
        c = self.HDR + change_line("2025-10-05", "add", "瓦工", "已签",
                                   14000, "owner")
        c += "	add	瓦工	口头加	项	1	2000	2000	contractor	顺手\n"
        code, out, _ = self.verdict_of(c)
        self.assertEqual(code, sc.EXIT_GATE)
        self.assertIn("REDO", out)

    def test_pending_on_high_absent_trade(self):
        # after = 3400/100000 = 3.4% <= creep -> ACCEPT band, but the
        # evidence must name the HIGH absence
        c = self.HDR + change_line("2025-10-05", "add", "瓦工", "已签",
                                   1000, "owner")
        c += "	add	防水	现在才说要防水	项	1	2400	2400	contractor	必须做\n"
        code, out, _ = self.verdict_of(c)
        self.assertEqual(code, sc.EXIT_OK)
        self.assertIn("HIGH-absent", out)
        self.assertIn("ACCEPT", out)

    def test_pending_owner_banner(self):
        c = self.HDR + change_line("2025-10-05", "add", "瓦工", "已签",
                                   1000, "owner")
        c += "	add	瓷砖	自己要升级	项	1	2000	2000	owner	我要好的\n"
        code, out, _ = self.verdict_of(c)
        self.assertIn("(proposed by owner)", out)

    def test_no_pending(self):
        c = self.HDR + change_line("2025-10-05", "add", "瓦工", "已签",
                                   1000, "owner")
        c += change_line("2025-10-06", "add", "瓦工", "已签2", 1000, "owner")
        c += change_line("2025-10-07", "add", "瓦工", "已签3", 1000, "owner")
        code, out, _ = self.verdict_of(c)
        self.assertEqual(code, sc.EXIT_OK)
        self.assertIn("no pending change orders", out)

    def test_in_progress_projection_reappears(self):
        # as-of 2025-11-01: day 31 of 101; settled 8000 -> 8%,
        # projection 26.06% -> REDO even though after is only 10%
        c = self.HDR + change_line("2025-10-05", "add", "瓦工", "已签",
                                   8000, "owner")
        c += "	add	瓦工	口头加	项	1	2000	2000	contractor	顺手\n"
        m = "mode	full\nstart	2025-10-01\nplan	2026-01-10\n"
        p = write_ledger(self.Q, c, m)
        code, out, _ = run_cli(cli_args(
            "court", p, ["--as-of", "2025-11-01"]))
        self.assertEqual(code, sc.EXIT_GATE)
        self.assertIn("REDO", out)
        self.assertIn("projection", out)


# ------------------------------------------------------------- compare

class TestCompare(unittest.TestCase):
    A_Q = ("category	item	unit	qty	price	amount\n"
           "水电	水电	m	100	80	8000\n"
           "瓦工	贴砖	m²	52	95	4940\n"
           "防水	防水	m²	12	200	2400\n")

    B_Q = ("category	item	unit	qty	price	amount\n"
           "水电	水电	m	100	90	9000\n"
           "瓦工	贴砖	m²	52	95	4940\n"
           "防水	防水	m²	12	210	2520\n"
           "管理费	管理费	项	1	2000	2000\n")

    def test_headline_and_silence(self):
        p = write_ledger(self.A_Q, None, "mode	full\n")
        q2 = os.path.join(os.path.dirname(p[0]), "b.tsv")
        with open(q2, "w", encoding="utf-8") as fh:
            fh.write(self.B_Q)
        code, out, _ = run_cli(cli_args("compare", p, ["--quote2", q2]))
        # A: 15340, B: 18460 -> headline gap 3120;
        # common (水电/瓦工/防水) gap 16460-15340 = 1120; only-B 2000
        self.assertEqual(code, sc.EXIT_GATE)  # B itself lacks 垃圾清运 (HIGH)
        self.assertIn("3,120.00", out)
        self.assertIn("1,120.00", out)
        self.assertIn("2,000.00", out)
        self.assertIn("pre-signature lens", out)  # no settle yet

    def test_b_high_absence_gates(self):
        p = write_ledger(self.A_Q, None, "mode	full\n")
        q2 = os.path.join(os.path.dirname(p[0]), "b.tsv")
        with open(q2, "w", encoding="utf-8") as fh:
            fh.write("category	item	unit	qty	price	amount\n"
                     "水电	水电	m	100	90	9000\n")
        code, out, _ = run_cli(cli_args("compare", p, ["--quote2", q2]))
        self.assertEqual(code, sc.EXIT_GATE)
        self.assertIn("HIGH absence", out)

    def test_requires_quote2(self):
        p = write_ledger(self.A_Q, None, None)
        err = io.StringIO()
        with redirect_stderr(err):
            code = sc.main(["--quote", p[0], "--meta", p[2], "compare"])
        self.assertEqual(code, sc.EXIT_INPUT)

    def test_empty_common(self):
        p = write_ledger(self.A_Q, None, "mode	half\n")
        q2 = os.path.join(os.path.dirname(p[0]), "b.tsv")
        with open(q2, "w", encoding="utf-8") as fh:
            fh.write("category	item	unit	qty	price	amount\n"
                     "地板	地板	m²	62	180	11160\n")
        code, out, _ = run_cli(cli_args("compare", p, ["--quote2", q2]))
        # disjoint bids: nothing comparable, and B misses every base trade
        self.assertEqual(code, sc.EXIT_GATE)
        self.assertIn("common trades (0)", out)


# ------------------------------------------------- as-of and anchoring

class TestAnchoring(unittest.TestCase):
    def test_default_as_of_includes_settle(self):
        p = sample()
        st = load(p)
        self.assertEqual(st["as_of"], sc.parse_date("2026-01-18", "x"))
        self.assertTrue(st["final"])

    def test_default_as_of_without_settle(self):
        p = write_ledger(SAMPLE_Q, SAMPLE_C, "mode	full\n")
        st = load(p)
        self.assertEqual(st["as_of"], sc.parse_date("2026-01-05", "x"))
        self.assertFalse(st["final"])

    def test_truncation(self):
        st = load(sample(), as_of=sc.parse_date("2025-10-31", "x"))
        # only 10-12 and 10-20 orders
        self.assertAlmostEqual(st["net"], 3600.0, places=6)
        self.assertEqual(len(st["changes"]), 2)

    def test_future_rows_are_counted_not_silent(self):
        code, out, _ = run_cli(cli_args(
            "report", sample(), ["--as-of", "2025-12-01"]))
        self.assertIn("4 after as-of", out)

    def test_no_wall_clock_in_source(self):
        src = open(sc.__file__, encoding="utf-8").read()
        self.assertNotIn("date.today()", src)
        self.assertNotIn("datetime.now", src)
        self.assertNotIn("time.time", src)

    def test_report_prints_basename_only(self):
        p = sample()
        code, out, _ = run_cli(cli_args("report", p))
        self.assertNotIn(p[0], out)
        self.assertIn("quote.tsv", out)

    def test_static_without_dates(self):
        p = write_ledger(SAMPLE_Q, SAMPLE_C, None)
        # all rows have dates -> as-of falls to latest; give a pending-only
        # ledger instead
        c = ("date	type	category	item	unit	qty	price	amount	who	reason\n"
             "	add	瓦工	a	项	1	100	100	owner	x\n"
             "	add	瓦工	b	项	1	100	100	owner	x\n")
        p = write_ledger(SAMPLE_Q, c, None)
        code, out, _ = run_cli(cli_args("report", p))
        self.assertIn("STATIC", out)

    def test_overtime_does_not_amplify_projection(self):
        # elapsed 109 > total 101, no settle yet -> projection clamped to rate
        c = ("date	type	category	item	unit	qty	price	amount	who	reason\n"
             "2026-01-20	add	瓦工	拖期后加项	项	1	2000	2000	owner	x\n"
             "2026-01-21	add	瓦工	拖期后加项2	项	1	2000	2000	owner	x\n"
             "2026-01-22	add	瓦工	拖期后加项3	项	1	2000	2000	owner	x\n")
        m = "mode	full\nstart	2025-10-01\nplan	2026-01-10\n"
        p = write_ledger(base_quote(10, 10000), c, m)
        st = load(p, as_of=sc.parse_date("2026-01-22", "x"))
        self.assertAlmostEqual(st["projection"], st["rate"], places=9)


# --------------------------------------------------------- thin ledger

class TestThin(unittest.TestCase):
    def test_thin_report_declines_but_prints_math(self):
        q = ("category	item	unit	qty	price	amount\n"
             "瓦工	a	m²	1	10	10\n"
             "瓦工	b	m²	1	10	10\n"
             "瓦工	c	m²	1	10	10\n")
        c = ("date	type	category	item	unit	qty	price	amount	who	reason\n"
             "2025-10-05	add	瓦工	x	项	1	5	5	owner	x\n"
             "2025-10-06	add	瓦工	y	项	1	5	5	owner	x\n")
        p = write_ledger(q, c, None)
        code, out, _ = run_cli(cli_args("report", p))
        self.assertEqual(code, sc.EXIT_THIN)
        self.assertIn("THIN", out)
        self.assertIn("net change", out)  # arithmetic still printed
        self.assertNotIn("VERDICT", out)

    def test_zero_changes_thin(self):
        p = write_ledger(base_quote(10, 1000),
                         "date	type	category	item	unit	qty	price	amount	who	reason\n",
                         None)
        code, out, _ = run_cli(cli_args("report", p))
        self.assertEqual(code, sc.EXIT_THIN)
        self.assertIn("+¥0.00", out)


# -------------------------------------------------------- broken ledger

class TestBroken(unittest.TestCase):
    def bad(self, changes=None, quote=None, meta=None):
        p = write_ledger(quote or base_quote(10, 10000),
                         changes, meta if meta is not None else
                         "mode	full\n")
        return p

    HDR = ("date	type	category	item	unit	qty	price	amount	who	reason\n")

    def assert_broken(self, p, cmd="report"):
        err = io.StringIO()
        with redirect_stderr(err):
            code = sc.main(cli_args(cmd, p))
        self.assertEqual(code, sc.EXIT_INPUT, err.getvalue())
        return err.getvalue()

    def test_negative_add(self):
        p = self.bad(self.HDR + change_line("2025-10-05", "add", "瓦工",
                                            "x", -5, "owner"))
        self.assert_broken(p)

    def test_negative_deduct(self):
        p = self.bad(self.HDR + change_line("2025-10-05", "deduct", "瓦工",
                                            "x", -5, "owner"))
        self.assert_broken(p)

    def test_bad_type(self):
        p = self.bad(self.HDR + change_line("2025-10-05", "magic", "瓦工",
                                            "x", 5, "owner"))
        self.assert_broken(p)

    def test_bad_who(self):
        p = self.bad(self.HDR + change_line("2025-10-05", "add", "瓦工",
                                            "x", 5, " foreman"))
        self.assert_broken(p)

    def test_bad_date(self):
        p = self.bad(self.HDR + change_line("2025/10/05", "add", "瓦工",
                                            "x", 5, "owner"))
        self.assert_broken(p)

    def test_deduct_unquoted_trade(self):
        p = self.bad(self.HDR + change_line("2025-10-05", "deduct", "木工",
                                            "x", 5, "owner"))
        code, out, _ = run_cli(cli_args("validate", p))
        self.assertEqual(code, sc.EXIT_INPUT)
        self.assertIn("unquoted", out)

    def test_reaudit_unquoted_trade(self):
        p = self.bad(self.HDR + change_line("2025-10-05", "reaudit", "防水",
                                            "x", 5, "contractor"))
        code, out, _ = run_cli(cli_args("validate", p))
        self.assertEqual(code, sc.EXIT_INPUT)

    def test_change_after_settle(self):
        c = self.HDR + change_line("2026-02-01", "add", "瓦工", "x", 5,
                                   "owner")
        c += change_line("2025-10-05", "add", "瓦工", "y", 5, "owner")
        c += change_line("2025-10-06", "add", "瓦工", "z", 5, "owner")
        p = self.bad(c, meta="mode	full\nsettle	2026-01-18\n")
        self.assert_broken(p)

    def test_change_before_start(self):
        c = self.HDR + change_line("2025-09-01", "add", "瓦工", "x", 5,
                                   "owner")
        c += change_line("2025-09-02", "add", "瓦工", "y", 5, "owner")
        c += change_line("2025-09-03", "add", "瓦工", "z", 5, "owner")
        p = self.bad(c, meta="mode	full\nstart	2025-10-01\n")
        code, out, _ = run_cli(cli_args("validate", p))
        self.assertEqual(code, sc.EXIT_INPUT)
        self.assertIn("early", out)

    def test_meta_bad_mode(self):
        p = self.bad(self.HDR + change_line("2025-10-05", "add", "瓦工",
                                            "x", 5, "owner"),
                     meta="mode	penthouse\n")
        self.assert_broken(p)

    def test_meta_unknown_key(self):
        p = self.bad(meta="mood	full\n")
        self.assert_broken(p)

    def test_meta_plan_before_start(self):
        p = self.bad(meta="mode	full\nstart	2025-10-01\nplan	2025-09-01\n")
        self.assert_broken(p)

    def test_settlement_identity_broken(self):
        c = self.HDR + change_line("2025-10-05", "add", "瓦工", "x", 100,
                                   "owner")
        c += change_line("2025-10-06", "add", "瓦工", "y", 100, "owner")
        c += change_line("2025-10-07", "add", "瓦工", "z", 100, "owner")
        m = "mode	full\nsettle	2025-10-31\nsettle_amount	99999\n"
        p = write_ledger(base_quote(10, 10000), c, m)
        code, out, _ = run_cli(cli_args("validate", p))
        self.assertEqual(code, sc.EXIT_INPUT)
        self.assertIn("settlement identity", out)

    def test_settlement_identity_tolerance(self):
        # 1 yuan of hand-copy rounding is absorbed
        c = self.HDR + change_line("2025-10-05", "add", "瓦工", "x", 100,
                                   "owner")
        c += change_line("2025-10-06", "add", "瓦工", "y", 100, "owner")
        c += change_line("2025-10-07", "add", "瓦工", "z", 100, "owner")
        m = "mode	full\nsettle	2025-10-31\nsettle_amount	100300.99\n"
        p = write_ledger(base_quote(10, 10000), c, m)
        code, out, _ = run_cli(cli_args("validate", p))
        self.assertEqual(code, sc.EXIT_OK)

    def test_line_arithmetic_off(self):
        q = ("category	item	unit	qty	price	amount\n"
             "瓦工	x	m²	3	100	999\n")  # 3*100 != 999 (>0.01)
        for _ in range(9):
            q += "瓦工	f%d	m²	1	1000	1000\n" % _
        p = write_ledger(q, None, None)
        code, out, _ = run_cli(cli_args("validate", p))
        self.assertEqual(code, sc.EXIT_INPUT)
        self.assertIn("qty×price", out)

    def test_nonpositive_quote_amount(self):
        q = ("category	item	unit	qty	price	amount\n"
             "瓦工	x	m²	1	0	0\n")
        p = write_ledger(q, None, None)
        self.assert_broken(p)

    def test_missing_file(self):
        p = write_ledger(base_quote(10, 1000), self.HDR, None)
        os.unlink(p[0])  # the quote is the one mandatory sheet
        self.assert_broken(p)

    def test_missing_changes_is_legal(self):
        # before signature there is no change-order sheet yet
        p = write_ledger(base_quote(10, 1000), None, None)
        self.assertFalse(os.path.exists(p[1]))
        code, out, _ = run_cli(cli_args("census", p))
        self.assertEqual(code, sc.EXIT_GATE)  # 清运 HIGH absent
        self.assertNotIn("ledger error", out)

    def test_missing_column(self):
        q = "category	item	unit	qty	price\n瓦工	x	m²	1	10\n"
        p = write_ledger(q, None, None)
        self.assert_broken(p)


# ------------------------------------------------------------- parsing

class TestParsing(unittest.TestCase):
    def test_thousands_separator(self):
        self.assertEqual(sc.parse_amount("1,200", "t"), 1200.0)

    def test_signed_amount(self):
        self.assertEqual(sc.parse_amount("-1316", "t"), -1316.0)

    def test_negative_reaudit_allowed(self):
        # an over-charge can come back: reaudit refunds 500
        c = ("date	type	category	item	unit	qty	price	amount	who	reason\n"
             "2025-10-05	reaudit	瓦工	多算退还	项	1	-500	-500	contractor	复核退钱\n"
             "2025-10-06	add	瓦工	a	项	1	100	100	owner	x\n"
             "2025-10-07	add	瓦工	b	项	1	100	100	owner	x\n")
        p = write_ledger(base_quote(10, 10000), c, None)
        st = load(p)
        self.assertAlmostEqual(st["net"], -300.0, places=6)
        code, out, _ = run_cli(cli_args("validate", p))
        self.assertEqual(code, sc.EXIT_OK)

    def test_canon_type_self_mapping(self):
        for t in ("add", "deduct", "upgrade", "reaudit"):
            self.assertEqual(sc.canon_type(t), t)

    def test_canon_who_self_mapping(self):
        for w in ("owner", "contractor"):
            self.assertEqual(sc.canon_who(w), w)

    def test_aliases(self):
        self.assertEqual(sc.canon_type("增项"), "add")
        self.assertEqual(sc.canon_type("按实结算"), "reaudit")
        self.assertEqual(sc.canon_who("工长"), "contractor")
        self.assertEqual(sc.canon_trade("waterproofing")[0], "防水")
        self.assertEqual(sc.canon_trade("泥工")[0], "瓦工")
        self.assertEqual(sc.canon_trade("拆改")[0], "拆改")

    def test_display_width(self):
        self.assertEqual(sc.dw("防水"), 4)
        self.assertEqual(sc.dw("abc"), 3)
        s = sc.pad("防水", 10)
        self.assertEqual(sc.dw(s), 10)

    def test_dual_algorithm_days(self):
        # the same invariant validate runs, re-checked here independently
        import random
        from datetime import date, timedelta
        rng = random.Random(20261001)
        for _ in range(50):
            d1 = date(2025, 1, 1) + timedelta(days=rng.randrange(0, 700))
            d2 = date(2025, 1, 1) + timedelta(days=rng.randrange(0, 700))
            self.assertEqual((d2 - d1).days,
                             d2.toordinal() - d1.toordinal())


class TestPriorTable(unittest.TestCase):
    def test_full_includes_mains_and_mgmt(self):
        t = sc.prior_table("full", [])
        self.assertEqual(t["管理费"], "HIGH")
        self.assertEqual(t["监理"], "LOW")
        self.assertEqual(t["防水"], "HIGH")
        self.assertEqual(t["瓷砖"], "LOW")

    def test_half_and_clean_share_base(self):
        for mode in ("half", "clean"):
            t = sc.prior_table(mode, [])
            self.assertNotIn("管理费", t)
            self.assertNotIn("瓷砖", t)
            self.assertEqual(t["防水"], "HIGH")

    def test_extend_overrides_severity(self):
        t = sc.prior_table("half", ["瓦工:HIGH"])
        self.assertEqual(t["瓦工"], "HIGH")

    def test_rates_nail_the_constants(self):
        self.assertEqual(sc.CREEP_LINE, 5.0)
        self.assertEqual(sc.AMBUSH_LINE, 15.0)
        self.assertEqual(sc.LOWBALL_LINE, 50.0)


if __name__ == "__main__":
    unittest.main()
