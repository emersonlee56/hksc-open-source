"""Review bindings, observation classes and unknown calendar ranges."""
from pathlib import Path
import tempfile
import unittest

from hksc.bundle import read_json, sha, write_json
from hksc.context import observe_context
from hksc.demo import generate
from hksc.evaluation import evaluate_run
from hksc.research import run_research
from hksc.weekly import build_weekly


class ReviewFaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.first, self.second = generate(self.root / 'inputs')
        self.run1 = run_research(self.first, self.root / 'first')
        self.run2 = run_research(self.second, self.root / 'second', self.root / 'first')

    def replace(self, path, value):
        path.unlink()
        write_json(path, value)

    def alter(self, directory, name, key, value):
        artifact = read_json(directory / name)
        artifact[key] = value
        self.replace(directory / name, artifact)
        hashes = read_json(directory / 'result_hashes.json')
        hashes[name] = sha(directory / name)
        self.replace(directory / 'result_hashes.json', hashes)

    def test_environment_cannot_relabel_synthetic_input(self):
        self.alter(self.root / 'first', 'run.json', 'synthetic', False)
        with self.assertRaisesRegex(ValueError, 'mode mismatch'):
            observe_context(self.root / 'first', self.first, self.root / 'bad')

    def test_review_sidecar_bundle_must_match(self):
        observe_context(self.root / 'second', self.second, self.root / 'context')
        self.alter(self.root / 'context', 'context.json', 'bundle_sha256', '0' * 64)
        with self.assertRaisesRegex(ValueError, 'bundle mismatch'):
            build_weekly([self.root / 'second'], self.root / 'bad', self.run2['as_of_date'],
                         self.run2['as_of_date'], contexts=[self.root / 'context'])

    def test_review_cannot_claim_forward_observation(self):
        evaluate_run(self.root / 'second', self.second, self.root / 'evaluation')
        self.alter(self.root / 'evaluation', 'evaluation.json', 'observation_mode', 'REAL_FORWARD_OBSERVATION')
        with self.assertRaisesRegex(ValueError, 'observation mode mismatch'):
            build_weekly([self.root / 'second'], self.root / 'bad', self.run2['as_of_date'],
                         self.run2['as_of_date'], evaluations=[self.root / 'evaluation'])

    def test_left_calendar_unknown_is_disclosed(self):
        result = build_weekly([self.root / 'first'], self.root / 'review', '2024-12-30', self.run1['as_of_date'])
        self.assertTrue(any('before' in item for item in result['coverage']['unknown_calendar_range']))
        self.assertFalse(result['coverage']['complete'])

    def test_prior_gap_question_gets_current_period_observation(self):
        early = build_weekly([self.root / 'first'], self.root / 'early', self.run1['as_of_date'], '2025-07-03')
        later = build_weekly([self.root / 'second'], self.root / 'later', self.run2['as_of_date'],
                             self.run2['as_of_date'], prior=self.root / 'early')
        gaps = [q for q in later['questions'] if q['topic'] == 'DATA_GAPS']
        self.assertEqual(len(gaps), 1)
        self.assertEqual(len(gaps[0]['observations']), 2)
        self.assertEqual(gaps[0]['first_proposed_date'], '2025-07-03')
        self.assertFalse(gaps[0]['observations'][-1]['current_period_has_data_gaps'])


if __name__ == '__main__':
    unittest.main()
