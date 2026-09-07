# -*- coding: utf-8 -*-
"""shot-chain · 针链 验收测试.

验收标准(README 承诺的全部转成自动化测试):
  解析层    中英别名归一(猫三联/四联/狂犬疫苗/跳蚤)/物种中文短名/
            缺右列视为空/行尾制表符容忍/注释行/前向引用/未知行型/
            未知链=不发明没教过的链/未知物种/缺名字/缺物种/重复登记/
            缺日期/日期不补零/假日期(02-30)/指向未登记宠/物种链矛盾/
            列数>5 拒/缺表头拒/空账 exit 3/缺文件 exit 2/薄账分层
  链引擎    MISSING 盲区/恰到期日 DUE/宽容末日 DUE(left=0)/次日 BROKEN/
            预警窗恰线即亮/窗外 OK/月月钟预警收敛(min(warn,cycle//3))/
            狂犬宽容为零到期即断/--cycle/--grace/--warn 翻案/
            多针链只认末针/乱序日期重排/hw 只适用狗
  report    样例灯统计/带灯 exit 4/全绿 exit 0/时间机器剪切+披露/
            NOT-YET 不抬闸(剪后零≠盲区)/缺省锚定账本末日+披露/basename
  next      只列亮灯链/排序:断线日→截止日→盲区殿后/全绿 exit 0
  brief     核对栏在场/链状态行/exit 语义
  validate  恒等式一 Σshot≡聚合/恒等式二 非空+盲区≡链空间/
            双路径重放全绿/账坏 exit 2/行号回溯在场
  旗标      --cycle 坏形/未知链/非正数;--grace 负数;--warn 负数
  确定性    同账同 as-of 两跑逐字节一致
"""

import contextlib
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EX_SHOTS = os.path.join(ROOT, "examples", "shots.tsv")
EX_NIANGAO = os.path.join(ROOT, "examples", "niangao.tsv")
sys.path.insert(0, ROOT)
import shot_chain  # noqa: E402


def run(argv):
    buf = io.StringIO()
    err = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
        code = shot_chain.main(argv)
    return code, buf.getvalue(), err.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tsv(self, name, content):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    # 小满春节寄养账本(与 examples/shots.tsv 同构,缩样:两宠)
    LEDGER = """type\tpet\titem\tdate\tnote
pet\t阿福\tdog\t\t柯基,2 岁
pet\t煤球\tcat\t\t狸花,免疫史不明
shot\t阿福\trabies\t2025-02-20\t狂犬证 2026-02-20 到期
shot\t阿福\tflea\t2025-12-28\t大宠爱
shot\t阿福\thw\t2025-12-10\t犬心保
shot\t煤球\trabies\t2024-06-15\t领养当年
shot\t煤球\tworm\t2025-09-30\t海乐妙
"""
    AS_OF = "2026-02-10"

    def led(self, content=None, name="l.tsv"):
        return self.tsv(name, self.LEDGER if content is None else content)


