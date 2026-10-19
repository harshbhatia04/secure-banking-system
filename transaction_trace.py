"""Per-request observations of the real banking code path."""
from datetime import datetime, timezone
import os
import threading
import time


class TransactionTrace:
    def __init__(self):
        self.started_ns = time.perf_counter_ns()
        self.events = []

    def record(self, component, action, message, *, account_id=None, duration_ms=None):
        self.events.append({
            'sequence': len(self.events) + 1,
            'occurred_at': datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
            'elapsed_ms': round((time.perf_counter_ns() - self.started_ns) / 1_000_000, 3),
            'process_id': os.getpid(),
            'native_thread_id': threading.get_native_id(),
            'component': component,
            'action': action,
            'message': message,
            'account_id': account_id,
            'duration_ms': round(duration_ms, 3) if duration_ms is not None else None,
        })

    def lock_event(self, action, account_id, wait_ms=None):
        if action == 'requested':
            message = f'Requested account #{account_id} mutex'
        elif action == 'waiting':
            message = f'Account #{account_id} mutex held by another worker; waiting'
        elif action == 'acquired':
            message = f'Acquired account #{account_id} mutex after {wait_ms:.3f} ms'
        elif action == 'released':
            message = f'Released account #{account_id} mutex'
        else:
            message = f'Timed out waiting for account #{account_id} mutex'
        self.record('THREAD', f'lock_{action}', message, account_id=account_id,
                    duration_ms=wait_ms)

    def save(self, database, transaction_id):
        connection = database.connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            connection.executemany('''
                INSERT INTO transaction_events(transaction_id, sequence, occurred_at, elapsed_ms,
                    process_id, native_thread_id, component, action, message, account_id, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', [
                (transaction_id, event['sequence'], event['occurred_at'], event['elapsed_ms'],
                 event['process_id'], event['native_thread_id'], event['component'],
                 event['action'], event['message'], event['account_id'], event['duration_ms'])
                for event in self.events
            ])
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
