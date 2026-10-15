"""In-process account mutexes and bounded, reproducible OS demonstrations."""
from contextlib import contextmanager
import threading
import time


class LockTimeout(Exception):
    pass


class AccountLocks:
    def __init__(self):
        self._guard = threading.Lock()
        self._locks = {}
        self.observer = None
        self.visualization_delay = 0

    def for_account(self, account_id):
        with self._guard:
            return self._locks.setdefault(account_id, threading.Lock())

    @contextmanager
    def acquire(self, account_ids, timeout=5.0):
        acquired = []
        deadline = time.monotonic() + timeout
        try:
            for account_id in sorted(set(account_ids)):
                lock = self.for_account(account_id)
                if self.observer:
                    self.observer('waiting' if lock.locked() else 'request', account_id)
                if not lock.acquire(timeout=max(0, deadline - time.monotonic())):
                    if self.observer:
                        self.observer('timeout', account_id)
                    raise LockTimeout(f'Timed out waiting for account {account_id}')
                acquired.append((account_id, lock))
                if self.observer:
                    self.observer('acquired', account_id)
                if self.visualization_delay:
                    time.sleep(self.visualization_delay)
            yield
        finally:
            for account_id, lock in reversed(acquired):
                if self.observer:
                    self.observer('released', account_id)
                lock.release()


_registry_guard = threading.Lock()
_registries = {}


def locks_for_database(path):
    # Multiple manager objects in one process must share the same account locks.
    with _registry_guard:
        return _registries.setdefault(str(path), AccountLocks())


def deadlock_demo(timeout=0.2, observer=None):
    """Force circular waiting on dummy locks; bounded waits let both workers exit."""
    locks = [threading.Lock(), threading.Lock()]
    ready = threading.Barrier(2)
    timed_out = threading.Barrier(2)
    events = []
    guard = threading.Lock()

    def record(message):
        with guard:
            events.append(message)
        if observer:
            observer(message)

    def worker(index):
        first, second = locks[index], locks[1 - index]
        first.acquire()
        try:
            record(f'Thread {index + 1} holds {"A" if index == 0 else "B"}')
            ready.wait(timeout=3)
            record(f'Thread {index + 1} requests {"B" if index == 0 else "A"}')
            got_second = second.acquire(timeout=timeout)
            if got_second:
                second.release()
                record('Unexpected acquisition')
            else:
                record(f'Thread {index + 1}: lock timeout (circular wait)')
            # Hold the first locks until BOTH second-lock attempts have timed out.
            timed_out.wait(timeout=3)
        except threading.BrokenBarrierError:
            record('Barrier timeout: demonstration coordination failed')
        finally:
            first.release()

    workers = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(2)]
    for worker_thread in workers:
        worker_thread.start()
    for worker_thread in workers:
        worker_thread.join(timeout=5)
    return {
        'events': events,
        'workers_finished': all(not thread.is_alive() for thread in workers),
        'circular_wait_observed': sum('lock timeout (circular wait)' in event for event in events) == 2,
        'explanation': 'Timeouts break this deliberately created circular wait. Normal transfers acquire locks in sorted order.',
    }


def race_demo():
    """Deterministically demonstrate a lost update on dummy memory, then its fix."""
    balance = [0]
    barrier = threading.Barrier(2)

    def unsafe():
        old = balance[0]
        barrier.wait(timeout=3)
        balance[0] = old + 100

    threads = [threading.Thread(target=unsafe) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    unsafe_result = balance[0]
    balance[0] = 0
    lock = threading.Lock()

    def safe():
        with lock:
            balance[0] += 100

    threads = [threading.Thread(target=safe) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    return {'expected': 200, 'without_lock': unsafe_result, 'with_lock': balance[0]}
