from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
import io
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from app import main, parse_money
from client_sim import run_simulation
from concurrency_manager import AccountLocks, LockTimeout, deadlock_demo, race_demo
from database import Database, MAX_MONEY
from transaction_manager import BankingError, TransactionManager


class BankingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Database(Path(self.directory.name) / 'test.db')
        self.database.initialize()
        self.database.seed()
        self.manager = TransactionManager(self.database)

    def balance(self, account_id=1):
        return next(row['balance_paise'] for row in self.database.accounts() if row['id'] == account_id)

    def test_deposit_withdraw_transfer_and_history(self):
        self.manager.deposit(1, 10_000)
        self.manager.withdraw(1, 5_000)
        self.manager.transfer(1, 2, 20_000)
        self.assertEqual(self.balance(1), 985_000)
        self.assertEqual(self.balance(2), 1_020_000)
        self.assertEqual(len(self.database.history()), 3)

    def test_seed_preserves_existing_balances(self):
        self.manager.deposit(1, 100)
        self.database.seed()
        self.assertEqual(self.balance(), 1_000_100)

    def test_invalid_amounts(self):
        for amount in (0, -1, 1.5, True, '100', MAX_MONEY + 1):
            with self.subTest(amount=amount), self.assertRaises(BankingError):
                self.manager.deposit(1, amount)
        self.assertEqual(self.balance(), 1_000_000)

    def test_invalid_account_ids(self):
        for account in (True, 0, -1, '1', 1.0, MAX_MONEY + 1):
            with self.subTest(account=account), self.assertRaises(BankingError):
                self.manager.withdraw(account, 100)

    def test_missing_account_and_self_transfer(self):
        for source, destination in [(1, 999), (999, 1), (1, 1)]:
            with self.subTest(source=source, destination=destination), self.assertRaises(BankingError):
                self.manager.transfer(source, destination, 100)
        self.assertEqual(len(self.database.history()), 0)
        self.assertEqual(len(self.database.failures()), 3)

    def test_insufficient_funds(self):
        with self.assertRaisesRegex(BankingError, 'Insufficient'):
            self.manager.withdraw(1, 1_000_001)
        self.assertEqual(self.balance(), 1_000_000)
        self.assertEqual(len(self.database.failures()), 1)

    def test_injected_failure_rolls_back_and_releases_locks(self):
        before = self.database.accounts()
        with self.assertRaisesRegex(BankingError, 'Injected'):
            self.manager.transfer(1, 2, 500, simulate_failure=True)
        self.assertEqual(before, self.database.accounts())
        self.assertEqual(len(self.database.history()), 0)
        self.assertEqual(len(self.database.failures()), 1)
        # A different thread must be able to acquire the released account locks.
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(self.manager.transfer, 1, 2, 500).result(timeout=10)

    def test_request_replay_moves_money_once(self):
        first = self.manager.transfer(1, 2, 500, request_key='repeat')
        second = self.manager.transfer(1, 2, 500, request_key='repeat')
        self.assertEqual(first.transaction_id, second.transaction_id)
        self.assertTrue(second.replayed)
        self.assertEqual(self.balance(), 999_500)
        self.assertEqual(len(self.database.history()), 1)

    def test_conflicting_request_key_rejected(self):
        self.manager.deposit(1, 100, request_key='same')
        with self.assertRaisesRegex(BankingError, 'different operation'):
            self.manager.deposit(1, 200, request_key='same')
        self.assertEqual(self.balance(), 1_000_100)

    def test_concurrent_duplicate_requests(self):
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda _: self.manager.transfer(1, 2, 500, request_key='duplicate'), range(20)))
        self.assertEqual(sum(not result.replayed for result in results), 1)
        self.assertEqual(self.balance(), 999_500)

    def test_100_concurrent_deposits(self):
        with ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(lambda _: self.manager.deposit(1, 10_000), range(100)))
        self.assertEqual(self.balance(), 2_000_000)
        self.assertEqual(len(self.database.history()), 100)

    def test_concurrent_withdrawals_cannot_overspend(self):
        barrier = threading.Barrier(20)
        def withdraw(_):
            barrier.wait(timeout=5)
            try:
                self.manager.withdraw(1, 100_000)
                return True
            except BankingError as exc:
                self.assertIn('Insufficient', str(exc))
                return False
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(withdraw, range(20)))
        self.assertEqual(sum(results), 10)
        self.assertEqual(self.balance(), 0)

    def test_opposing_transfers_finish(self):
        barrier = threading.Barrier(2)
        def transfer(source, destination):
            barrier.wait(timeout=5)
            for _ in range(25):
                self.manager.transfer(source, destination, 100)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(transfer, 1, 2), pool.submit(transfer, 2, 1)]
            for future in futures:
                future.result(timeout=15)
        self.assertEqual(self.balance(1), 1_000_000)
        self.assertEqual(self.balance(2), 1_000_000)

    def test_frozen_account_rejected(self):
        connection = self.database.connect()
        try:
            connection.execute("UPDATE accounts SET status = 'frozen' WHERE id = 2")
        finally:
            connection.close()
        with self.assertRaisesRegex(BankingError, 'frozen'):
            self.manager.transfer(1, 2, 100)
        self.assertEqual(self.balance(), 1_000_000)

    def test_overflow_rolls_back_debit(self):
        connection = self.database.connect()
        try:
            connection.execute('UPDATE accounts SET balance_paise = ? WHERE id = 2', (MAX_MONEY,))
        finally:
            connection.close()
        with self.assertRaisesRegex(BankingError, 'exceed'):
            self.manager.transfer(1, 2, 100)
        self.assertEqual(self.balance(), 1_000_000)

    def test_database_constraint_rejects_negative_balance(self):
        connection = self.database.connect()
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute('UPDATE accounts SET balance_paise = -1 WHERE id = 1')
        finally:
            connection.close()

    def test_lock_timeout_is_audited(self):
        self.manager.lock_timeout = 0.03
        lock = self.manager.locks.for_account(1)
        lock.acquire()
        try:
            with self.assertRaisesRegex(BankingError, 'Timed out'):
                self.manager.withdraw(1, 100)
        finally:
            lock.release()
        self.assertEqual(self.balance(), 1_000_000)
        self.assertEqual(len(self.database.failures()), 1)

    def test_partial_lock_acquisition_is_cleaned_up(self):
        locks = AccountLocks()
        second = locks.for_account(2)
        second.acquire()
        try:
            with self.assertRaises(LockTimeout):
                with locks.acquire([2, 1], timeout=0.03):
                    pass
            first = locks.for_account(1)
            self.assertTrue(first.acquire(blocking=False))
            first.release()
        finally:
            second.release()

    def test_separate_managers_share_locks(self):
        self.assertIs(self.manager.locks, TransactionManager(self.database).locks)

    def test_database_serializes_independent_lock_registries(self):
        # Emulate separate processes: Python lock registries cannot protect each other.
        managers = [TransactionManager(self.database) for _ in range(2)]
        for manager in managers:
            manager.locks = AccountLocks()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda i: managers[i % 2].deposit(1, 100), range(40)))
        self.assertEqual(self.balance(), 1_004_000)

    def test_simulator_accounts_for_mixed_operations(self):
        result = run_simulation(self.manager, workers=10, operations=100)
        self.assertTrue(result['accounting_correct'])
        self.assertTrue(result['all_operations_accounted_for'])
        self.assertTrue(result['balances_nonnegative'])
        self.assertFalse(result['unexpected_errors'])

    def test_simulator_transfer_conservation(self):
        result = run_simulation(self.manager, workers=20, operations=100, mode='transfer')
        self.assertEqual(result['initial_total_paise'], result['actual_total_paise'])
        self.assertEqual(result['successful'], 100)

    def test_deadlock_demonstration_is_bounded(self):
        result = deadlock_demo(timeout=0.05)
        self.assertTrue(result['workers_finished'])
        self.assertTrue(result['circular_wait_observed'])

    def test_race_demonstration(self):
        result = race_demo()
        self.assertEqual(result, {'expected': 200, 'without_lock': 100, 'with_lock': 200})

    def test_money_parser(self):
        import argparse
        self.assertEqual(parse_money('123.45'), 12_345)
        for value in ('nan', 'inf', '-1', '0', '1.001', 'abc', '1e999999'):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                parse_money(value)

    def test_cli_and_persistence(self):
        args = ['--db', str(self.database.path)]
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(args + ['deposit', '1', '25.50']), 0)
            self.assertEqual(main(args + ['transfer', '1', '2', '10', '--fail-after-debit']), 1)
        self.assertEqual(Database(self.database.path).accounts()[0]['balance_paise'], 1_002_550)


if __name__ == '__main__':
    unittest.main()
