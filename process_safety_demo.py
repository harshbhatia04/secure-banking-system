"""Verify cross-process writes, request replay, and crash rollback on temporary data."""

from datetime import datetime, timezone
import json
import multiprocessing as mp
import os
from pathlib import Path
import sqlite3
import tempfile

from database import Database
from transaction_manager import TransactionManager


ROOT = Path(__file__).resolve().parent
RESULT_PATH = ROOT / 'docs' / 'process_safety_results.json'


def _transfer_worker(path, source, destination, amount, count, request_key, ready, start, results):
    """Run in a separate OS process with its own Python account-lock registry."""
    ready.set()
    if not start.wait(10):
        results.put({'error': 'start timeout'})
        return
    try:
        manager = TransactionManager(Database(path, timeout=10.0), lock_timeout=10.0)
        replayed = []
        for _ in range(count):
            result = manager.transfer(source, destination, amount, request_key=request_key)
            replayed.append(result.replayed)
        results.put({'completed': count, 'replayed': replayed})
    except Exception as exc:
        results.put({'error': f'{type(exc).__name__}: {exc}'})


def _crash_after_debit(path, debited):
    """Exit without COMMIT after a debit to exercise SQLite crash recovery."""
    connection = Database(path).connect()
    connection.execute('BEGIN IMMEDIATE')
    connection.execute('UPDATE accounts SET balance_paise = balance_paise - 100 WHERE id = 1')
    debited.set()
    os._exit(7)


def _pair(context, path, requests):
    start = context.Event()
    results = context.Queue()
    ready = [context.Event(), context.Event()]
    workers = [context.Process(target=_transfer_worker,
                               args=(str(path), *request, ready[index], start, results))
               for index, request in enumerate(requests)]
    try:
        for worker in workers:
            worker.start()
        if not all(signal.wait(10) for signal in ready):
            raise RuntimeError('A worker did not start within 10 seconds')
        start.set()
        for worker in workers:
            worker.join(30)
        if any(worker.is_alive() for worker in workers):
            raise RuntimeError('A worker did not finish within 30 seconds')
        outcomes = [results.get(timeout=3) for _ in workers]
        return {'exit_codes': [worker.exitcode for worker in workers], 'outcomes': outcomes}
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(3)
        results.close()


def main():
    context = mp.get_context('spawn')
    report = {'generated_at_utc': datetime.now(timezone.utc).isoformat(),
              'python_start_method': context.get_start_method(),
              'sqlite_version': sqlite3.sqlite_version}
    with tempfile.TemporaryDirectory(prefix='banking-process-safety-') as directory:
        directory = Path(directory)

        opposing_path = directory / 'opposing.db'
        opposing_db = Database(opposing_path)
        opposing_db.initialize()
        opposing_db.seed()
        opposing = _pair(context, opposing_path,
                         [(1, 2, 100, 25, None), (2, 1, 100, 25, None)])
        balances = [row['balance_paise'] for row in opposing_db.accounts()]
        opposing.update({'balances_paise': balances,
                         'ledger_rows': len(opposing_db.history())})
        opposing['passed'] = (opposing['exit_codes'] == [0, 0]
                             and all(outcome.get('completed') == 25 for outcome in opposing['outcomes'])
                             and balances == [1_000_000] * 3 and opposing['ledger_rows'] == 50)
        report['opposing_transfers_two_processes'] = opposing

        replay_path = directory / 'replay.db'
        replay_db = Database(replay_path)
        replay_db.initialize()
        replay_db.seed()
        replay = _pair(context, replay_path,
                       [(1, 2, 12_345, 1, 'same-key-two-processes')] * 2)
        balances = [row['balance_paise'] for row in replay_db.accounts()]
        replay.update({'balances_paise': balances, 'ledger_rows': len(replay_db.history())})
        replay['passed'] = (replay['exit_codes'] == [0, 0]
                            and sorted(outcome.get('replayed', [None])[0]
                                       for outcome in replay['outcomes']) == [False, True]
                            and balances == [987_655, 1_012_345, 1_000_000]
                            and replay['ledger_rows'] == 1)
        report['same_key_two_processes'] = replay

        crash_path = directory / 'crash.db'
        crash_db = Database(crash_path)
        crash_db.initialize()
        crash_db.seed()
        before = [row['balance_paise'] for row in crash_db.accounts()]
        debited = context.Event()
        crash = context.Process(target=_crash_after_debit, args=(str(crash_path), debited))
        try:
            crash.start()
            if not debited.wait(10):
                raise RuntimeError('Crash worker did not reach the debit')
            crash.join(10)
            if crash.is_alive():
                raise RuntimeError('Crash worker did not exit')
        finally:
            if crash.is_alive():
                crash.terminate()
                crash.join(3)
        after = [row['balance_paise'] for row in crash_db.accounts()]
        report['uncommitted_debit_process_crash'] = {
            'exit_code': crash.exitcode, 'balances_before_paise': before,
            'balances_after_paise': after, 'ledger_rows': len(crash_db.history()),
            'passed': crash.exitcode == 7 and before == after and not crash_db.history()}

    report['overall_passed'] = all(value['passed'] for key, value in report.items()
                                   if isinstance(value, dict) and 'passed' in value)
    RESULT_PATH.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value['passed'] for key, value in report.items()
                      if isinstance(value, dict) and 'passed' in value}, indent=2))
    print(f'Overall: {"PASS" if report["overall_passed"] else "FAIL"}; evidence: {RESULT_PATH}')
    return 0 if report['overall_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
