"""Synthetic candidate evaluation, explicit assumptions and binding failures."""
from pathlib import Path
import tempfile
import unittest

from hksc.bundle import read_json, write_json
from hksc.demo import generate
from hksc.evaluation import evaluate_run, net_return, validate_policy
from hksc.research import run_research


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.first, self.second = generate(self.root / 'inputs')
        run_research(self.first, self.root / 'first')
        run_research(self.second, self.root / 'second', self.root / 'first')

    def test_no_implicit_zero_cost_or_portfolio(self):
        result = evaluate_run(self.root / 'second', self.second, self.root / 'evaluation')
        self.assertGreater(result['summary']['closed_count'], 0)
        self.assertIsNone(result['portfolio'])
        self.assertTrue(all(r['net_return'] is None for r in result['candidates']))
        self.assertIn('日线基准', (self.root / 'evaluation/report.md').read_text())

    def test_explicit_model_and_costs(self):
        policy = {'format': 'hksc-evaluation-policy/1', 'label': 'fictional test',
                  'initial_capital_hkd': 1000000, 'allocation_fraction': 0.25,
                  'commission_bps': 10, 'slippage_bps': 5}
        write_json(self.root / 'policy.json', policy)
        result = evaluate_run(self.root / 'second', self.second, self.root / 'evaluation', self.root / 'policy.json')
        self.assertEqual(result['portfolio']['net']['status'], 'SIMULATION_ONLY')
        self.assertGreater(result['portfolio']['net']['modeled_friction_hkd'], 0)
        self.assertLess(result['portfolio']['net']['total_return'], result['portfolio']['gross']['total_return'])
        self.assertTrue(all(r['net_return'] is not None for r in result['candidates'] if r['status'] == 'CLOSED'))

    def test_unbound_input_blocks(self):
        with self.assertRaisesRegex(ValueError, 'bound by the research run'):
            evaluate_run(self.root / 'second', self.first, self.root / 'bad')
        self.assertFalse((self.root / 'bad').exists())

    def test_tampered_run_blocks(self):
        (self.root / 'second/events.json').write_text('[]')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            evaluate_run(self.root / 'second', self.second, self.root / 'bad')

    def test_cost_formula(self):
        policy = {'commission_bps': 10, 'slippage_bps': 5}
        self.assertAlmostEqual(net_return(100, 110, policy), 110 * .9995 * .999 / (100 * 1.0005 * 1.001) - 1)

    def test_invalid_assumptions(self):
        policy = {'format': 'hksc-evaluation-policy/1', 'label': 'invalid',
                  'initial_capital_hkd': 1000, 'allocation_fraction': 0.25,
                  'commission_bps': -1, 'slippage_bps': 0}
        with self.assertRaises(ValueError):
            validate_policy(policy)


if __name__ == '__main__':
    unittest.main()
