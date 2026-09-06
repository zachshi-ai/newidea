#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Acceptance tests for off-track (掉带).

Sample numbers were computed straight from the references CSVs + the LMS
formula by an independent cross-check script BEFORE the CLI existed; the
CLI must reproduce them (样例数字先手算再钉测试).
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import off_track as T  # noqa: E402

EXAMPLES = os.path.join(ROOT, 'examples')


class Base(unittest.TestCase):
    _tmp_counter = [0]

    def cli(self, *args):
        """Returns (exit_code, stdout). argparse SystemExit is unwrapped."""
        out = io.StringIO()
        err = io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = T.main(list(args))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 2
        return code, out.getvalue()

    def cli_err(self, *args):
        """Returns (exit_code, stderr_text)."""
        out = io.StringIO()
        err = io.StringIO()
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = T.main(list(args))
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 2
        return code, err.getvalue()

    def tmp_ledger(self, name, rows):
        Base._tmp_counter[0] += 1
        path = os.path.join(EXAMPLES, '_tmp_%s_%d.tsv' % (name, Base._tmp_counter[0]))
        with open(path, 'w') as fh:
            fh.write('date\tchild\tborn\tsex\theight_cm\tweight_kg\n')
            for r in rows:
                fh.write('\t'.join(str(c) for c in r) + '\n')
        self.addCleanup(os.remove, path)
        return path


class LmsEngine(Base):
    def test_median_round_trip_at_every_node(self):
        bad = 0
        for sex in (1, 2):
            for agemo, L, M, S in T.TABLES['HFA'][sex]:
                if abs(T.value_at_percentile('HFA', sex, agemo, 50.0) - M) > 1e-6:
                    bad += 1
                if abs(T.percentile_of('HFA', sex, agemo, M) - 50.0) > 1e-6:
                    bad += 1
        self.assertEqual(bad, 0)

    def test_value_increasing_in_percentile(self):
        for sex in (1, 2):
            for agemo in (0.0, 12.0, 24.0, 60.0, 120.0, 200.0, 240.0):
                vals = [T.value_at_percentile('HFA', sex, agemo, p)
                        for p in (1, 3, 10, 25, 50, 75, 90, 97, 99)]
                for a, b in zip(vals, vals[1:]):
                    self.assertLess(a, b)

    def test_band_edges_belong_to_higher_band(self):
        self.assertEqual(T.band_of(2.999), 0)
        self.assertEqual(T.band_of(3.0), 1)
        self.assertEqual(T.band_of(10.0), 2)
        self.assertEqual(T.band_of(50.0), 4)
        self.assertEqual(T.band_of(75.0), 5)
        self.assertEqual(T.band_of(97.0), 7)
        self.assertEqual(T.band_of(96.999), 6)

    def test_bmi_table_starts_at_24m(self):
        self.assertEqual(T.TABLES['BMI'][1][0][0], 24.0)

    def test_infant_bmi_pct_returns_none(self):
        path = self.tmp_ledger('infbmi', [
            ('2026-01-10', 'bei', '2025-02-10', 'F', '76.2', '9.6')])
        rows, as_of = T.load(path, None)
        self.assertIsNone(rows[0].pct(bmi_mode=True))
        self.assertIsNotNone(rows[0].pct())

    def test_crosscheck_sample_values_reproduced(self):
        # independent cross-check numbers (from CSV + LMS formula directly)
        self.assertAlmostEqual(T.value_at_percentile('HFA', 2, 96, 50.0), 127.6, delta=0.05)
        self.assertAlmostEqual(T.value_at_percentile('HFA', 1, 48, 75.0), 105.1, delta=0.05)
        self.assertAlmostEqual(T.value_at_percentile('HFA', 1, 108, 10.0), 125.7, delta=0.05)
        self.assertAlmostEqual(T.percentile_of('HFA', 1, 84, 119.8), 36.0, delta=0.3)
        self.assertAlmostEqual(T.value_at_percentile('BMI', 1, 108, 90.0), 19.45, delta=0.05)


