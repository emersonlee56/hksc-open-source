"""Synthetic unit/integration and fault injection, never live-source acceptance."""
from pathlib import Path
import tempfile
import unittest

from hksc.bundle import read_json, sha, validate_bundle, write_json
from hksc.demo import generate
from hksc.research import run_research
from hksc_engine.hkm1_lifecycle import evaluate_candidate_open
from hksc_engine.hkm1_scanner import load_daily_series


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.signal, self.followup = generate(self.root / 'inputs')

    def rewrite(self, path, value):
        path.unlink()
        write_json(path, value)

    def test_synthetic_scan_and_continuation(self):
        first = self.root / 'first'
        result = run_research(self.signal, first)
        self.assertEqual(result['open_candidate_count'], 3)
        scan = read_json(first / 'scan.json')
        self.assertEqual(scan['summary']['eligible_count'], 140)
        self.assertEqual(scan['summary']['watch_capacity_count'], 2)
        later = self.root / 'later'
        result = run_research(self.followup, later, first)
        self.assertLessEqual(result['open_candidate_count'], 3)
        self.assertFalse(result['is_actual_trade'])
        self.assertTrue(result['synthetic'])
        self.assertTrue(read_json(later / 'events.json'))
        states = read_json(later / 'lifecycle.json')
        self.assertIn('TARGET_HIT', {s['lifecycle_status'] for s in states})

    def test_deterministic_replays(self):
        run_research(self.signal, self.root / 'one')
        run_research(self.signal, self.root / 'two')
        self.assertEqual(read_json(self.root / 'one/result_hashes.json'),
                         read_json(self.root / 'two/result_hashes.json'))

    def test_no_output_overwrite(self):
        run_research(self.signal, self.root / 'run')
        with self.assertRaises(ValueError):
            run_research(self.signal, self.root / 'run')

    def test_bad_input_hash_blocks(self):
        with (self.signal / 'bars.csv').open('a') as handle:
            handle.write('\n')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            validate_bundle(self.signal)

    def test_future_row_blocks_even_with_new_hash(self):
        bars = self.signal / 'bars.csv'
        with bars.open('a') as handle:
            handle.write('DEMO.00001,2099-01-01,10,11,9,10,1000,100\n')
        manifest = read_json(self.signal / 'bundle.json')
        manifest['files']['bars.csv'] = sha(bars)
        self.rewrite(self.signal / 'bundle.json', manifest)
        with self.assertRaisesRegex(ValueError, 'future'):
            validate_bundle(self.signal)

    def test_old_event_tampering_blocks(self):
        run_research(self.signal, self.root / 'run')
        self.rewrite(self.root / 'run/events.json', [{'event_id': 'invented'}])
        with self.assertRaisesRegex(ValueError, 'Prior artifact hash'):
            run_research(self.followup, self.root / 'next', self.root / 'run')

    def test_historical_restatement_blocks(self):
        run_research(self.signal, self.root / 'run')
        bars = self.followup / 'bars.csv'
        text = bars.read_text()
        lines = text.splitlines()
        row = lines[1].split(',')
        row[6] = str(float(row[6]) + 1)
        lines[1] = ','.join(row)
        bars.write_text('\n'.join(lines) + '\n')
        manifest = read_json(self.followup / 'bundle.json')
        manifest['files']['bars.csv'] = sha(bars)
        self.rewrite(self.followup / 'bundle.json', manifest)
        with self.assertRaisesRegex(ValueError, 'Historical prices changed'):
            run_research(self.followup, self.root / 'next', self.root / 'run')

    def test_missing_open_evidence_stays_blocked(self):
        run_research(self.signal, self.root / 'run')
        candidate = read_json(self.root / 'run/candidates.json')[0]
        series = load_daily_series(self.signal / 'bars.csv')[candidate['symbol']]
        state = evaluate_candidate_open(candidate, series, None)
        self.assertEqual(state['actionability_state'], 'DATA_BLOCKED')


if __name__ == '__main__':
    unittest.main()
