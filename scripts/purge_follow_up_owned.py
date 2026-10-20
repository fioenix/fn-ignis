"""Private cleanup-only command; real UTC only, no scheduler, config, DB or provider imports."""
import argparse
import json
from pathlib import Path
from ignis.infrastructure.follow_up_cleanup import (
    CleanupRefused, preflight_cleanup, purge_confirmed_cleanup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--preflight', action='store_true')
    mode.add_argument('--action-confirmation', type=Path)
    args = parser.parse_args()
    try:
        if args.preflight:
            result = preflight_cleanup(args.manifest, args.sha256)
        else:
            result = purge_confirmed_cleanup(args.manifest, args.sha256,
                json.loads(args.action_confirmation.read_text()))
    except (CleanupRefused, OSError, ValueError, KeyError, TypeError):
        print('CLEANUP_REFUSED')
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
