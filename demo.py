"""Run assessed demonstrations in temporary databases and save actual results."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import tempfile

from client_sim import run_simulation
from concurrency_manager import deadlock_demo, race_demo
from database import Database
from transaction_manager import BankingError, TransactionManager


def main():
    report = {'generated_at_utc': datetime.now(timezone.utc).isoformat(),
              'python': platform.python_version(), 'platform': platform.platform(),
              'storage': 'SQLite WAL, BEGIN IMMEDIATE, synchronous FULL',
              'scenarios': {}, 'benchmarks': []}
    with tempfile.TemporaryDirectory(prefix='banking-demo-') as directory:
        def fresh(name):
            database = Database(Path(directory) / f'{name}.db')
            database.initialize()
            database.seed()
            return database, TransactionManager(database)

        database, manager = fresh('deposits')
        with ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(lambda _: manager.deposit(1, 10_000), range(100)))
        actual = database.accounts()[0]['balance_paise']
        report['scenarios']['100_deposits'] = {'expected_paise': 2_000_000, 'actual_paise': actual, 'passed': actual == 2_000_000}

        database, manager = fresh('withdrawals')
        def withdraw(_):
            try:
                manager.withdraw(1, 100_000)
                return True
            except BankingError as exc:
                if 'Insufficient funds' not in str(exc):
                    raise
                return False
        with ThreadPoolExecutor(max_workers=20) as pool:
            successes = sum(pool.map(withdraw, range(20)))
        actual = database.accounts()[0]['balance_paise']
        report['scenarios']['overspending'] = {'successful': successes, 'rejected': 20 - successes,
                                               'final_paise': actual, 'passed': successes == 10 and actual == 0}

        database, manager = fresh('rollback')
        before = database.accounts()
        failure_observed = False
        try:
            manager.transfer(1, 2, 50_000, simulate_failure=True)
        except BankingError as exc:
            failure_observed = 'Injected failure' in str(exc)
        report['scenarios']['rollback'] = {'balances_unchanged': before == database.accounts(),
            'committed_records': len(database.history()), 'failed_records': len(database.failures()),
            'passed': failure_observed and before == database.accounts() and not database.history() and len(database.failures()) == 1}

        database, manager = fresh('opposing')
        def transfer(pair):
            return manager.transfer(*pair, 100)
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(transfer, [(1, 2), (2, 1)] * 50))
        report['scenarios']['opposing_transfers'] = {'completed': len(results),
            'balances_paise': [row['balance_paise'] for row in database.accounts()],
            'passed': len(results) == 100 and all(row['balance_paise'] == 1_000_000 for row in database.accounts())}

        report['scenarios']['deadlock'] = deadlock_demo()
        report['scenarios']['deadlock']['passed'] = (report['scenarios']['deadlock']['workers_finished'] and
                                                    report['scenarios']['deadlock']['circular_wait_observed'])
        report['scenarios']['race_condition'] = race_demo()
        report['scenarios']['race_condition']['passed'] = report['scenarios']['race_condition'] == {
            'expected': 200, 'without_lock': 100, 'with_lock': 200}

        for mode in ('transfer', 'mixed'):
            for workers in (1, 5, 10, 20):
                _, manager = fresh(f'{mode}-{workers}')
                result = run_simulation(manager, workers=workers, operations=100, seed=42, mode=mode)
                result['passed'] = (result['accounting_correct'] and result['balances_nonnegative'] and
                                    result['all_operations_accounted_for'] and not result['unexpected_errors'] and
                                    not result['audit_warnings'] and result['rejected'] == 0)
                report['benchmarks'].append(result)

    report['passed'] = (all(value['passed'] for value in report['scenarios'].values()) and
                        all(value['passed'] for value in report['benchmarks']))
    output = Path(__file__).resolve().parent / 'docs'
    output.mkdir(exist_ok=True)
    (output / 'test_results.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    lines = ['# Recorded demonstration results', '', f"Generated: {report['generated_at_utc']}", '',
             f"Python: {report['python']}; {report['storage']}", '',
             f"Overall result: {'PASS' if report['passed'] else 'FAIL'}", '',
             'These are measured local results, not promised performance. Each workload uses a fresh temporary database.', '',
             '| Scenario | Result |', '|---|---|']
    for name, result in report['scenarios'].items():
        lines.append(f"| {name} | {'PASS' if result['passed'] else 'FAIL'} |")
    lines.extend(['', '| Workload | Threads | Operations | Successful | Rejected | Seconds | Accounting |',
                  '|---|---:|---:|---:|---:|---:|---|'])
    for row in report['benchmarks']:
        lines.append(f"| {row['mode']} | {row['workers']} | {row['requested_operations']} | {row['successful']} | {row['rejected']} | {row['elapsed_seconds']} | {'PASS' if row['passed'] else 'FAIL'} |")
    lines.extend(['', 'SQLite allows one writer at a time, so additional threads need not increase throughput.',
                  'The seed fixes the requested operations; thread execution order and timing can vary.',
                  'The mixed workload checks initial total + successful deposits - successful withdrawals.',
                  'See test_results.json for totals, thread activity, and deadlock events.', ''])
    (output / 'test_results.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
