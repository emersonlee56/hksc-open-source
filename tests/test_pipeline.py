"""Complete local workflow and isolated sidecar failure behavior."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hksc.bundle import read_json
from hksc.delivery import load_delivery, load_run
from hksc.demo import generate
from hksc.pipeline import daily, full_demo
from hksc.research import run_research
from hksc.weekly import build_weekly


class PipelineTests(unittest.TestCase):
    def test_sidecar_failure_does_not_repeat_or_block_core(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, _ = generate(root / 'inputs')
            with patch('hksc.pipeline.observe_context', side_effect=ValueError('fixture context unavailable')):
                result = daily(first, root / 'daily')
            self.assertEqual(result['status'], 'COMPLETE_WITH_DEGRADATION')
            self.assertEqual(result['stages']['research']['status'], 'COMPLETE')
            self.assertEqual(result['stages']['context']['status'], 'DEGRADED')
            self.assertFalse(result['repair_authorized'])
            load_run(root / 'daily')
            load_delivery(root / 'daily')

    def test_bad_core_has_blocked_receipt_and_cannot_continue(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, _ = generate(root / 'inputs')
            (first / 'bars.csv').write_text('invalid')
            result = daily(first, root / 'daily')
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertNotIn('evaluation', result['stages'])
            with self.assertRaises(ValueError):
                load_run(root / 'daily')
            self.assertFalse((root / 'daily/research/run.json').exists())

    def test_complete_demo_and_review_questions_reach_next_day(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'demo'
            result = full_demo(root)
            self.assertEqual(result['status'], 'COMPLETE')
            self.assertEqual(len(result['days']), 11)
            self.assertGreaterEqual(len(result['reviews']), 2)
            last = root / result['last_daily']
            agenda = read_json(last / 'research_agenda.json')
            self.assertTrue(agenda['questions'])
            self.assertFalse(agenda['changes_strategy'])
            final_review = read_json(root / result['last_review'] / 'weekly.json')
            self.assertTrue(any(len(q['observations']) >= 2 for q in final_review['questions']))
            load_delivery(root)
            self.assertIn('日常研究', (root / 'index.html').read_text())

    def test_unexpected_sidecar_exception_is_degraded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, _ = generate(root / 'inputs')
            with patch('hksc.pipeline.observe_context', side_effect=RuntimeError('unexpected sidecar failure')):
                result = daily(first, root / 'daily')
            self.assertEqual(result['status'], 'COMPLETE_WITH_DEGRADATION')
            self.assertIn('合成数据回放', (root / 'daily/report.md').read_text())

    def test_malformed_manifest_has_blocked_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, _ = generate(root / 'inputs')
            (first / 'bundle.json').write_text('[]')
            result = daily(first, root / 'daily')
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertEqual(read_json(root / 'daily/daily_receipt.json')['status'], 'BLOCKED')

    def test_finalization_failure_cannot_leave_complete_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, _ = generate(root / 'inputs')
            with patch('hksc.pipeline.seal_directory', side_effect=OSError('fixture sealing failure')):
                result = daily(first, root / 'daily')
            self.assertEqual(result['status'], 'BLOCKED')
            self.assertEqual(read_json(root / 'daily/daily_receipt.json')['status'], 'BLOCKED')
            with self.assertRaises(ValueError):
                load_run(root / 'daily')

    def test_parent_cannot_omit_corrupted_child_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, _ = generate(root / 'inputs')
            daily(first, root / 'daily')
            manifest = root / 'daily/result_hashes.json'
            hashes = read_json(manifest)
            hashes.pop('context/report.html')
            manifest.write_text(__import__('json').dumps(hashes))
            (root / 'daily/context/report.html').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'complete file set'):
                load_delivery(root / 'daily')

    def test_partial_sidecar_is_not_reused_by_demo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'demo'
            def partial(run, input_directory, output):
                path = Path(output)
                path.mkdir(parents=True)
                (path / 'context.json').write_text('{}')
                raise OSError('fixture partial context')
            with patch('hksc.pipeline.observe_context', side_effect=partial):
                result = full_demo(root)
            self.assertEqual(result['status'], 'COMPLETE_WITH_DEGRADATION')
            self.assertEqual(len(result['days']), 11)

    def test_degraded_evaluation_has_no_dead_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'demo'
            with patch('hksc.pipeline.evaluate_run', side_effect=ValueError('fixture missing evaluation')):
                result = full_demo(root)
            self.assertEqual(result['status'], 'COMPLETE_WITH_DEGRADATION')
            self.assertNotIn('/evaluation/report.html', (root / 'index.html').read_text())

    def test_interrupted_sidecar_manifest_preserves_bytes_and_continuation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first, second = generate(root / 'inputs')
            fragment = b'{"context.json":'
            def interrupted(run, input_directory, output):
                path = Path(output)
                path.mkdir(parents=True)
                (path / 'context.json').write_text('{}')
                (path / 'result_hashes.json').write_bytes(fragment)
                raise OSError('fixture interrupted manifest')
            with patch('hksc.pipeline.observe_context', side_effect=interrupted):
                result = daily(first, root / 'first')
            self.assertEqual(result['status'], 'COMPLETE_WITH_DEGRADATION')
            evidence = root / 'first' / result['stages']['context']['failure_evidence_directory']
            self.assertEqual((evidence / 'result_hashes.json.incomplete').read_bytes(), fragment)
            self.assertEqual((evidence / 'context.json').read_text(), '{}')
            self.assertFalse((root / 'first/context').exists())
            load_delivery(root / 'first')
            load_run(root / 'first')
            resumed = daily(second, root / 'second', root / 'first')
            self.assertEqual(resumed['status'], 'COMPLETE')
            (evidence / 'context.json').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                load_delivery(root / 'first')

    def test_demo_continues_with_interrupted_evaluation_manifests(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'demo'
            def interrupted(run, input_directory, output, policy_path):
                path = Path(output)
                path.mkdir(parents=True)
                (path / 'result_hashes.json').write_text('{')
                raise OSError('fixture evaluation write interruption')
            with patch('hksc.pipeline.evaluate_run', side_effect=interrupted):
                result = full_demo(root)
            self.assertEqual(result['status'], 'COMPLETE_WITH_DEGRADATION')
            self.assertEqual(len(result['days']), 11)
            self.assertEqual(len(result['reviews']), 3)
            load_delivery(root)
            self.assertNotIn('/evaluation/report.html', (root / 'index.html').read_text())

    def test_failed_middle_review_keeps_latest_valid_agenda_and_daily_chain(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'demo'
            attempts = []
            def fail_second(*args, **kwargs):
                attempts.append(args[3])
                if len(attempts) == 2:
                    raise RuntimeError('fixture weekly unavailable')
                return build_weekly(*args, **kwargs)
            with patch('hksc.pipeline.build_weekly', side_effect=fail_second), \
                 patch('hksc.pipeline.run_research', wraps=run_research) as core:
                result = full_demo(root)
            self.assertEqual(core.call_count, 11)
            self.assertEqual(attempts, ['2025-07-04', '2025-07-11', '2025-07-16'])
            self.assertEqual(result['status'], 'COMPLETE_WITH_DEGRADATION')
            self.assertEqual(len(result['days']), 11)
            self.assertEqual([r['status'] for r in result['reviews']], ['COMPLETE', 'DEGRADED', 'COMPLETE'])
            self.assertEqual(result['last_review'], 'weekly/2025-07-16')
            self.assertNotIn('weekly/2025-07-11/report.html', (root / 'index.html').read_text())
            first_questions = read_json(root / 'weekly/2025-07-04/weekly.json')['questions']
            agenda = read_json(root / 'daily/2025-07-14/research_agenda.json')
            self.assertEqual(agenda['questions'], first_questions)
            load_delivery(root)

    def test_interrupted_weekly_manifests_preserve_evidence_without_retries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'demo'
            def interrupted(*args, **kwargs):
                path = Path(args[1])
                path.mkdir(parents=True)
                (path / 'report.md').write_text('fixture partial weekly')
                (path / 'result_hashes.json').write_text('{')
                raise OSError('fixture weekly manifest interrupted')
            with patch('hksc.pipeline.build_weekly', side_effect=interrupted) as weekly, \
                 patch('hksc.pipeline.run_research', wraps=run_research) as core:
                result = full_demo(root)
            self.assertEqual(core.call_count, 11)
            self.assertEqual(weekly.call_count, 3)
            self.assertEqual(result['status'], 'COMPLETE_WITH_DEGRADATION')
            self.assertIsNone(result['last_review'])
            self.assertTrue(all(r['status'] == 'DEGRADED' for r in result['reviews']))
            for review in result['reviews']:
                evidence = root / review['failure_evidence_directory']
                self.assertEqual((evidence / 'result_hashes.json.incomplete').read_text(), '{')
                self.assertEqual((evidence / 'report.md').read_text(), 'fixture partial weekly')
                self.assertNotIn('weekly/' + review['end_date'] + '/report.html', (root / 'index.html').read_text())
            self.assertTrue(all(d['stages']['agenda']['status'] == 'NOT_PROVIDED' for d in result['days']))
            load_delivery(root)


if __name__ == '__main__':
    unittest.main()