class LedgerParsing(Base):
    def test_chinese_column_aliases(self):
        path = os.path.join(EXAMPLES, '_tmp_cn.tsv')
        with open(path, 'w') as fh:
            fh.write('日期\t孩子\t生日\t性别\t身高\t体重\n')
            fh.write('2024-03-15\t小明\t2022-03-15\t男\t87.7\t11.9\n')
        self.addCleanup(os.remove, path)
        code, out = self.cli('report', path)
        self.assertEqual(code, T.EXIT_OK)  # 1 row -> thin, position printed
        self.assertIn('P50', out)

    def test_sex_alias_forms(self):
        for alias, expect in (('M', 'M'), ('male', 'M'), ('男', 'M'), ('1', 'M'),
                              ('F', 'F'), ('girl', 'F'), ('女', 'F'), ('2', 'F')):
            path = self.tmp_ledger('sexalias', [
                ('2024-03-15', 'kid', '2022-03-15', alias, '96.9', '')])
            rows, _ = T.load(path, None)
            self.assertEqual(rows[0].sex, expect)

    def test_missing_required_column(self):
        path = os.path.join(EXAMPLES, '_tmp_nc.tsv')
        with open(path, 'w') as fh:
            fh.write('date\tchild\tsex\theight_cm\n')
            fh.write('2024-03-15\tkid\tM\t96.9\n')
        self.addCleanup(os.remove, path)
        code, errtxt = self.cli_err('report', path)
        self.assertEqual(code, T.EXIT_BROKEN)
        self.assertIn('born', errtxt)

    def test_unknown_column(self):
        path = os.path.join(EXAMPLES, '_tmp_uc.tsv')
        with open(path, 'w') as fh:
            fh.write('date\tchild\tborn\tsex\theight_cm\tshoe_size\n')
            fh.write('2024-03-15\tkid\t2022-03-15\tM\t96.9\t17\n')
        self.addCleanup(os.remove, path)
        code, errtxt = self.cli_err('report', path)
        self.assertEqual(code, T.EXIT_BROKEN)
        self.assertIn('shoe_size', errtxt)

    def test_missing_file(self):
        code, errtxt = self.cli_err('report', os.path.join(EXAMPLES, 'nope.tsv'))
        self.assertEqual(code, T.EXIT_BROKEN)
        self.assertIn('not found', errtxt)

    def test_bad_date_and_bad_sex(self):
        path = self.tmp_ledger('badate', [
            ('2024-13-40', 'kid', '2022-03-15', 'M', '96.9', '')])
        code, errtxt = self.cli_err('report', path)
        self.assertEqual(code, T.EXIT_BROKEN)
        self.assertIn('bad date', errtxt)
        path = self.tmp_ledger('badsex', [
            ('2024-03-15', 'kid', '2022-03-15', 'X', '96.9', '')])
        code, errtxt = self.cli_err('report', path)
        self.assertEqual(code, T.EXIT_BROKEN)
        self.assertIn('sex', errtxt)

    def test_as_of_excludes_later_rows(self):
        # as-of is a time machine, not a validator: rows after it are the
        # not-yet-happened future and are excluded, never flagged broken
        path = self.tmp_ledger('future', [
            ('2022-03-15', 'kid', '2020-03-15', 'M', '91.2', ''),
            ('2030-03-15', 'kid', '2020-03-15', 'M', '140.0', '')])
        code, out = self.cli('report', path, '--as-of', '2025-01-01')
        self.assertEqual(code, T.EXIT_OK)
        self.assertIn('age 24.0 mo', out)
        self.assertNotIn('140.0', out)

    def test_as_of_before_first_row_is_an_error(self):
        path = self.tmp_ledger('emptywin', [
            ('2022-03-15', 'kid', '2020-03-15', 'M', '91.2', '')])
        code, errtxt = self.cli_err('report', path, '--as-of', '2021-01-01')
        self.assertEqual(code, T.EXIT_BROKEN)
        self.assertIn('no measurement rows', errtxt)

    def test_duplicate_measurement_rejected(self):
        path = self.tmp_ledger('dup', [
            ('2024-03-15', 'kid', '2022-03-15', 'M', '96.9', ''),
            ('2024-03-15', 'kid', '2022-03-15', 'M', '97.0', '')])
        code, errtxt = self.cli_err('report', path)
        self.assertEqual(code, T.EXIT_BROKEN)
        self.assertIn('duplicate', errtxt)

    def test_two_birthdays_rejected(self):
        path = self.tmp_ledger('twoborn', [
            ('2024-03-15', 'kid', '2022-03-15', 'M', '96.9', ''),
            ('2025-03-15', 'kid', '2022-03-16', 'M', '104.0', '')])
        code, errtxt = self.cli_err('report', path)
        self.assertEqual(code, T.EXIT_BROKEN)
        self.assertIn('two birthdays', errtxt)

    def test_height_shrinkage_rejected(self):
        path = self.tmp_ledger('shrink', [
            ('2024-03-15', 'kid', '2022-03-15', 'M', '96.9', ''),
            ('2025-03-15', 'kid', '2022-03-15', 'M', '95.0', '')])
        code, errtxt = self.cli_err('report', path)
        self.assertEqual(code, T.EXIT_BROKEN)
        self.assertIn('shrank', errtxt)

    def test_height_domain_rejected(self):
        path = self.tmp_ledger('domain', [
            ('2024-03-15', 'kid', '2022-03-15', 'M', '250.0', '')])
        code, errtxt = self.cli_err('report', path)
        self.assertEqual(code, T.EXIT_BROKEN)
        self.assertIn('plausible', errtxt)

    def test_age_beyond_tables_rejected(self):
        path = self.tmp_ledger('old', [
            ('2024-03-15', 'kid', '1990-03-15', 'M', '175.0', '')])
        code, errtxt = self.cli_err('report', path)
        self.assertEqual(code, T.EXIT_BROKEN)
        self.assertIn('beyond reference tables', errtxt)

    def test_multi_child_ledgers_stay_separate(self):
        path = os.path.join(EXAMPLES, '_tmp_multi.tsv')
        with open(path, 'w') as fh:
            fh.write('date\tchild\tborn\tsex\theight_cm\n')
            fh.write('2026-03-15\ta\t2018-03-15\tF\t129.1\n')
            fh.write('2026-03-15\tb\t2018-03-15\tF\t121.0\n')
        self.addCleanup(os.remove, path)
        code, out = self.cli('report', path)
        self.assertEqual(code, T.EXIT_OK)
        self.assertIn('child a', out)
        self.assertIn('child b', out)


