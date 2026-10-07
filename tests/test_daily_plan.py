"""Synthetic daily-plan behavior and prior-artifact fault injection."""
from pathlib import Path
import tempfile
import unittest

from hksc.bundle import read_json
from hksc.demo import generate
from hksc.plan import build_plan, document_html, render_plan
from hksc.research import run_research


class DailyPlanTests(unittest.TestCase):
    def test_continuous_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, second = generate(root / 'inputs')
            run_research(first, root / 'first')
            run_research(second, root / 'second', root / 'first')
            plan = read_json(root / 'second/daily_plan.json')
            self.assertEqual(plan['observation_mode'], 'SYNTHETIC_REPLAY')
            self.assertFalse(plan['is_actual_trade'])
            self.assertTrue(any(i['change'] == 'UPDATED' for i in plan['items']))
            self.assertIn('今日关注', (root / 'second/report.md').read_text())
            self.assertIn('viewport', (root / 'second/report.html').read_text())

    def test_report_tampering_blocks_prior(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, second = generate(root / 'inputs')
            run_research(first, root / 'first')
            (root / 'first/report.md').write_text('altered')
            with self.assertRaisesRegex(ValueError, 'Prior artifact hash mismatch'):
                run_research(second, root / 'second', root / 'first')

    def test_empty_day_has_no_recommendation(self):
        run = {'as_of_date': '2025-07-02', 'synthetic': True, 'bundle_sha256': 'demo',
               'prior_result_hashes_sha256': None, 'new_candidate_count': 0,
               'open_candidate_count': 0, 'source_records': {}}
        scan = {'valid_for_trade_date': '2025-07-03', 'strategy_version': 'demo',
                'summary': {'trade_count': 0, 'watch_capacity_count': 0}}
        plan = build_plan(run, scan, [], [])
        self.assertEqual(plan['items'], [])
        plan['source_records'] = {k: {'provider': 'synthetic', 'access_tool': 'demo',
                                     'source_timestamp': 'demo', 'retrieved_at': 'demo'}
                                  for k in ('bars', 'benchmark')}
        self.assertIn('不新增推荐', render_plan(plan))

    def test_source_markup_is_escaped(self):
        self.assertNotIn('<script>', document_html('demo', '# Demo\n<script>alert(1)</script>'))


if __name__ == '__main__':
    unittest.main()
