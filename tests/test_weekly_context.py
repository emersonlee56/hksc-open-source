"""Read-only environment and incomplete-period review scenarios."""
from pathlib import Path
import tempfile
import unittest

from hksc.bundle import read_json
from hksc.context import observe_context
from hksc.demo import generate
from hksc.evaluation import evaluate_run
from hksc.research import run_research
from hksc.weekly import build_weekly


class WeeklyContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.first, self.second = generate(self.root / 'inputs')
        self.run1 = run_research(self.first, self.root / 'first')
        self.run2 = run_research(self.second, self.root / 'second', self.root / 'first')

    def test_read_only_environment(self):
        hashes = read_json(self.root / 'second/result_hashes.json')
        result = observe_context(self.root / 'second', self.second, self.root / 'context')
        self.assertEqual(result['pool_breadth']['observed_count'], 140)
        self.assertFalse(result['strategy_input'])
        self.assertEqual(hashes, read_json(self.root / 'second/result_hashes.json'))

    def test_missing_days_and_no_fabricated_evaluation(self):
        result = build_weekly([self.root / 'first', self.root / 'second'], self.root / 'review',
                              self.run1['as_of_date'], self.run2['as_of_date'])
        self.assertTrue(result['coverage']['missing_dates'])
        self.assertFalse(result['coverage']['complete'])
        self.assertIsNone(result['evaluation_as_of'])
        self.assertFalse(result['automatic_rule_changes'])

    def test_linked_results_and_questions_continue(self):
        evaluate_run(self.root / 'second', self.second, self.root / 'evaluation')
        observe_context(self.root / 'second', self.second, self.root / 'context')
        early = build_weekly([self.root / 'first'], self.root / 'early',
                             self.run1['as_of_date'], self.run1['as_of_date'])
        start = read_json(self.first / 'calendar.json')['next_trade_date']
        later = build_weekly([self.root / 'second'], self.root / 'later', start,
                             self.run2['as_of_date'], [self.root / 'evaluation'],
                             [self.root / 'context'], self.root / 'early')
        first_questions = {q['question_id']: q for q in early['questions']}
        for question in later['questions']:
            if question['question_id'] in first_questions:
                self.assertEqual(question['first_proposed_date'], first_questions[question['question_id']]['first_proposed_date'])
                self.assertEqual(len(question['observations']), 2)
        self.assertIsNotNone(later['evaluation_as_of'])
        self.assertTrue(later['closed_candidates'])

    def test_unbound_sidecar_blocks(self):
        observe_context(self.root / 'first', self.first, self.root / 'context')
        with self.assertRaisesRegex(ValueError, 'not bound'):
            build_weekly([self.root / 'second'], self.root / 'bad', self.run2['as_of_date'],
                         self.run2['as_of_date'], contexts=[self.root / 'context'])

    def test_duplicate_dates_block(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            build_weekly([self.root / 'first'] * 2, self.root / 'bad',
                         self.run1['as_of_date'], self.run1['as_of_date'])

    def test_unknown_end_calendar_is_disclosed(self):
        result = build_weekly([self.root / 'first'], self.root / 'review', self.run1['as_of_date'], '2025-07-30')
        self.assertIsNotNone(result['coverage']['unknown_calendar_range'])
        self.assertFalse(result['coverage']['complete'])


if __name__ == '__main__':
    unittest.main()