class Grading(Base):
    def test_xiaoman_on_track_green(self):
        code, out = self.cli('report', os.path.join(EXAMPLES, 'xiaoman.tsv'),
                             '--mom', '160', '--dad', '172')
        self.assertEqual(code, T.EXIT_OK)
        self.assertIn('GREEN', out)
        self.assertIn('band path:   4 4 4 4 4 4 4', out)
        self.assertNotIn('RED', out)

    def test_xiaoman_bmi_stable(self):
        code, out = self.cli('report', os.path.join(EXAMPLES, 'xiaoman.tsv'))
        self.assertIn('BMI TRACK', out)
        self.assertIn('band path:   4 4 4 4 4 4 4', out)

    def test_xiaozhou_off_track_red(self):
        code, out = self.cli('report', os.path.join(EXAMPLES, 'xiaozhou.tsv'))
        self.assertEqual(code, T.EXIT_RED)
        self.assertIn('band path:   5 4 3 3 2 1', out)
        self.assertIn('drift -4', out)
        self.assertIn('growth faltering', out)
        # every single window is at most one band: the trap this tool exists for
        self.assertIn('steepest single window 1', out)
        self.assertIn('BMI track drifted 4 band(s) UP', out)

    def test_xiaozhou_velocity_front_windows_still_ok(self):
        # the first two windows clear the 5 cm/yr floor: velocity alone
        # would have stayed quiet for two years
        code, out = self.cli('velocity', os.path.join(EXAMPLES, 'xiaozhou.tsv'))
        self.assertEqual(code, T.EXIT_RED)
        self.assertIn('5.2', out)
        self.assertIn('4.5', out)
        self.assertIn('BELOW', out)

    def test_xiaoshu_late_bloomer_portrait(self):
        code, out = self.cli('report', os.path.join(EXAMPLES, 'xiaoshu.tsv'),
                             '--mom', '168', '--dad', '180',
                             '--family-late-bloomer')
        self.assertEqual(code, T.EXIT_OK)
        self.assertIn('GREEN', out)
        self.assertIn('PORTRAIT', out)
        self.assertIn('bone age is the only referee', out)
        self.assertIn('projection is BELOW target range', out)

    def test_portrait_requires_family_flag(self):
        code, out = self.cli('report', os.path.join(EXAMPLES, 'xiaoshu.tsv'),
                             '--mom', '168', '--dad', '180')
        self.assertEqual(code, T.EXIT_OK)
        self.assertNotIn('PORTRAIT', out)
        self.assertIn('below target range: worth measuring', out)

    def test_portrait_needs_intact_velocity(self):
        # same child but an artificially broken velocity floor: the portrait
        # must NOT fire even with family history (velocity is a precondition)
        code, out = self.cli('report', os.path.join(EXAMPLES, 'xiaoshu.tsv'),
                             '--mom', '168', '--dad', '180',
                             '--family-late-bloomer', '--velocity-floor', '8')
        self.assertEqual(code, T.EXIT_RED)
        self.assertNotIn('PORTRAIT', out)

    def test_xiaodou_thin_ledger_declines_grading(self):
        code, out = self.cli('report', os.path.join(EXAMPLES, 'xiaodou.tsv'))
        self.assertEqual(code, T.EXIT_OK)
        self.assertIn('P79.5', out)          # position is still published
        self.assertIn('DECLINED', out)
        self.assertIn('thin ledger', out)
        self.assertNotIn('RED', out)

    def test_as_of_replay_turns_red_green(self):
        # pinned to 2017-07-02 (third row) xiaozhou has only drifted -1 band:
        # last year this ledger was green. as-of is the time machine.
        code, out = self.cli('report', os.path.join(EXAMPLES, 'xiaozhou.tsv'),
                             '--as-of', '2016-07-02')
        self.assertEqual(code, T.EXIT_OK)
        self.assertIn('band path:   5 4', out)
        self.assertNotIn('RED', out)

    def test_cross_bands_flag_moves_the_line(self):
        led = os.path.join(EXAMPLES, 'xiaozhou.tsv')
        code, _ = self.cli('report', led, '--cross-bands', '3')
        self.assertEqual(code, T.EXIT_RED)   # drift -4 >= 3
        code, out = self.cli('report', led, '--cross-bands', '5')
        self.assertEqual(code, T.EXIT_RED)   # velocity floor is independent of cross-bands
        self.assertNotIn('band(s) DOWN', out)
        code, out = self.cli('report', led, '--cross-bands', '5', '--velocity-floor', '1')
        self.assertEqual(code, T.EXIT_OK)    # nothing left to trip
        self.assertIn('GREEN', out)

    def test_infant_drift_never_grades(self):
        # an infant who "crosses" three bands before 24mo: physiologic, green
        path = self.tmp_ledger('infant', [
            ('2025-05-10', 'bei', '2024-05-10', 'M', '59.0', ''),
            ('2025-11-10', 'bei', '2024-05-10', 'M', '71.0', ''),
            ('2026-05-10', 'bei', '2024-05-10', 'M', '76.5', '')])
        code, out = self.cli('report', path)
        self.assertEqual(code, T.EXIT_OK)
        self.assertIn('thin ledger', out)
        self.assertIn('DECLINED', out)
        self.assertNotIn('RED', out)

    def test_short_span_declines(self):
        # two gradable rows only 100 days apart: no crossing grade
        path = self.tmp_ledger('shortspan', [
            ('2026-01-15', 'kid', '2022-03-15', 'M', '102.0', ''),
            ('2026-04-25', 'kid', '2022-03-15', 'M', '103.4', '')])
        code, out = self.cli('report', path)
        self.assertEqual(code, T.EXIT_OK)
        self.assertIn('DECLINED', out)

    def test_window_crossing_fires_even_if_drift_small(self):
        # engine-level: an acute single-window crossing pulls the red light
        # even when the whole-path drift stays under the gate. A ledger that
        # drops 2+ bands inside one window cannot also stay monotone in
        # height (by design the regression check catches it first), so this
        # grading rule is pinned on synthetic windows.
        m = object.__new__(T.Measure)
        wins = []
        class FakeM(object):
            def __init__(self, d):
                self.date = d
        pts = [(FakeM(1), 60.0), (FakeM(2), 40.0), (FakeM(3), 55.0)]
        w1 = T.Window(pts[0][0], pts[1][0], -3, 4.0, 5.0)
        w2 = T.Window(pts[1][0], pts[2][0], 2, 4.5, 5.0)
        path, drift, max_win, reds = T.grade_track(pts, [w1, w2], 2.0)
        self.assertEqual(drift, 0)
        self.assertEqual(max_win, 3)
        self.assertIn(('WINDOW', 3), reds)


