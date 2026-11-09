#!/usr/bin/env python3
"""Explicit local taxonomy projection and verification; no application startup."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

# Operator scripts run from a matching checkout, including with a non-editable installed wheel.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from ignis.infrastructure.migration import taxonomy_retirement as retirement  # noqa: E402


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise retirement.RetirementError('INVALID_INPUT', 2)


def _arguments(argv):
    parser = _Parser(description=__doc__)
    parser.add_argument('operation', choices=('project', 'apply', 'verify'))
    backend = parser.add_mutually_exclusive_group(required=True)
    backend.add_argument('--sqlite')
    backend.add_argument('--postgres-service')
    parser.add_argument('--baseline')
    args = parser.parse_args(argv)
    if args.sqlite == '' or args.postgres_service == '':
        raise retirement.RetirementError('INVALID_INPUT', 2)
    if args.postgres_service and not re.fullmatch(r'[A-Za-z0-9_.-]+', args.postgres_service):
        raise retirement.RetirementError('INVALID_INPUT', 2)
    if (args.operation in ('apply', 'verify')) != bool(args.baseline):
        raise retirement.RetirementError('INVALID_INPUT', 2)
    return args


def main(argv=None):
    connection = None
    try:
        args = _arguments(argv)
        baseline = None
        if args.baseline:
            try:
                baseline = json.loads(Path(args.baseline).read_text())
            except (OSError, ValueError):
                raise retirement.RetirementError('INVALID_INPUT', 2) from None
        if args.sqlite:
            path = Path(args.sqlite)
            if not path.is_file():
                raise retirement.RetirementError('INVALID_INPUT', 2)
            mode = 'rw' if args.operation == 'apply' else 'ro'
            connection = sqlite3.connect(path.resolve().as_uri() + '?mode=' + mode, uri=True)
            if args.operation != 'apply':
                connection.execute('PRAGMA query_only = ON')
            backend, identity = 'sqlite', retirement.sqlite_identity(path)
        else:
            import psycopg
            connection = psycopg.connect(service=args.postgres_service)
            if args.operation != 'apply':
                connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            backend, identity = 'postgres', retirement.postgres_identity(connection)
            if args.operation == 'apply':
                connection.rollback()
        if args.operation == 'project':
            result = retirement.project(connection, backend, identity)
        else:
            operation = retirement.apply if args.operation == 'apply' else retirement.verify
            result = operation(connection, backend, identity, baseline)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0
    except retirement.RetirementError as error:
        print(json.dumps({'status': 'REFUSED', 'reason': error.reason}))
        return error.exit_code
    except Exception:
        # Driver exceptions can contain a DSN, SQL row, personal data or a password.
        print(json.dumps({'status': 'REFUSED', 'reason': 'CANNOT_RUN'}))
        return 2
    finally:
        if connection is not None:
            connection.close()


if __name__ == '__main__':
    raise SystemExit(main())
