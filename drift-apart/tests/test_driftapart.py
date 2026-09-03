#!/usr/bin/env python3
"""Acceptance tests for 渐行渐远 · Drift Apart."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import drift_apart as da  # noqa: E402

AS_OF = date(2025, 12, 1)


class LedgerFixture(unittest.TestCase):
    """Each test builds its own two-ledger CSV pair in a temp dir."""

    def write(self, roster, interactions):
        tmp = tempfile.mkdtemp()
        rp = os.path.join(tmp, "roster.csv")
        ip = os.path.join(tmp, "interactions.csv")
        with open(rp, "w", encoding="utf-8") as fh:
            fh.write(roster)
        with open(ip, "w", encoding="utf-8") as fh:
            fh.write(interactions)
        return rp, ip

    def run_cli(self, command, roster, interactions, *extra, capture=None):
        rp, ip = self.write(roster, interactions)
        argv = [command, rp, ip] + list(extra)
        code = da.main([str(a) for a in argv])
        return code


def contacts(name, start, gaps, initiators=None):
    """Interactions CSV rows: start date + n gaps → n+1 contacts."""
    rows = []
    day = start
    who_list = (list(initiators) + ["me"] * (len(gaps) + 1))[:len(gaps) + 1] if initiators else ["me"] * (len(gaps) + 1)
    for i, gap in enumerate(list(gaps) + [None]):
        rows.append("%s,%s,%s" % (name, day.isoformat(), who_list[i]))
        if gap is not None:
            day = day + timedelta(days=gap)
    return rows


def build_relations(roster, interactions, as_of=AS_OF, overrides=None):
    """Direct-model helper: parse fixture strings, return relations."""
    tmp = tempfile.mkdtemp()
    rp = os.path.join(tmp, "r.csv")
    ip = os.path.join(tmp, "i.csv")
    with open(rp, "w", encoding="utf-8") as fh:
        fh.write(roster)
    with open(ip, "w", encoding="utf-8") as fh:
        fh.write(interactions)
    report = da.load_ledger(rp, ip, as_of, overrides or {})
    return {r["name"]: r for r in report["relations"]}, report


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------

class ParserTests(LedgerFixture):
    ROSTER = "name,circle,birthday\n阿岚,close,03-08\n"

    def test_chinese_headers_and_aliases(self):
        rp, ip = self.write("姓名,圈层,生日\n阿岚,亲密,03-08\n",
                            "姓名,日期,发起者\n阿岚,2025-09-01,对方\n")
        report = da.load_ledger(rp, ip, AS_OF, {})
        self.assertEqual(report["tracked"], 1)
        rel = report["relations"][0]
        self.assertEqual(rel["circle"], "close")
        self.assertEqual(rel["last_contact"], date(2025, 9, 1))
        self.assertEqual(rel["events"][0]["initiator"], "them")

    def test_bom_and_blank_lines(self):
        rp, ip = self.write("\ufeffname,circle\n阿岚,close\n\n",
                            "\ufeffname,date,initiator\n\n阿岚,2025-09-01,me\n")
        report = da.load_ledger(rp, ip, AS_OF, {})
        self.assertEqual(report["tracked"], 1)

    def test_date_formats(self):
        rp, _ = self.write(self.ROSTER, "name,date,initiator\n")
        tmp = os.path.dirname(rp)
        ip = os.path.join(tmp, "i.csv")
        rows = ["name,date,initiator"]
        for fmt in ("2025-09-01", "2025/09/02", "2025.09.03", "2025年09月04日"):
            rows.append("阿岚,%s,me" % fmt)
        with open(ip, "w", encoding="utf-8") as fh:
            fh.write("\n".join(rows) + "\n")
        report = da.load_ledger(rp, ip, AS_OF, {})
        self.assertEqual(report["relations"][0]["contacts"], 4)
        self.assertEqual(report["relations"][0]["last_contact"],
                         date(2025, 9, 4))

    def test_roster_missing_circle_reports_line(self):
        rp, ip = self.write("name,circle\n阿岚,\n", "name,date,initiator\n")
        with self.assertRaises(da.ParseError) as ctx:
            da.read_roster(rp)
        self.assertIn("line 2", str(ctx.exception))

    def test_unknown_circle_reports_choices(self):
        rp, ip = self.write("name,circle\n阿岚,bestie\n", "name,date,initiator\n")
        with self.assertRaises(da.ParseError) as ctx:
            da.read_roster(rp)
        self.assertIn("bestie", str(ctx.exception))
        self.assertIn("inner", str(ctx.exception))

    def test_duplicate_name_rejected(self):
        rp, ip = self.write("name,circle\n阿岚,close\n阿岚,inner\n",
                            "name,date,initiator\n")
        with self.assertRaises(da.ParseError) as ctx:
            da.read_roster(rp)
        self.assertIn("duplicate", str(ctx.exception))

    def test_bad_initiator_rejected(self):
        rp, ip = self.write(self.ROSTER, "name,date,initiator\n阿岚,2025-09-01,nobody\n")
        with self.assertRaises(da.ParseError) as ctx:
            da.read_interactions(ip)
        self.assertIn("nobody", str(ctx.exception))

    def test_bad_date_reports_line(self):
        rp, ip = self.write(self.ROSTER, "name,date,initiator\n阿岚,昨天,me\n")
        with self.assertRaises(da.ParseError) as ctx:
            da.read_interactions(ip)
        self.assertIn("line 2", str(ctx.exception))

    def test_ghost_interactions_rejected(self):
        rp, ip = self.write(self.ROSTER,
                            "name,date,initiator\n路人,2025-09-01,me\n")
        with self.assertRaises(da.ParseError) as ctx:
            da.load_ledger(rp, ip, AS_OF, {})
        self.assertIn("路人", str(ctx.exception))
        self.assertIn("roster", str(ctx.exception))

    def test_birthday_formats(self):
        self.assertEqual(da.parse_monthday("03-08"), (3, 8))
        self.assertEqual(da.parse_monthday("1998/3/8"), (3, 8))
        self.assertEqual(da.parse_monthday("1998年3月8日"), (3, 8))
        with self.assertRaises(da.ParseError):
            da.parse_monthday("三八节")

    def test_no_header_rejected(self):
        tmp = tempfile.mkdtemp()
        rp = os.path.join(tmp, "r.csv")
        with open(rp, "w", encoding="utf-8") as fh:
            fh.write("阿岚,close\n")
        with self.assertRaises(da.ParseError) as ctx:
            da.read_roster(rp)
        self.assertIn("no header", str(ctx.exception))

    def test_cadence_column_must_be_positive_int(self):
        rp, _ = self.write("name,circle,cadence\n阿岚,close,abc\n",
                           "name,date,initiator\n")
        with self.assertRaises(da.ParseError) as ctx:
            da.read_roster(rp)
        self.assertIn("integer", str(ctx.exception))
        rp, _ = self.write("name,circle,cadence\n阿岚,close,0\n",
                           "name,date,initiator\n")
        with self.assertRaises(da.ParseError):
            da.read_roster(rp)


# ---------------------------------------------------------------------------
# cadence resolution
# ---------------------------------------------------------------------------

class CadenceTests(LedgerFixture):
    def relations(self, cadence_col=None, cli=None):
        header = "name,circle" + (",cadence" if cadence_col is not None else "") + "\n"
        row = "阿岚,close" + (","+str(cadence_col) if cadence_col is not None else "") + "\n"
        return build_relations(header + row, "name,date,initiator\n阿岚,2025-09-01,me\n",
                               overrides=cli)

    def test_default_cadence_table(self):
        rels, _ = build_relations(
            "name,circle\nA,inner\nB,close\nC,active\nD,outer\n",
            "name,date,initiator\nA,2025-09-01,me\n")
        self.assertEqual([rels[k]["cadence"] for k in ("A", "B", "C", "D")],
                         [30, 90, 180, 365])

    def test_row_overrides_circle_default(self):
        rels, _ = self.relations(cadence_col=14)
        self.assertEqual(rels["阿岚"]["cadence"], 14)

    def test_cli_overrides_circle_default(self):
        rels, _ = self.relations(cli={"close": 45})
        self.assertEqual(rels["阿岚"]["cadence"], 45)

    def test_row_beats_cli(self):
        rels, _ = self.relations(cadence_col=14, cli={"close": 45})
        self.assertEqual(rels["阿岚"]["cadence"], 14)


# ---------------------------------------------------------------------------
# band arithmetic
# ---------------------------------------------------------------------------

class BandTests(LedgerFixture):
    def band_for_elapsed(self, days, cadence=90):
        last = AS_OF - timedelta(days=days)
        rels, _ = build_relations(
            "name,circle,cadence\n阿岚,close,%d\n" % cadence,
            "name,date,initiator\n阿岚,%s,me\n" % last.isoformat())
        return rels["阿岚"]

    def test_band_boundaries(self):
        self.assertEqual(self.band_for_elapsed(90)["band"], "FRESH")     # 1.0×
        self.assertEqual(self.band_for_elapsed(91)["band"], "OVERDUE")
        self.assertEqual(self.band_for_elapsed(180)["band"], "OVERDUE")  # 2.0×
        self.assertEqual(self.band_for_elapsed(181)["band"], "DRIFTING")
        self.assertEqual(self.band_for_elapsed(360)["band"], "DRIFTING") # 4.0×
        self.assertEqual(self.band_for_elapsed(361)["band"], "GONE")

    def test_arrears_math(self):
        rel = self.band_for_elapsed(103)
        self.assertEqual(rel["elapsed"], 103)
        self.assertEqual(rel["arrears"], 13)
        self.assertAlmostEqual(rel["ratio"], 103 / 90.0)

    def test_never_band_without_contacts(self):
        rels, _ = build_relations("name,circle\n何朗,outer\n",
                                  "name,date,initiator\n")
        rel = rels["何朗"]
        self.assertEqual(rel["band"], "NEVER")
        self.assertIsNone(rel["elapsed"])
        self.assertEqual(rel["contacts"], 0)


# ---------------------------------------------------------------------------
# silence slope
# ---------------------------------------------------------------------------

class SlopeTests(unittest.TestCase):
    def slope_for_gaps(self, gaps, initiators=None):
        start = date(2024, 1, 1)
        events = []
        day = start
        seq = list(gaps)
        for i in range(len(seq) + 1):
            who = (initiators[i] if initiators else "me")
            events.append({"date": day, "initiator": who, "line": i + 2})
            if i < len(seq):
                day = day + __import__("datetime").timedelta(days=seq[i])
        return da.silence_slope(events)

    def test_unknown_below_three_contacts(self):
        self.assertEqual(self.slope_for_gaps([30])["slope"], "UNKNOWN")
        self.assertEqual(da.silence_slope([])["slope"], "UNKNOWN")

    def test_steady(self):
        s = self.slope_for_gaps([30, 30, 30])
        self.assertEqual(s["slope"], "STEADY")
        self.assertAlmostEqual(s["growth"], 1.0)

    def test_lengthening_at_and_above_two(self):
        self.assertEqual(self.slope_for_gaps([30, 30, 60])["slope"], "LENGTHENING")
        s = self.slope_for_gaps([30, 28, 60, 55, 130])
        self.assertEqual(s["slope"], "LENGTHENING")
        self.assertAlmostEqual(s["median_gap"], 42.5)
        self.assertEqual(s["last_gap"], 130)

    def test_warming(self):
        s = self.slope_for_gaps([90, 90, 30])
        self.assertEqual(s["slope"], "WARMING")
        self.assertAlmostEqual(s["growth"], 30 / 90.0)

    def test_median_of_prefix_not_perturbed_by_last_gap(self):
        # last gap 1000d must not inflate the baseline median
        s = self.slope_for_gaps([10, 10, 10, 1000])
        self.assertEqual(s["median_gap"], 10)
        self.assertEqual(s["last_gap"], 1000)
        self.assertEqual(s["slope"], "LENGTHENING")

    def test_zero_prefix_gap_safe(self):
        s = self.slope_for_gaps([0, 0, 0])
        self.assertEqual(s["slope"], "UNKNOWN")


class SlopeOverdueLineTests(LedgerFixture):
    def test_show_flags_overdue_by_own_history(self):
        # gaps 90,90 then 180d of silence: even by their own (stretched)
        # rhythm the contact is overdue.
        rows = contacts("阿岚", date(2025, 1, 1), [90, 90], ["me", "them"])
        rp, ip = self.write("name,circle,cadence\n阿岚,outer,365\n",
                            "name,date,initiator\n" + "\n".join(rows) + "\n")
        report = da.load_ledger(rp, ip, AS_OF, {})
        rel = report["relations"][0]
        self.assertEqual(rel["slope"]["slope"], "STEADY")
        due_by_history = rel["last_contact"] + timedelta(days=rel["slope"]["last_gap"])
        self.assertGreater(AS_OF, due_by_history)


# ---------------------------------------------------------------------------
# unilateral balance
# ---------------------------------------------------------------------------

class UnilateralTests(unittest.TestCase):
    def idx(self, initiators):
        events = [{"date": date(2025, 1, 1) + timedelta(days=10 * i),
                   "initiator": w, "line": i}
                  for i, w in enumerate(initiators)]
        return da.unilateral_index(events)

    def test_all_mine_is_unilateral(self):
        self.assertEqual(self.idx(["me"] * 5), 1.0)

    def test_window_is_last_five(self):
        # 6th (oldest) contact was theirs — outside the K=5 window
        self.assertEqual(self.idx(["them", "me", "me", "me", "me", "me"]), 1.0)

    def test_below_threshold_not_flagged(self):
        self.assertEqual(self.idx(["them", "them", "me", "me"]), 0.5)

    def test_needs_two_contacts(self):
        self.assertIsNone(self.idx(["me"]))
        self.assertIsNone(da.unilateral_index([]))


# ---------------------------------------------------------------------------
# occasions
# ---------------------------------------------------------------------------

class OccasionTests(unittest.TestCase):
    def test_next_occasion_same_year(self):
        nxt = da.next_occasion((12, 5), date(2025, 12, 1))
        self.assertEqual(nxt, date(2025, 12, 5))

    def test_next_occasion_wraps_year(self):
        nxt = da.next_occasion((3, 8), date(2025, 12, 1))
        self.assertEqual(nxt, date(2026, 3, 8))

    def test_feb29_celebrates_march1(self):
        nxt = da.next_occasion((2, 29), date(2025, 1, 1))
        self.assertEqual(nxt, date(2025, 3, 1))

    def test_occasion_flag_window(self):
        def flag(days):
            return da.occasion_flag({"band": "OVERDUE", "days_to_occasion": days,
                                     "slope": {"slope": "STEADY"},
                                     "unilateral": 0.0, "contacts": 2,
                                     "name": "x", "circle": "close",
                                     "ratio": 1.5, "cadence": 90,
                                     "elapsed": 135})
        self.assertTrue(flag(7))
        self.assertTrue(flag(0))
        self.assertFalse(flag(8))
        self.assertFalse(flag(None))


# ---------------------------------------------------------------------------
# ledger command
# ---------------------------------------------------------------------------

class LedgerTests(LedgerFixture):
    ROSTER = ("name,circle,birthday\n"
              "陈默,inner,05-12\n"
              "林小满,close,12-05\n"
              "王一帆,active,\n"
              "何朗,outer,\n")
    INTERACTIONS = ("name,date,initiator\n"
                    "陈默,2024-01-10,me\n"
                    "陈默,2024-02-09,me\n"
                    "陈默,2024-03-08,me\n"
                    "陈默,2024-05-07,me\n"
                    "陈默,2024-07-01,me\n"
                    "陈默,2024-11-08,me\n"
                    "林小满,2025-08-20,them\n"
                    "王一帆,2025-11-10,me\n")

    def test_ranking_bands_then_ratio(self):
        _, report = build_relations(self.ROSTER, self.INTERACTIONS)
        order = [r["name"] for r in report["relations"]]
        # 陈默 (GONE 12.9×) first, OVERDUE by ratio, FRESH by ratio, NEVER last
        self.assertEqual(order, ["陈默", "林小满", "王一帆", "何朗"])

    def test_counts_summary(self):
        _, report = build_relations(self.ROSTER, self.INTERACTIONS)
        c = report["counts"]
        self.assertEqual((c["GONE"], c["OVERDUE"], c["FRESH"], c["NEVER"]),
                         (1, 1, 1, 1))

    def test_farthest_gone_is_the_most_drifted(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        report = da.load_ledger(rp, ip, AS_OF, {})
        drifted = [r for r in report["relations"] if r["band"] != "FRESH"]
        worst = max(drifted, key=lambda r: (da.SORT_RANK[r["band"]], r["ratio"] or 0))
        self.assertEqual(worst["name"], "陈默")
        self.assertAlmostEqual(worst["ratio"], 388 / 30.0, places=2)

    def test_text_output_contains_marks(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = da.main(["ledger", rp, ip, "--as-of", "2025-12-01"])
        text = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("!! GONE", text)
        self.assertIn("~ OVERDUE★", text)          # birthday door open
        self.assertIn("⚠", text)                    # lengthening slope
        self.assertIn("↺", text)                    # unilateral
        self.assertIn("?? NEVER", text)
        self.assertIn("farthest gone : 陈默", text)

    def test_circle_filter_updates_counts(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        buf = io.StringIO()
        with redirect_stdout(buf):
            da.main(["ledger", rp, ip, "--as-of", "2025-12-01",
                     "--circle", "close"])
        text = buf.getvalue()
        self.assertIn("1 relation", text)
        self.assertIn("林小满", text)
        self.assertNotIn("陈默", text)

    def test_unknown_circle_flag_rejected(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        code = da.main(["ledger", rp, ip, "--circle", "besties"])
        self.assertEqual(code, 3)

    def test_json_output_shape(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = da.main(["ledger", rp, ip, "--as-of", "2025-12-01",
                            "--format", "json"])
        payload = json.loads(buf.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["tracked"], 4)
        self.assertEqual(payload["counts"]["GONE"], 1)
        chen = next(r for r in payload["relations"] if r["name"] == "陈默")
        self.assertEqual(chen["band"], "GONE")
        self.assertEqual(chen["elapsed"], 388)
        self.assertEqual(chen["slope"]["slope"], "LENGTHENING")
        self.assertAlmostEqual(chen["slope"]["growth"], 130 / 42.5)
        self.assertEqual(chen["unilateral"], 1.0)
        self.assertEqual(chen["days_to_occasion"], 162)


# ---------------------------------------------------------------------------
# repair list
# ---------------------------------------------------------------------------

class RepairTests(LedgerFixture):
    # 林小满: close, overdue, birthday 12-05 (4d away)  → door, first
    # 陈默:   inner, gone (12.9×), unilateral+slope     → second
    # 苏黎:   close, overdue 1.1×, no door              → third
    # 何朗:   outer, never contacted                    → last
    ROSTER = ("name,circle,birthday\n"
              "陈默,inner,05-12\n"
              "林小满,close,12-05\n"
              "苏黎,close,03-08\n"
              "何朗,outer,\n")
    INTERACTIONS = ("name,date,initiator\n"
                    "陈默,2024-01-10,me\n"
                    "陈默,2024-02-09,me\n"
                    "陈默,2024-03-08,me\n"
                    "陈默,2024-05-07,me\n"
                    "陈默,2024-07-01,me\n"
                    "陈默,2024-11-08,me\n"
                    "林小满,2025-08-20,me\n"
                    "苏黎,2025-08-01,them\n")

    def test_order_doors_first_then_drift(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        report = da.load_ledger(rp, ip, AS_OF, {})
        ordered = da.repair_list(report, None)
        self.assertEqual([r["name"] for r in ordered],
                         ["林小满", "陈默", "苏黎", "何朗"])

    def test_gate_exit_codes(self):
        self.assertEqual(self.run_cli(
            "repair", self.ROSTER, self.INTERACTIONS,
            "--as-of", "2025-12-01"), 4)
        fresh_roster = "name,circle\n阿珂,close\n"
        fresh_inters = "name,date,initiator\n阿珂,2025-11-15,me\n"
        self.assertEqual(self.run_cli(
            "repair", fresh_roster, fresh_inters, "--as-of", "2025-12-01"), 0)

    def test_all_green_gate_text(self):
        buf = io.StringIO()
        rp, ip = self.write("name,circle\n阿珂,close\n",
                            "name,date,initiator\n阿珂,2025-11-15,me\n")
        with redirect_stdout(buf):
            code = da.main(["repair", rp, ip, "--as-of", "2025-12-01"])
        self.assertEqual(code, 0)
        self.assertIn("gate: PASS", buf.getvalue())

    def test_within_truncates(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        report = da.load_ledger(rp, ip, AS_OF, {})
        self.assertEqual(len(da.repair_list(report, 2)), 2)
        self.assertEqual(len(da.repair_list(report, None)), 4)

    def test_advice_per_band(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        report = da.load_ledger(rp, ip, AS_OF, {})
        ordered = da.repair_list(report, None)
        advice = {r["name"]: da.REPAIR_ADVICE[r["band"]] for r in ordered}
        self.assertIn("one message", advice["林小满"])
        self.assertIn("occasion", advice["陈默"])
        self.assertIn("never contacted", advice["何朗"])

    def test_repair_json_gate(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = da.main(["repair", rp, ip, "--as-of", "2025-12-01",
                            "--format", "json"])
        self.assertEqual(code, 4)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["gate"], "FAIL")
        self.assertEqual(payload["due"], 4)
        self.assertEqual(payload["list"][0]["name"], "林小满")

    def test_unilateral_reason_line(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        buf = io.StringIO()
        with redirect_stdout(buf):
            da.main(["repair", rp, ip, "--as-of", "2025-12-01"])
        self.assertIn("you initiated 5 of the last 5", buf.getvalue())
        self.assertIn("gaps stretching", buf.getvalue())


# ---------------------------------------------------------------------------
# privacy
# ---------------------------------------------------------------------------

class RedactTests(LedgerFixture):
    ROSTER = "name,circle,birthday\n林小满,close,12-05\n"
    INTERACTIONS = "name,date,initiator\n林小满,2025-08-20,me\n"

    def test_ledger_redact_hides_names(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        buf = io.StringIO()
        with redirect_stdout(buf):
            da.main(["ledger", rp, ip, "--as-of", "2025-12-01", "--redact"])
        text = buf.getvalue()
        self.assertNotIn("林小满", text)
        self.assertIn("anon-", text)

    def test_repair_json_redact(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        buf = io.StringIO()
        with redirect_stdout(buf):
            da.main(["repair", rp, ip, "--as-of", "2025-12-01",
                     "--format", "json", "--redact"])
        payload = json.loads(buf.getvalue())
        self.assertTrue(all(row["name"].startswith("anon-")
                            for row in payload["list"]))

    def test_show_redact(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        buf = io.StringIO()
        with redirect_stdout(buf):
            da.main(["show", rp, ip, "林小满", "--as-of", "2025-12-01",
                     "--redact"])
        self.assertNotIn("林小满", buf.getvalue())
        self.assertIn("anon-", buf.getvalue())


# ---------------------------------------------------------------------------
# show dossier
# ---------------------------------------------------------------------------

class ShowTests(LedgerFixture):
    ROSTER = ("name,circle,birthday\n"
              "陈默,inner,05-12\n"
              "何朗,outer,\n")
    INTERACTIONS = ("name,date,initiator\n"
                    "陈默,2024-01-10,me\n"
                    "陈默,2024-02-09,me\n"
                    "陈默,2024-03-08,me\n"
                    "陈默,2024-05-07,me\n"
                    "陈默,2024-07-01,me\n"
                    "陈默,2024-11-08,me\n")

    def test_dossier_fields(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = da.main(["show", rp, ip, "陈默", "--as-of", "2025-12-01"])
        text = buf.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("inner 核心 · cadence 30d", text)
        self.assertIn("!! GONE", text)
        self.assertIn("silent 388d · arrears 358d", text)
        self.assertIn("LENGTHENING — last gap 130d vs. median 42.5d (3.06×)", text)
        self.assertIn("overdue even by your own history", text)
        self.assertIn("UNILATERAL: it stops the moment you do", text)
        self.assertIn("in 162d (05-12)", text)
        self.assertIn("2024-01-10(me)", text)

    def test_never_dossier(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        buf = io.StringIO()
        with redirect_stdout(buf):
            da.main(["show", rp, ip, "何朗", "--as-of", "2025-12-01"])
        self.assertIn("?? NEVER", buf.getvalue())
        self.assertIn("none on record", buf.getvalue())

    def test_unknown_name_exit_3_with_hint(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        buf = io.StringIO()
        import contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = da.main(["show", rp, ip, "陈陌", "--as-of", "2025-12-01"])
        self.assertEqual(code, 3)
        self.assertIn("陈陌", err.getvalue())
        self.assertIn("陈默", err.getvalue())


# ---------------------------------------------------------------------------
# CLI semantics
# ---------------------------------------------------------------------------

class CliTests(LedgerFixture):
    ROSTER = "name,circle\n阿岚,close\n"
    INTERACTIONS = "name,date,initiator\n阿岚,2025-09-01,me\n"

    def test_no_args_exit_2(self):
        self.assertEqual(da.main([]), 2)

    def test_missing_files_exit_3(self):
        code = da.main(["ledger", "/nonexistent/r.csv", "/nonexistent/i.csv"])
        self.assertEqual(code, 3)

    def test_as_of_defaults_to_today(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        report = da.load_ledger(rp, ip, date.today(), {})
        self.assertEqual(report["as_of"], date.today())

    def test_bad_as_of_clean_usage_error(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        with self.assertRaises(SystemExit) as ctx:   # argparse exits cleanly
            da.main(["ledger", rp, ip, "--as-of", "明天"])
        self.assertEqual(ctx.exception.code, 2)      # usage error, no traceback

    def test_bad_circle_cadence_exit_3(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        self.assertEqual(da.main(
            ["ledger", rp, ip, "--circle-cadence", "besties=30"]), 3)
        self.assertEqual(da.main(
            ["ledger", rp, ip, "--circle-cadence", "close=abc"]), 3)
        self.assertEqual(da.main(
            ["ledger", rp, ip, "--circle-cadence", "close"]), 3)

    def test_circle_cadence_changes_band(self):
        rp, ip = self.write(self.ROSTER, self.INTERACTIONS)
        buf = io.StringIO()
        with redirect_stdout(buf):
            da.main(["ledger", rp, ip, "--as-of", "2025-12-01",
                     "--circle-cadence", "close=7"])
        self.assertIn("GONE", buf.getvalue())   # 91d / 7d = 13×


# ---------------------------------------------------------------------------
# dogfood: examples reproducible + key numbers
# ---------------------------------------------------------------------------

class DogfoodTests(unittest.TestCase):
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def test_examples_in_sync(self):
        import subprocess
        proc = subprocess.run(
            [sys.executable, os.path.join(self.ROOT, "examples",
                                          "build_examples.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0,
                         msg="examples out of sync:\n" + proc.stdout + proc.stderr)
        self.assertIn("examples in sync", proc.stdout)

    def test_sample_numbers(self):
        with open(os.path.join(self.ROOT, "examples", "sample-ledger.txt"),
                  encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("farthest gone : 陈默", text)
        self.assertIn("388d", text)                # silent 388 days
        self.assertIn("!! GONE", text)
        self.assertIn("?? NEVER", text)
        self.assertIn("~ OVERDUE★", text)          # birthday door open
        self.assertIn("12.9×", text)               # ratio vs own rhythm


if __name__ == "__main__":
    unittest.main()
