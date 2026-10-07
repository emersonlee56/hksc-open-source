"""Offline public commands; data tools remain externally configured."""
import argparse
import json
import sys
from pathlib import Path

from .bundle import background_facts, validate_bundle
from .demo import generate
from .research import run_research
from .context import observe_context
from .delivery import load_delivery, load_run
from .evaluation import evaluate_run
from .pipeline import daily, full_demo
from .weekly import build_weekly


def main():
    parser = argparse.ArgumentParser(description='HKSC public research-only workflow')
    commands = parser.add_subparsers(dest='command', required=True)
    demo = commands.add_parser('demo', help='Generate a fictional continuous research and review workflow')
    demo.add_argument('--output', default='outputs/demo')
    demo.add_argument('--quick', action='store_true', help='Only generate two scanner/lifecycle snapshots')
    run = commands.add_parser('run', help='Research an explicitly normalized input bundle')
    run.add_argument('--input', required=True)
    run.add_argument('--output', required=True)
    run.add_argument('--prior', help='Previous public run directory for simulated continuation')
    validate = commands.add_parser('validate-input', help='Verify a normalized bundle without calculation')
    validate.add_argument('--input', required=True)
    daily_cmd = commands.add_parser('daily', help='Run daily research with independent evaluation and context')
    daily_cmd.add_argument('--input', required=True)
    daily_cmd.add_argument('--output', required=True)
    daily_cmd.add_argument('--prior')
    daily_cmd.add_argument('--policy', help='Explicit hypothetical portfolio and friction assumptions')
    daily_cmd.add_argument('--prior-review', help='Previous non-overlapping review, for research questions only')
    evaluation = commands.add_parser('evaluate', help='Evaluate a hash-bound research run')
    evaluation.add_argument('--run', required=True)
    evaluation.add_argument('--input', required=True)
    evaluation.add_argument('--output', required=True)
    evaluation.add_argument('--policy')
    context = commands.add_parser('context', help='Read-only benchmark and research-pool environment')
    context.add_argument('--run', required=True)
    context.add_argument('--input', required=True)
    context.add_argument('--output', required=True)
    weekly = commands.add_parser('weekly', help='Review an explicit research period')
    weekly.add_argument('--runs', nargs='+', required=True)
    weekly.add_argument('--start', required=True)
    weekly.add_argument('--end', required=True)
    weekly.add_argument('--output', required=True)
    weekly.add_argument('--evaluations', nargs='*', default=[])
    weekly.add_argument('--contexts', nargs='*', default=[])
    weekly.add_argument('--prior-review')
    check = commands.add_parser('check-output', help='Verify delivery hashes and research-state invariants')
    check.add_argument('--input', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'demo':
            root = Path(args.output)
            if root.exists():
                raise ValueError('Demo output already exists; use a new output directory')
            if args.quick:
                bundles = generate(root / 'inputs')
                first = root / 'signal'
                run_research(bundles[0], first)
                result = run_research(bundles[1], root / 'followup', prior=first)
            else:
                result = full_demo(root)
        elif args.command == 'run':
            result = run_research(args.input, args.output, prior=load_run(args.prior)[0] if args.prior else None)
        elif args.command == 'daily':
            result = daily(args.input, args.output, args.prior, args.policy, args.prior_review)
        elif args.command == 'evaluate':
            result = evaluate_run(args.run, args.input, args.output, args.policy)
        elif args.command == 'context':
            result = observe_context(args.run, args.input, args.output)
        elif args.command == 'weekly':
            result = build_weekly(args.runs, args.output, args.start, args.end,
                                  args.evaluations, args.contexts, args.prior_review)
        elif args.command == 'check-output':
            root, hashes = load_delivery(args.input)
            if (root / 'run.json').exists() or (root / 'daily_receipt.json').exists():
                load_run(root)
            result = {'status': 'OUTPUT_VALIDATED', 'artifact_count': len(hashes), 'production_acceptance': False}
        else:
            input_root, manifest, _ = validate_bundle(args.input)
            result = {'status': 'INPUT_VALIDATED', 'as_of_date': manifest['as_of_date'],
                      'synthetic': manifest['synthetic'], 'production_acceptance': False}
            try:
                facts = background_facts(input_root, manifest)
                result['background'] = {'status': 'VALIDATED' if facts else 'NOT_PROVIDED'}
            except (ValueError, KeyError, TypeError, OSError) as exc:
                result['background'] = {'status': 'DEGRADED', 'reason': str(exc)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get('status') == 'BLOCKED' else 0
    except Exception as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
