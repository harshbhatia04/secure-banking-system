"""Atomic banking operations with lock ordering, validation and idempotency."""
from dataclasses import dataclass
import sqlite3
import time
import uuid

from concurrency_manager import LockTimeout, locks_for_database
from database import MAX_MONEY


class BankingError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.audit_warning = None


@dataclass(frozen=True)
class TransactionResult:
    transaction_id: int
    request_key: str
    operation: str
    amount_paise: int
    replayed: bool = False


class TransactionManager:
    def __init__(self, database, lock_timeout=5.0):
        self.database = database
        self.locks = locks_for_database(database.path)
        self.lock_timeout = lock_timeout
        self.observer = None

    def deposit(self, account_id, amount_paise, *, request_key=None, trace=None):
        return self._execute('deposit', None, account_id, amount_paise, request_key, trace=trace)

    def withdraw(self, account_id, amount_paise, *, request_key=None, trace=None):
        return self._execute('withdraw', account_id, None, amount_paise, request_key, trace=trace)

    def transfer(self, source_id, destination_id, amount_paise, *, request_key=None, simulate_failure=False, trace=None):
        return self._execute('transfer', source_id, destination_id, amount_paise, request_key, simulate_failure, trace)

    def _execute(self, operation, source_id, destination_id, amount, request_key, simulate_failure=False, trace=None):
        def emit(component, action, message, *, duration_ms=None):
            if trace:
                trace.record(component, action, message, duration_ms=duration_ms)

        key = request_key if request_key is not None else str(uuid.uuid4())
        # Reject malformed values before binding them to SQLite.
        if type(amount) is not int or not 0 < amount <= MAX_MONEY:
            raise BankingError('Amount must be a positive integer number of paise within the supported limit')
        ids = [value for value in (source_id, destination_id) if value is not None]
        if not ids or any(type(value) is not int or not 0 < value <= MAX_MONEY for value in ids):
            raise BankingError('Account IDs must be positive integers within the supported limit')
        if not isinstance(key, str) or not key.strip() or len(key) > 128:
            raise BankingError('Request key must contain 1 to 128 characters')
        emit('SERVICE', 'validated', f'{operation.title()} request validated; amount {amount} paise')
        try:
            if operation == 'transfer' and source_id == destination_id:
                raise BankingError('Source and destination must be different accounts')
            with self.locks.acquire(ids, timeout=self.lock_timeout,
                                    trace=trace.lock_event if trace else None):
                connection = self.database.connect()
                emit('SQLITE', 'connection_opened', 'Opened a SQLite connection for this worker')
                try:
                    # Reserve SQLite's single writer BEFORE checking balances.
                    writer_wait_started = time.perf_counter_ns()
                    connection.execute('BEGIN IMMEDIATE')
                    writer_wait_ms = (time.perf_counter_ns() - writer_wait_started) / 1_000_000
                    emit('SQLITE', 'begin_immediate', f'BEGIN IMMEDIATE reserved the SQLite writer after {writer_wait_ms:.3f} ms', duration_ms=writer_wait_ms)
                    previous = connection.execute('SELECT * FROM transactions WHERE request_key = ?', (key,)).fetchone()
                    if previous is not None:
                        if (previous['operation'], previous['source_id'], previous['destination_id'], previous['amount_paise']) != (operation, source_id, destination_id, amount):
                            raise BankingError('Request key was already used for a different operation')
                        connection.commit()
                        emit('SQLITE', 'duplicate_request', f'Existing ledger row #{previous["id"]} found; no balance changed')
                        return TransactionResult(previous['id'], key, operation, amount, replayed=True)
                    emit('SQLITE', 'request_key_checked', 'No previous ledger row uses this request key')
                    accounts = {}
                    for account_id in sorted(set(ids)):
                        account = connection.execute('SELECT * FROM accounts WHERE id = ?', (account_id,)).fetchone()
                        if account is None:
                            raise BankingError(f'Account {account_id} does not exist')
                        if account['status'] != 'active':
                            raise BankingError(f'Account {account_id} is frozen')
                        accounts[account_id] = account
                        emit('SQLITE', 'account_read', f'Read active account #{account_id}')
                    if source_id is not None:
                        if accounts[source_id]['balance_paise'] < amount:
                            raise BankingError('Insufficient funds')
                        connection.execute('UPDATE accounts SET balance_paise = balance_paise - ? WHERE id = ?', (amount, source_id))
                        emit('SQLITE', 'debit_written', f'Debited {amount} paise from account #{source_id} inside the open transaction')
                    if simulate_failure:
                        raise BankingError('Injected failure after debit; transfer rolled back')
                    if destination_id is not None:
                        if accounts[destination_id]['balance_paise'] + amount > MAX_MONEY:
                            raise BankingError('Destination balance would exceed the supported limit')
                        connection.execute('UPDATE accounts SET balance_paise = balance_paise + ? WHERE id = ?', (amount, destination_id))
                        emit('SQLITE', 'credit_written', f'Credited {amount} paise to account #{destination_id} inside the open transaction')
                    cursor = connection.execute(
                        'INSERT INTO transactions(request_key, operation, source_id, destination_id, amount_paise) VALUES (?, ?, ?, ?, ?)',
                        (key, operation, source_id, destination_id, amount),
                    )
                    emit('SQLITE', 'ledger_inserted', f'Inserted ledger row #{cursor.lastrowid} in the same transaction')
                    connection.commit()
                    emit('SQLITE', 'committed', f'COMMIT made ledger row #{cursor.lastrowid} and balance updates durable')
                    if self.observer:
                        self.observer('committed', operation, ids)
                    return TransactionResult(cursor.lastrowid, key, operation, amount)
                except Exception:
                    connection.rollback()
                    emit('SQLITE', 'rolled_back', 'ROLLBACK discarded uncommitted balance and ledger changes')
                    if self.observer:
                        self.observer('rolled_back', operation, ids)
                    raise
                finally:
                    connection.close()
                    emit('SQLITE', 'connection_closed', 'Closed the worker SQLite connection')
        except (BankingError, LockTimeout, sqlite3.Error) as exc:
            error = exc if isinstance(exc, BankingError) else BankingError(str(exc))
            # A rolled-back transaction cannot also retain its own failure record.
            # Audit in a NEW transaction after releasing account locks.
            try:
                connection = self.database.connect()
                try:
                    connection.execute(
                        'INSERT INTO failed_attempts(request_key, operation, source_id, destination_id, amount_paise, reason) VALUES (?, ?, ?, ?, ?, ?)',
                        (key, operation, source_id, destination_id, amount, str(error)),
                    )
                finally:
                    connection.close()
            except sqlite3.Error as audit_error:
                error.audit_warning = f'Failure could not be persisted: {audit_error}'
            if error is exc:
                raise
            raise error from exc