class Velocity(Base):
    def test_floor_segments_by_age(self):
        opts = T.base_parser().parse_args(['report', 'x'])
        self.assertEqual(T.velocity_floor('M', 30.0, opts), 7.0)
        self.assertEqual(T.velocity_floor('M', 42.0, opts), 6.0)
        self.assertEqual(T.velocity_floor('M', 60.0, opts), 5.0)
        self.assertEqual(T.velocity_floor('M', 150.0, opts), 4.0)  # past puberty-boy
        self.assertEqual(T.velocity_floor('F', 126.0, opts), 4.0)  # past puberty-girl
        self.assertEqual(T.velocity_floor('F', 114.0, opts), 5.0)  # not yet

    def test_velocity_floor_flag_overrides_all(self):
        opts = T.base_parser().parse_args(
            ['report', 'x', '--velocity-floor', '6'])
        self.assertEqual(T.velocity_floor('M', 150.0, opts), 6.0)

    def test_weighted_identity_in_output(self):
        code, out = self.cli('velocity', os.path.join(EXAMPLES, 'xiaoman.tsv'))
        self.assertEqual(code, T.EXIT_OK)
        self.assertIn('identity:', out)


class Target(Base):
    def test_formula_boy_and_girl(self):
        opts = T.base_parser().parse_args(
            ['target', 'x', '--mom', '162', '--dad', '175'])
        mid, lo, hi = T.target_range(opts, 'M')
        self.assertAlmostEqual(mid, 175.0)
        self.assertAlmostEqual(lo, 166.5)
        mid, lo, hi = T.target_range(opts, 'F')
        self.assertAlmostEqual(mid, 162.0)

    def test_target_command_requires_parents(self):
        code, errtxt = self.cli_err('target', os.path.join(EXAMPLES, 'xiaoman.tsv'))
        self.assertEqual(code, T.EXIT_BROKEN)

    def test_target_page_projection(self):
        code, out = self.cli('target', os.path.join(EXAMPLES, 'xiaoman.tsv'),
                             '--mom', '160', '--dad', '172')
        self.assertEqual(code, T.EXIT_OK)
        self.assertIn('at age 20 on the same band', out)
        self.assertIn('inside range', out)


