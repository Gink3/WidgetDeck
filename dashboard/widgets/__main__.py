"""Inspect and validate runtime profiles without importing widget code."""
import argparse
import json
import sys
from .bundled import ROOT
from .manifest import WidgetError
from .profiles import resolve_profile


def main(argv=None):
    parser = argparse.ArgumentParser(prog='dashboard-widgets')
    subcommands = parser.add_subparsers(dest='command', required=True)
    for command in ('list', 'validate'):
        subparser = subcommands.add_parser(command)
        subparser.add_argument('--profile', default=str(ROOT / 'profiles' / 'compatibility.json'))
    migration = subcommands.add_parser('migrate', help='Plan or explicitly apply an offline SQLite migration')
    migration.add_argument('--profile', required=True)
    migration.add_argument('--widget', required=True)
    migration.add_argument('--database', required=True)
    migration.add_argument('--from-provider', required=True)
    migration.add_argument('--from-version', required=True)
    migration.add_argument('--to-version', required=True)
    migration.add_argument('--reviewed', action='store_true')
    migration.add_argument('--offline', action='store_true')
    migration.add_argument('--plan-id')
    args = parser.parse_args(argv)
    try:
        profile, selected, capabilities = resolve_profile(args.profile)
        if args.command == 'migrate':
            from .migrations import execute, plan
            manifest = next((c.manifest for c in selected if c.manifest.id == args.widget), None)
            if manifest is None:
                raise WidgetError('Migration target must be selected in the profile.')
            if args.reviewed:
                if not args.plan_id:
                    raise WidgetError('Supply the plan ID from the reviewed dry run.')
                result = execute(manifest, args.database, args.from_provider,
                    args.from_version, args.to_version, plan_id=args.plan_id, offline=args.offline)
            else:
                result = plan(manifest, args.database, args.from_provider, args.from_version, args.to_version)
            print(json.dumps(result, indent=2))
            return 0
        widgets = [dict(identity=c.manifest.identity, version=str(c.manifest.version),
                        source=c.source.to_dict(), capabilities=capabilities[c.manifest.id]) for c in selected]
        print(json.dumps(dict(profile=profile['name'], valid=True, widgets=widgets), indent=2))
        return 0
    except WidgetError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
