"""Thread-safe, read-only snapshots of an isolated demonstration run."""
from collections import deque
import threading
from datetime import datetime


class LabMonitor:
    def __init__(self):
        self.guard = threading.Lock()
        self.running = False
        self.stage = 'Ready to run'
        self.holders = {}
        self.waiting = {}
        self.events = deque(maxlen=80)
        self.committed = 0
        self.rolled_back = 0
        self.wait_count = 0
        self.last_edges = []
        self.result = None
        self.error = None

    def start(self):
        with self.guard:
            if self.running:
                return False
            self.running = True
            self.stage = 'Preparing isolated database'
            self.holders = {}
            self.waiting = {}
            self.events.clear()
            self.committed = 0
            self.rolled_back = 0
            self.wait_count = 0
            self.last_edges = []
            self.result = None
            self.error = None
            self._event('started', 'Lab started in a temporary database')
            return True

    def _event(self, kind, message):
        self.events.appendleft({'time': datetime.now().strftime('%H:%M:%S.%f')[:-3],
                                'kind': kind, 'message': message})

    def set_stage(self, stage):
        with self.guard:
            self.stage = stage
            self._event('stage', stage)

    def demo_event(self, message):
        with self.guard:
            self._event('deadlock', message)

    def lock_event(self, kind, account_id):
        name = threading.current_thread().name
        with self.guard:
            if kind in ('request', 'waiting'):
                self.waiting[name] = account_id
                if kind == 'waiting':
                    self.wait_count += 1
            elif kind == 'acquired':
                self.waiting.pop(name, None)
                self.holders[account_id] = name
            elif kind in ('released', 'timeout'):
                if kind == 'released' and self.holders.get(account_id) == name:
                    self.holders.pop(account_id)
                self.waiting.pop(name, None)
            verbs = {'request': 'requests', 'waiting': 'waits for', 'acquired': 'holds',
                     'released': 'releases', 'timeout': 'timed out on'}
            self._event(kind, f'{name} {verbs[kind]} account {account_id}')
            edges = self._edges()
            if edges:
                self.last_edges = edges

    def _edges(self):
        return [{'waiter': name, 'holder': self.holders[account_id], 'account': account_id}
                for name, account_id in self.waiting.items()
                if account_id in self.holders and self.holders[account_id] != name]

    def transaction_event(self, kind, operation, ids):
        name = threading.current_thread().name
        with self.guard:
            if kind == 'committed':
                self.committed += 1
            else:
                self.rolled_back += 1
            self._event(kind, f'{name} {kind.replace("_", " ")} {operation} '
                        f'({" → ".join(map(str, ids))})')

    def finish(self, result=None, error=None):
        with self.guard:
            self.result = result
            self.error = str(error) if error else None
            self.running = False
            self.stage = 'Completed' if error is None else 'Demo failed'
            self._event('error' if error else 'complete', self.error or 'All demonstrations finished')

    def snapshot(self):
        with self.guard:
            edges = self._edges()
            return {'running': self.running, 'stage': self.stage,
                    'holders': dict(self.holders), 'waiting': dict(self.waiting),
                    'edges': edges, 'last_edges': list(self.last_edges),
                    'wait_count': self.wait_count, 'events': list(self.events),
                    'committed': self.committed, 'rolled_back': self.rolled_back,
                    'result': self.result, 'error': self.error}
