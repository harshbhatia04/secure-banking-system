"""Command-line entry point for the Weeks 1-3 banking prototype."""
import argparse
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import json
import sqlite3
import sys

from client_sim import run_simulation
from concurrency_manager import deadlock_demo, race_demo
from database import Database, MAX_MONEY
from transaction_manager import BankingError, TransactionManager


def parse_money(value):
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount <= 0 or amount > Decimal(MAX_MONEY) / 100:
            raise ValueError
        paise = amount * 100
        if paise != paise.to_integral_value():
            raise ValueError
        return int(paise)
    except (InvalidOperation, ValueError):
        raise argparse.ArgumentTypeError('Enter a positive rupee amount with at most two decimal places') from None


def build_parser():
    parser = argparse.ArgumentParser(description='Concurrent banking prototype. CLI amounts are in rupees.')
    parser.add_argument('--db', default='data/banking.db', help='SQLite database path')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'accounts', 'history', 'failures', 'reconcile', 'deadlock-demo', 'race-demo'):
        commands.add_parser(name)
    for name in ('deposit', 'withdraw', 'transfer'):
        command = commands.add_parser(name)
        command.add_argument('account', type=int)
        if name == 'transfer':
            command.add_argument('destination', type=int)
            command.add_argument('--fail-after-debit', action='store_true')
        command.add_argument('amount', type=parse_money)
        command.add_argument('--request-key')
    balance = commands.add_parser('balance')
    balance.add_argument('account', type=int)
    for name in ('freeze', 'unfreeze'):
        commands.add_parser(name).add_argument('account', type=int)
    statement = commands.add_parser('statement')
    statement.add_argument('account', type=int)
    statement.add_argument('--limit', type=int, default=10)
    simulator = commands.add_parser('simulate')
    simulator.add_argument('--workers', type=int, default=10)
    simulator.add_argument('--operations', type=int, default=100)
    simulator.add_argument('--seed', type=int, default=42)
    simulator.add_argument('--mode', choices=('mixed', 'transfer'), default='mixed')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == 'deadlock-demo':
            result = deadlock_demo()
            exit_code = 0 if result['workers_finished'] and result['circular_wait_observed'] else 1
        elif args.command == 'race-demo':
            result = race_demo()
            exit_code = 0 if result['with_lock'] == result['expected'] and result['without_lock'] != result['expected'] else 1
        else:
            database = Database(args.db)
            if args.command == 'init':
                database.initialize()
                database.seed()
                result = {'database': str(database.path), 'accounts': database.accounts(), 'note': 'Existing balances preserved'}
            else:
                if not database.path.is_file():
                    raise BankingError('Database does not exist. Run the init command first.')
                manager = TransactionManager(database)
                if args.command == 'balance':
                    result = database.account(args.account)
                    if result is None:
                        raise BankingError(f'Account {args.account} does not exist')
                elif args.command == 'statement':
                    result = database.statement(args.account, args.limit)
                elif args.command in ('freeze', 'unfreeze'):
                    result = database.set_status(args.account, 'frozen' if args.command == 'freeze' else 'active')
                elif args.command in ('accounts', 'history', 'failures', 'reconcile'):
                    result = getattr(database, args.command)()
                elif args.command == 'simulate':
                    result = run_simulation(manager, args.workers, args.operations, args.seed, args.mode)
                elif args.command == 'transfer':
                    result = asdict(manager.transfer(args.account, args.destination, args.amount,
                                    request_key=args.request_key, simulate_failure=args.fail_after_debit))
                else:
                    result = asdict(getattr(manager, args.command)(args.account, args.amount, request_key=args.request_key))
            exit_code = 0
            if args.command == 'simulate':
                exit_code = 0 if (result['accounting_correct'] and result['balances_nonnegative'] and
                                  result['all_operations_accounted_for'] and not result['unexpected_errors']) else 1
            if args.command == 'reconcile':
                exit_code = 0 if result['consistent'] else 1
        print(json.dumps(result, indent=2))
        return exit_code
    except (BankingError, ValueError, RuntimeError, sqlite3.Error, OSError) as exc:
        print(json.dumps({'error': str(exc), 'audit_warning': getattr(exc, 'audit_warning', None)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
