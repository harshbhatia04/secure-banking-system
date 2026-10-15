"""Repeatable threaded workloads with accounting checks and bounded waits."""
from collections import Counter
from dataclasses import asdict
from queue import Empty, Queue
import random
import threading
import time

from transaction_manager import BankingError


def run_simulation(manager, workers=10, operations=100, seed=42, mode='mixed'):
    if not 1 <= workers <= 100 or not 1 <= operations <= 10_000:
        raise ValueError('Use 1-100 workers and 1-10000 operations')
    if mode not in ('mixed', 'transfer'):
        raise ValueError('Mode must be mixed or transfer')
    before_accounts = manager.database.accounts()
    account_ids = [row['id'] for row in before_accounts if row['status'] == 'active']
    if len(account_ids) < 2:
        raise ValueError('The simulator requires at least two active accounts')
    before = sum(row['balance_paise'] for row in before_accounts)
    rng = random.Random(seed)
    queue = Queue()
    for _ in range(operations):
        source, destination = rng.sample(account_ids, 2)
        operation = rng.choice(['deposit', 'withdraw', 'transfer']) if mode == 'mixed' else 'transfer'
        queue.put((operation, source, destination, rng.randint(1, 100) * 100))
    barrier = threading.Barrier(workers)
    guard = threading.Lock()
    successful, rejected, unexpected = [], [], []
    counts = Counter()

    def worker():
        try:
            barrier.wait(timeout=10)
            while True:
                try:
                    operation, source, destination, amount = queue.get_nowait()
                except Empty:
                    return
                try:
                    if operation == 'transfer':
                        result = manager.transfer(source, destination, amount)
                    else:
                        result = getattr(manager, operation)(source, amount)
                    with guard:
                        successful.append(asdict(result))
                        counts[threading.current_thread().name] += 1
                except BankingError as exc:
                    with guard:
                        rejected.append({'reason': str(exc), 'audit_warning': exc.audit_warning})
                finally:
                    queue.task_done()
        except Exception as exc:
            with guard:
                unexpected.append(repr(exc))

    started = time.perf_counter()
    threads = [threading.Thread(target=worker, name=f'client-{i + 1}', daemon=True) for i in range(workers)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + 60
    for thread in threads:
        thread.join(timeout=max(0, deadline - time.monotonic()))
    alive = [thread.name for thread in threads if thread.is_alive()]
    if alive:
        raise RuntimeError(f'Simulation exceeded 60 seconds; workers still running: {alive}')
    elapsed = time.perf_counter() - started
    after_accounts = manager.database.accounts()
    after = sum(row['balance_paise'] for row in after_accounts)
    deposits = sum(row['amount_paise'] for row in successful if row['operation'] == 'deposit')
    withdrawals = sum(row['amount_paise'] for row in successful if row['operation'] == 'withdraw')
    expected = before + deposits - withdrawals
    return {
        'mode': mode, 'seed': seed, 'workers': workers, 'requested_operations': operations,
        'successful': len(successful), 'rejected': len(rejected),
        'rejection_reasons': dict(Counter(row['reason'] for row in rejected)),
        'audit_warnings': [row['audit_warning'] for row in rejected if row['audit_warning']],
        'unexpected_errors': unexpected, 'workers_finished': not alive,
        'completed_by_worker': dict(counts), 'elapsed_seconds': round(elapsed, 4),
        'operations_per_second': round((len(successful) + len(rejected)) / elapsed, 2),
        'initial_total_paise': before, 'deposited_paise': deposits, 'withdrawn_paise': withdrawals,
        'expected_total_paise': expected, 'actual_total_paise': after,
        'balances_nonnegative': all(row['balance_paise'] >= 0 for row in after_accounts),
        'accounting_correct': after == expected,
        'all_operations_accounted_for': len(successful) + len(rejected) == operations,
    }
