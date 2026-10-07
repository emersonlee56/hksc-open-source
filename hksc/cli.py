"""Offline public commands; data tools remain externally configured."""
import argparse
import json
import sys
from pathlib import Path

from .bundle import validate_bundle
from .demo import generate
from .research import run_research


def main():
    parser = argparse.ArgumentParser(description='HKSC public research-only workflow')
    commands = parser.add_subparsers(dest='command', required=True)
    demo = commands.add_parser('demo', help='Generate fictional data and two research runs')
    demo.add_argument('--output', default='outputs/demo')
    run = commands.add_parser('run', help='Research an explicitly normalized input bundle')
    run.add_argument('--input', required=True)
    run.add_argument('--output', required=True)
    run.add_argument('--prior', help='Previous public run directory for simulated continuation')
    validate = commands.add_parser('validate-input', help='Verify a normalized bundle without calculation')
    validate.add_argument('--input', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'demo':
            root = Path(args.output)
            if root.exists():
                raise ValueError('Demo output already exists; use a new output directory')
            bundles = generate(root / 'inputs')
            first = root / 'signal'
            run_research(bundles[0], first)
            result = run_research(bundles[1], root / 'followup', prior=first)
        elif args.command == 'run':
            result = run_research(args.input, args.output, prior=args.prior)
        else:
            _, manifest, _ = validate_bundle(args.input)
            result = {'status': 'INPUT_VALIDATED', 'as_of_date': manifest['as_of_date'],
                      'synthetic': manifest['synthetic'], 'production_acceptance': False}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