class Next(Base):
    def test_corridor_lines_ordered(self):
        code, out = self.cli('next', os.path.join(EXAMPLES, 'xiaoman.tsv'),
                             '--next-at', '2026-09-15')
        self.assertEqual(code, T.EXIT_OK)
        self.assertIn('stay on band 4', out)
        self.assertIn('RED LINE (2 bands down): height <  126.3 cm', out)
        stay = float(out.split('height >= ')[1].split()[0])
        red = float(out.split('height <  ')[1].split()[0])
        self.assertGreater(stay, red)

    def test_band1_child_has_no_redline_below(self):
        code, out = self.cli('next', os.path.join(EXAMPLES, 'xiaozhou.tsv'))
        self.assertEqual(code, T.EXIT_OK)
        self.assertIn('second-lowest band', out)
        self.assertNotIn('RED LINE', out)

    def test_infant_advisory_note(self):
        path = self.tmp_ledger('nxtinf', [
            ('2026-04-10', 'bei', '2025-02-10', 'F', '78.5', '')])
        code, out = self.cli('next', path)
        self.assertEqual(code, T.EXIT_OK)
        self.assertIn('advisory only', out)

    def test_default_next_is_six_months(self):
        code, out = self.cli('next', os.path.join(EXAMPLES, 'xiaoman.tsv'))
        self.assertIn('next visit 2026-09', out)