class TestParse(Base):
    def test_alias_norm_cn_en(self):
        cases = {
            "猫三联": "fvrcp", "三联": "fvrcp", "fvrcp": "fvrcp",
            "四联": "core-dog", "八联": "core-dog", "dhpp": "core-dog",
            "狂犬疫苗": "rabies", "rabies": "rabies",
            "跳蚤": "flea", "体外驱虫": "flea",
            "打虫": "worm", "heartworm": "hw", "心丝虫预防": "hw",
        }
        for raw, want in cases.items():
            self.assertEqual(shot_chain.norm_item(raw), want, raw)

    def test_alias_norm_whitespace(self):
        # 「猫 三联」式抄录差异不分裂账本
        self.assertEqual(shot_chain.norm_item("猫 三联"), "fvrcp")

    def test_alias_unknown_chain_refused(self):
        with self.assertRaises(ValueError):
            shot_chain.norm_item("九联")

    def test_species_cn(self):
        self.assertEqual(shot_chain.norm_species("猫"), "cat")
        self.assertEqual(shot_chain.norm_species("狗狗"), "dog")

    def test_forward_reference(self):
        # 先记针、后登记宠——两遍扫描,不拘书写顺序
        p = self.led("type\tpet\titem\tdate\tnote\n"
                     "shot\t煤球\trabies\t2024-06-15\t\n"
                     "pet\t煤球\tcat\t\t\n")
        code, out, _ = run(["validate", p])
        self.assertEqual(code, 0)

    def test_missing_right_cols_tolerated(self):
        p = self.led("type\tpet\titem\tdate\tnote\n"
                     "pet\t豆豆\tcat\n"          # 3 列,右缺视为空
                     "shot\t豆豆\trabies\t2025-01-01\n")
        code, _, _ = run(["validate", p])
        self.assertEqual(code, 0)

    def test_trailing_tab_tolerated(self):
        p = self.led("type\tpet\titem\tdate\tnote\n"
                     "pet\t豆豆\tcat\t\t\n"
                     "shot\t豆豆\trabies\t2025-01-01\t\n")
        code, _, _ = run(["validate", p])
        self.assertEqual(code, 0)

    def test_comment_lines_skipped(self):
        p = self.led("# 春节寄养前盘点\n" + self.LEDGER)
        code, _, _ = run(["validate", p])
        self.assertEqual(code, 0)

    def test_six_cols_refused(self):
        p = self.led(self.LEDGER + "shot\t阿福\trabies\t2025-01-01\tx\textra\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("6 > 5", err)

    def test_no_header_refused(self):
        p = self.led("pet\t阿福\tdog\t\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("表头", err)

    def test_unknown_rowtype_refused(self):
        p = self.led(self.LEDGER + "vax\t阿福\trabies\t2025-01-01\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("未知行型", err)

    def test_unknown_item_refused(self):
        p = self.led(self.LEDGER + "shot\t阿福\t猫艾滋\t2025-01-01\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("不发明没教过的链", err)

    def test_unknown_species_refused(self):
        p = self.led("type\tpet\titem\tdate\tnote\npet\t龟龟\tturtle\t\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("未知物种", err)

    def test_pet_no_name_refused(self):
        p = self.led("type\tpet\titem\tdate\tnote\npet\t\tdog\t\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)

    def test_pet_no_species_refused(self):
        p = self.led("type\tpet\titem\tdate\tnote\npet\t阿福\t\t\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("缺物种", err)

    def test_dup_pet_refused(self):
        p = self.led(self.LEDGER + "pet\t阿福\tdog\t\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("重复登记", err)

    def test_shot_no_date_refused(self):
        p = self.led(self.LEDGER + "shot\t阿福\trabies\t\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("缺接种日期", err)

    def test_date_not_zeropadded_refused(self):
        p = self.led(self.LEDGER + "shot\t阿福\trabies\t2025-2-1\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("补零", err)

    def test_fake_date_refused(self):
        p = self.led(self.LEDGER + "shot\t阿福\trabies\t2026-02-30\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("真实存在", err)

    def test_shot_unknown_pet_refused(self):
        p = self.led("type\tpet\titem\tdate\tnote\n"
                     "shot\t没人认领\t rabies \t2025-01-01\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("未登记", err)

    def test_species_chain_mismatch_refused(self):
        p = self.led(self.LEDGER + "shot\t煤球\tcore-dog\t2025-01-01\t\n")
        code, _, err = run(["validate", p])
        self.assertEqual(code, 2)
        self.assertIn("物种与链矛盾", err)

    def test_empty_ledger_exit3(self):
        p = self.led("type\tpet\titem\tdate\tnote\n")
        code, _, err = run(["report", p, "--as-of", self.AS_OF])
        self.assertEqual(code, 3)
        self.assertIn("空账", err)

    def test_missing_file_exit2(self):
        code, _, err = run(["report", os.path.join(self.tmp, "nope.tsv")])
        self.assertEqual(code, 2)

    def test_thin_ledger_layered(self):
        # 只有登记没有针:钉 as-of → 全盲区对账单 exit 4;不钉 → 拒判 exit 3
        p = self.led("type\tpet\titem\tdate\tnote\npet\t豆豆\tcat\t\t\n")
        code, out, _ = run(["report", p, "--as-of", "2026-01-01"])
        self.assertEqual(code, 4)
        self.assertEqual(out.count("MISSING"), 4)  # cat 四条链全盲区
        code, _, err = run(["report", p])
        self.assertEqual(code, 3)
        self.assertIn("薄账", err)

    def test_item_cannot_shadow_species(self):
        # shot 行的 item 列误写物种:归一失败,拒绝猜测
        p = self.led(self.LEDGER + "shot\t阿福\tdog\t2025-01-01\t\n")
        code, _, _ = run(["validate", p])
        self.assertEqual(code, 2)


class TestEngine(Base):
    def engine(self, content, as_of, extra=None):
        p = self.led(content)
        argv = ["report", p, "--as-of", as_of] + (extra or [])
        code, out, err = run(argv)
        return code, out, err

    def test_missing_blindspot(self):
        code, out, _ = self.engine(
            "type\tpet\titem\tdate\tnote\npet\t豆豆\tcat\t\t\n", "2026-01-01")
        self.assertEqual(code, 4)
        self.assertIn("MISSING", out)

    def test_due_exactly_on_due_date(self):
        # 恰线即亮:as-of == 到期日 → DUE,不是 OK
        c = self.LEDGER + "shot\t煤球\tfvrcp\t2025-01-20\t\n"
        code, out, _ = self.engine(c, "2028-01-20")  # 1095 天后恰到期
        self.assertIn("DUE", out.split("煤球")[1].split("狂犬")[0])
        self.assertIn("已逾期 0 天", out)

    def test_due_last_grace_day(self):
        c = self.LEDGER + "shot\t煤球\tfvrcp\t2025-01-20\t\n"
        code, out, _ = self.engine(c, "2028-03-20")  # 宽容最后一天(2028 闰年)
        self.assertIn("宽容至 2028-03-20", out)
        self.assertIn("宽容还剩 0 天", out)

    def test_broken_next_day(self):
        c = self.LEDGER + "shot\t煤球\tfvrcp\t2025-01-20\t\n"
        code, out, _ = self.engine(c, "2028-03-22")  # 宽容次日,链断
        self.assertIn("BROKEN", out)
        self.assertIn("重新起链", out)

    def test_ok_outside_warn_window(self):
        c = self.LEDGER + "shot\t煤球\tfvrcp\t2025-01-20\t\n"
        code, out, _ = self.engine(c, "2027-11-01")  # 距 2028-01-20 还有 80 天
        seg = out.split("煤球")[1].split("狂犬")[0]
        self.assertIn("OK", seg)

    def test_warn_window_exactly_lights(self):
        # fvrcp warn_eff = min(30, 1095//3=365) = 30;恰第 30 天亮
        c = self.LEDGER + "shot\t煤球\tfvrcp\t2025-01-20\t\n"
        code, out, _ = self.engine(c, "2027-12-21")  # 到期 2028-01-20 前 30 天
        seg = out.split("煤球")[1].split("狂犬")[0]
        self.assertIn("DUE", seg)
        code, out, _ = self.engine(c, "2027-12-20")  # 前 31 天不亮
        seg = out.split("煤球")[1].split("狂犬")[0]
        self.assertIn("OK", seg)

    def test_monthly_clock_warn_converges(self):
        # flea cycle 30 → warn_eff = min(30, 10) = 10:月月钟不永远黄着
        c = self.LEDGER + "shot\t煤球\tflea\t2025-12-05\t\n"
        code, out, _ = self.engine(c, "2025-12-10")  # 到期 01-04,余 25 天 > 10
        flea_line = [l for l in out.split("\n") if l.strip().startswith("体外驱虫")]
        self.assertEqual(len(flea_line), 2)  # 阿福(第一针在 as-of 后,未起链)+ 煤球
        self.assertIn("未起链", flea_line[0])
        self.assertIn("OK", flea_line[1])    # 煤球:余 25 天 > warn_eff 10,不亮

    def test_rabies_zero_grace_breaks_on_expiry(self):
        c = self.LEDGER + "shot\t煤球\trabies\t2025-01-20\t\n"
        code, out, _ = self.engine(c, "2026-01-20")  # 到期当天仍 DUE
        rabies_line = [l for l in out.split("\n") if l.strip().startswith("狂犬")]
        self.assertEqual(len(rabies_line), 2)  # 两宠各一条
        self.assertIn("DUE", rabies_line[1])   # 煤球(第二行)恰线亮
        code, out, _ = self.engine(c, "2026-01-21")  # 次日即断,宽容为零
        rabies_line = [l for l in out.split("\n") if l.strip().startswith("狂犬")]
        self.assertIn("BROKEN", rabies_line[1])

    def test_cycle_flag_overrides(self):
        c = self.LEDGER + "shot\t煤球\trabies\t2025-01-20\t\n"
        # 海外三年:2028-01-20 到期,2026-02-10 看 OK
        code, out, _ = self.engine(c, "2026-02-10", ["--cycle", "rabies:1095"])
        seg = out.split("煤球")[1].split("体外")[0]
        self.assertIn("OK", seg)
        self.assertIn("2028-01-20", seg)  # 2025-01-20 + 1095 天(跨 2028 无闰日?)

    def test_grace_flag_overrides(self):
        c = self.LEDGER + "shot\t煤球\trabies\t2025-01-20\t\n"
        # 给狂犬开 30 天宽容:2026-01-21 看 DUE(原为 BROKEN)
        code, out, _ = self.engine(c, "2026-01-21", ["--grace", "rabies:30"])
        seg = out.split("煤球")[1].split("体外")[0]
        self.assertIn("DUE", seg)

    def test_warn_flag_overrides(self):
        c = self.LEDGER + "shot\t煤球\tfvrcp\t2025-01-20\t\n"
        # --warn 0:关掉预警窗,恰预警线当天不再亮
        code, out, _ = self.engine(c, "2027-12-21", ["--warn", "0"])
        seg = out.split("煤球")[1].split("狂犬")[0]
        self.assertIn("OK", seg)

    def test_multi_shot_chain_uses_last(self):
        # 年糕 fvrcp 三针系列:链只认末针(2024-10-01,+1095 = 2027-10-01)
        c = (self.LEDGER
             + "shot\t煤球\tfvrcp\t2024-08-01\t\n"
             + "shot\t煤球\tfvrcp\t2024-09-01\t\n"
             + "shot\t煤球\tfvrcp\t2024-10-01\t\n")
        code, out, _ = self.engine(c, "2026-02-10")
        seg = out.split("煤球")[1].split("狂犬")[0]
        self.assertIn("2027-10-01", seg)
        self.assertIn("(L11)", seg)  # 末针行号(LEDGER 8 行后第三针在 L11),不是首针

    def test_unordered_dates_sorted(self):
        # 账本乱序记录,链自动重排,末针取最大日期
        c = (self.LEDGER
             + "shot\t煤球\tfvrcp\t2024-10-01\t\n"
             + "shot\t煤球\tfvrcp\t2024-08-01\t\n")
        code, out, _ = self.engine(c, "2026-02-10")
        seg = out.split("煤球")[1].split("狂犬")[0]
        self.assertIn("2027-10-01", seg)

    def test_hw_dog_only_chain_space(self):
        # 猫的链空间不含 hw:cat 四链,dog 五链
        self.assertEqual(shot_chain.chains_for("cat"),
                         ["fvrcp", "rabies", "flea", "worm"])
        self.assertEqual(len(shot_chain.chains_for("dog")), 5)


class TestReport(Base):
    def test_sample_light_census(self):
        code, out, _ = run(["report", EX_SHOTS,
                            "--as-of", self.AS_OF])
        self.assertEqual(code, 4)
        self.assertIn("🔴5(断3/盲2) 🟡3 🟢5", out)
        self.assertIn("3 宠 13 针 · 13 链", out)

    def test_sample_broken_rabies_exposure_line(self):
        code, out, _ = run(["report", EX_SHOTS,
                            "--as-of", self.AS_OF])
        self.assertIn("人要打疫苗、它要隔离观察", out)

    def test_all_green_exit0(self):
        code, out, _ = run(["report", EX_NIANGAO,
                            "--as-of", self.AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("🟢", out)
        self.assertNotIn("exit 4", out)

    def test_time_machine_clips_and_discloses(self):
        code, out, _ = run(["report", EX_SHOTS,
                            "--as-of", "2025-12-20"])
        self.assertEqual(code, 4)
        self.assertIn("剪掉晚于 as-of 的 3 针后视行", out)
        self.assertIn("未起链", out)  # 阿福 flea 第一针在 as-of 之后

    def test_notyet_does_not_gate(self):
        # NOT-YET(剪后零)不抬闸:单宠一针被剪 → 剩 MISSING 抬闸,
        # 再造一只全时间零针宠对照:MISSING 在,NOT-YET 不在灯数里
        content = ("type\tpet\titem\tdate\tnote\n"
                   "pet\t豆豆\tcat\t\t\n"
                   "shot\t豆豆\tflea\t2026-06-01\t未来第一针\n")
        code, out, _ = run(["report", self.led(content), "--as-of", "2026-01-01"])
        self.assertEqual(code, 4)
        self.assertIn("未起链", out)
        # 灯数只算 MISSING 3 条(fvrcp/rabies/worm),NOT-YET 不计入
        self.assertIn("🔴3(断0/盲3) 🟡0 🟢0 ⚪1(时间机器下的未起链)", out)

    def test_default_anchors_ledger_end(self):
        code, out, _ = run(["report", EX_NIANGAO])
        self.assertEqual(code, 0)
        self.assertIn("未钉 as-of,缺省锚定账本末日", out)
        self.assertIn("as-of 2026-02-05", out)  # 账本最大日期

    def test_basename_only(self):
        code, out, _ = run(["report", EX_SHOTS,
                            "--as-of", self.AS_OF])
        self.assertNotIn(EX_SHOTS, out)  # 只打 basename
        self.assertNotIn(os.getcwd(), out)


class TestNext(Base):
    def test_lists_only_lit_sorted(self):
        code, out, _ = run(["next", EX_SHOTS, "--as-of", self.AS_OF])
        self.assertEqual(code, 4)
        # 排序:煤球狂犬(断线最早)第一;年糕全绿不出现
        self.assertLess(out.index("煤球·狂犬"), out.index("阿福·狂犬"))
        self.assertNotIn("年糕", out)
        self.assertIn("8 链要动手", out)

    def test_all_green_next(self):
        code, out, _ = run(["next", EX_NIANGAO, "--as-of", self.AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("全绿", out)


class TestBrief(Base):
    def test_checklist_and_states(self):
        code, out, _ = run(["brief", EX_SHOTS, "--as-of", self.AS_OF])
        self.assertEqual(code, 4)
        self.assertIn("寄养/托运机构核对栏", out)
        self.assertIn("□ 狂犬证在有效期", out)
        self.assertIn("链断于", out)
        self.assertIn("零记录 · 免疫史不明", out)

    def test_all_green_brief_exit0(self):
        code, out, _ = run(["brief", EX_NIANGAO, "--as-of", self.AS_OF])
        self.assertEqual(code, 0)
        self.assertIn("亮灯 0 条", out)


class TestValidate(Base):
    def test_sample_validate_green(self):
        code, out, _ = run(["validate", EX_SHOTS])
        self.assertEqual(code, 0)
        self.assertIn("恒等式全绿", out)
        self.assertIn("Σshot 行 ≡ Σ各宠各链针数 = 13", out)
        self.assertIn("非空链 11 + 盲区 2 ≡ 链空间 13", out)

    def test_line_numbers_backtrackable(self):
        # 行号可 grep 回账本:report 链行带 (L行号),validate 复述
        with open(EX_SHOTS, encoding="utf-8") as f:
            lines = f.read().split("\n")
        code, out, _ = run(["report", EX_SHOTS,
                            "--as-of", self.AS_OF])
        self.assertIn("(L6)", out)
        self.assertIn("rabies", lines[5])  # L6 就是阿福狂犬行(1-based)

    def test_validate_broken_ledger_exit2(self):
        p = self.led(self.LEDGER + "shot\t阿福\trabies\t2026-02-30\t\n")
        code, _, _ = run(["validate", p])
        self.assertEqual(code, 2)


class TestFlags(Base):
    def test_cycle_bad_shape(self):
        code, _, err = run(["report", EX_NIANGAO,
                            "--cycle", "rabies"])
        self.assertEqual(code, 2)
        self.assertIn("链:天数", err)

    def test_cycle_unknown_chain(self):
        code, _, err = run(["report", EX_NIANGAO,
                            "--cycle", "九联:365"])
        self.assertEqual(code, 2)
        self.assertIn("未知链", err)

    def test_cycle_nonpositive(self):
        code, _, err = run(["report", EX_NIANGAO,
                            "--cycle", "rabies:0"])
        self.assertEqual(code, 2)
        self.assertIn("正天数", err)

    def test_grace_negative(self):
        code, _, err = run(["report", EX_NIANGAO,
                            "--grace", "rabies:-1"])
        self.assertEqual(code, 2)

    def test_warn_negative(self):
        code, _, err = run(["report", EX_NIANGAO, "--warn", "-3"])
        self.assertEqual(code, 2)


class TestDeterminism(Base):
    def test_byte_identical_two_runs(self):
        a = run(["report", EX_SHOTS, "--as-of", self.AS_OF])
        b = run(["report", EX_SHOTS, "--as-of", self.AS_OF])
        self.assertEqual(a, b)

    def test_replay_matches_parse_layer(self):
        # 双路径重放在健康账本上逐字段全等(引擎内部一致性)
        led = shot_chain.parse_tsv(EX_SHOTS)
        replay = shot_chain.replay_from_text(EX_SHOTS)
        by_a = {}
        for s in led.shots:
            by_a.setdefault((s["pet"], s["item"]), []).append((s["date"], s["line"]))
        for k, lst in by_a.items():
            self.assertEqual(sorted(lst), sorted(replay[k]), k)


if __name__ == "__main__":
    unittest.main()
