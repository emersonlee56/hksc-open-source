"""Independent-review counterexamples as synthetic regression tests."""
import csv
from pathlib import Path
import tempfile
import unittest

from hksc.bundle import read_json, sha, write_json
from hksc.demo import generate
from hksc.evaluation import candidate_observations, evaluate_run
from hksc.research import run_research


class IntegrityFaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.first, self.second = generate(self.root / 'inputs')
        run_research(self.first, self.root / 'first')

    def replace_json(self, path, value):
        if path.exists():
            path.unlink()
        write_json(path, value)

    def reseal(self, root, manifest_name, name):
        manifest = read_json(root / manifest_name)
        if manifest_name == 'bundle.json':
            manifest['files'][name] = sha(root / name)
        else:
            manifest[name] = sha(root / name)
        self.replace_json(root / manifest_name, manifest)

    def edit_csv(self, path, transform):
        with path.open(newline='') as handle:
            reader = csv.DictReader(handle)
            fields, rows = reader.fieldnames, list(reader)
        rows = transform(rows)
        with path.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_missing_required_delivery_cannot_be_hidden_by_resealing(self):
        hashes = read_json(self.root / 'first/result_hashes.json')
        for name in ('daily_plan.json', 'scan.json', 'coverage.json', 'report.md', 'report.html'):
            hashes.pop(name)
            (self.root / 'first' / name).unlink()
        self.replace_json(self.root / 'first/result_hashes.json', hashes)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            run_research(self.second, self.root / 'bad', self.root / 'first')

    def test_historical_volume_changes_block(self):
        def change(rows):
            rows[0]['volume'] = str(float(rows[0]['volume']) + 1)
            return rows
        self.edit_csv(self.second / 'bars.csv', change)
        self.reseal(self.second, 'bundle.json', 'bars.csv')
        with self.assertRaisesRegex(ValueError, 'Historical prices changed'):
            run_research(self.second, self.root / 'bad', self.root / 'first')

    def test_historical_benchmark_changes_block(self):
        def change(rows):
            rows[0]['amount'] = str(float(rows[0]['amount']) + 1)
            return rows
        self.edit_csv(self.second / 'benchmark.csv', change)
        self.reseal(self.second, 'bundle.json', 'benchmark.csv')
        with self.assertRaisesRegex(ValueError, 'Historical prices changed'):
            run_research(self.second, self.root / 'bad', self.root / 'first')

    def test_between_snapshot_exits_are_reported(self):
        run_research(self.second, self.root / 'second', self.root / 'first')
        plan = read_json(self.root / 'second/daily_plan.json')
        exited = [i for i in plan['items'] if i['research_action'] == 'REVIEW_RECORDED_EXIT']
        self.assertTrue(exited)
        report = (self.root / 'second/report.md').read_text()
        self.assertTrue(any(e['observed_trade_date'] != plan['as_of_date']
                            for i in exited for e in i['events_since_prior']))
        for item in exited:
            self.assertIn(item['symbol'], report)

    def test_scan_gaps_are_disclosed(self):
        day = read_json(self.first / 'bundle.json')['as_of_date']
        symbols = {f'DEMO.{i:05d}' for i in range(127, 141)}
        self.edit_csv(self.first / 'bars.csv', lambda rows: [r for r in rows if not (r['date'] == day and r['symbol'] in symbols)])
        self.reseal(self.first, 'bundle.json', 'bars.csv')
        run_research(self.first, self.root / 'gaps')
        plan = read_json(self.root / 'gaps/daily_plan.json')
        self.assertEqual(plan['scan_coverage']['blocked_count'], 14)
        self.assertEqual(len(plan['scan_data_gaps']), 14)
        self.assertIn('DEMO.00140', (self.root / 'gaps/report.md').read_text())

    def test_invalid_background_degrades_without_blocking_mainline(self):
        day = read_json(self.first / 'bundle.json')['as_of_date']
        facts = [{'provider': 'synthetic', 'published_at': day + 'T17:00:00+08:00',
                  'retrieved_at': day + 'T16:00:00+08:00', 'evidence_reference': 'fictional'}]
        self.replace_json(self.first / 'gildata_facts.json', facts)
        self.reseal(self.first, 'bundle.json', 'gildata_facts.json')
        result = run_research(self.first, self.root / 'degraded')
        self.assertEqual(result['degradations'][0]['module'], 'background')
        self.assertEqual(read_json(self.root / 'degraded/daily_plan.json')['background_facts'], [])

    def test_event_registry_contradiction_blocks_evaluation(self):
        run_research(self.second, self.root / 'second', self.root / 'first')
        self.replace_json(self.root / 'second/events.json', [])
        self.reseal(self.root / 'second', 'result_hashes.json', 'events.json')
        with self.assertRaisesRegex(ValueError, 'events disagree'):
            evaluate_run(self.root / 'second', self.second, self.root / 'bad')

    def test_duplicate_candidates_block_evaluation(self):
        run_research(self.second, self.root / 'second', self.root / 'first')
        candidates = read_json(self.root / 'second/candidates.json')
        candidates.append(candidates[0])
        self.replace_json(self.root / 'second/candidates.json', candidates)
        self.reseal(self.root / 'second', 'result_hashes.json', 'candidates.json')
        with self.assertRaisesRegex(ValueError, 'unique'):
            evaluate_run(self.root / 'second', self.second, self.root / 'bad')

    def test_noncalendar_entry_blocks_default_evaluation(self):
        run_research(self.second, self.root / 'second', self.root / 'first')
        run = read_json(self.root / 'second/run.json')
        states = read_json(self.root / 'second/lifecycle.json')
        candidates = read_json(self.root / 'second/candidates.json')
        for state in states:
            for event in state['events']:
                if event['event_type'] == 'SIMULATED_ENTRY':
                    event['observed_trade_date'] = '2025-07-05'
                    with self.assertRaisesRegex(ValueError, 'trading window'):
                        candidate_observations(run, candidates, states, {}, {}, None)
                    return
        self.fail('Fixture must contain an entry')

    def test_missing_entry_history_is_incomplete_not_normal_not_entered(self):
        candidate = read_json(self.root / 'first/candidates.json')[0]
        self.edit_csv(self.second / 'bars.csv', lambda rows: [r for r in rows if not (
            r['symbol'] == candidate['symbol'] and r['date'] == candidate['valid_for_trade_date'])])
        self.reseal(self.second, 'bundle.json', 'bars.csv')
        run_research(self.second, self.root / 'second', self.root / 'first')
        evaluation = evaluate_run(self.root / 'second', self.second, self.root / 'evaluation')
        self.assertGreater(evaluation['summary']['incomplete_count'], 0)
        self.assertIn('strategy_version', evaluation)


if __name__ == '__main__':
    unittest.main()