class Validate(Base):
    def test_all_samples_pass(self):
        for k in ('xiaoman', 'xiaozhou', 'xiaoshu', 'xiaodou'):
            code, out = self.cli('validate', os.path.join(EXAMPLES, '%s.tsv' % k))
            self.assertEqual(code, T.EXIT_OK, k)
            self.assertIn('all checks OK', out)

    def test_validate_reports_node_count(self):
        code, out = self.cli('validate', os.path.join(EXAMPLES, 'xiaoman.tsv'))
        self.assertIn('LMS round-trip at every node', out)
        self.assertIn('0 bad node(s)', out)


class Reproducibility(Base):
    def test_as_of_pinned_is_byte_identical(self):
        led = os.path.join(EXAMPLES, 'xiaozhou.tsv')
        args = ['report', led, '--as-of', '2019-07-02', '--mom', '170', '--dad', '180']
        _, first = self.cli(*args)
        _, second = self.cli(*args)
        self.assertEqual(first, second)

    def test_report_prints_basename_only(self):
        code, out = self.cli('report', os.path.join(EXAMPLES, 'xiaoman.tsv'))
        self.assertIn('xiaoman.tsv', out)
        self.assertNotIn(EXAMPLES, out)
        self.assertNotIn('/examples', out)

    def test_track_command_band_path(self):
        code, out = self.cli('track', os.path.join(EXAMPLES, 'xiaozhou.tsv'))
        self.assertEqual(code, T.EXIT_RED)
        self.assertIn('5 P75-P90', out)
        self.assertIn('1 P3-P10', out)
        self.assertIn('drift -4, steepest window 1', out)

    def test_no_advice_without_disclaimer(self):
        code, out = self.cli('report', os.path.join(EXAMPLES, 'xiaoman.tsv'))
        self.assertIn('Not medical advice', out)
        self.assertNotIn('endocrinologist', out)
        code, out = self.cli('report', os.path.join(EXAMPLES, 'xiaozhou.tsv'))
        self.assertIn('reason to see a pediatric endocrinologist', out)


class UnitSuspect(Base):
    def test_impossible_bmi_is_skipped_with_disclosure(self):
        path = self.tmp_ledger('unit', [
            ('2024-03-15', 'kid', '2022-03-15', 'M', '96.9', '15.0'),
            ('2025-03-15', 'kid', '2022-03-15', 'M', '104.0', '60.0')])
        code, out = self.cli('report', path)
        self.assertEqual(code, T.EXIT_OK)
        self.assertIn('unit suspect', out)


if __name__ == '__main__':
    unittest.main()
