"""SQLite storage. Money is always integer paise, never floating point."""
from pathlib import Path
import sqlite3

MAX_MONEY = 9_000_000_000_000_000


class Database:
    def __init__(self, path='data/banking.db', timeout=5.0):
        self.path = Path(path).resolve()
        self.timeout = timeout

    def connect(self):
        # Each call creates a connection owned by its calling thread.
        connection = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('PRAGMA synchronous = FULL')
        return connection

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        try:
            connection.execute('PRAGMA journal_mode = WAL')
            connection.executescript(Path(__file__).with_name('schema.sql').read_text(encoding='utf-8'))
            # Upgrade the Week 1-3 demo database without deleting balances/history.
            user_columns = {row['name'] for row in connection.execute('PRAGMA table_info(users)')}
            for name, definition in {
                'username': 'TEXT', 'password_hash': 'TEXT', 'role': "TEXT NOT NULL DEFAULT 'customer'"
            }.items():
                if name not in user_columns:
                    connection.execute(f'ALTER TABLE users ADD COLUMN {name} {definition}')
            connection.execute('CREATE UNIQUE INDEX IF NOT EXISTS ux_users_username ON users(username)')
            alert_columns = {row['name'] for row in connection.execute('PRAGMA table_info(fraud_alerts)')}
            if 'user_id' not in alert_columns:
                connection.execute('ALTER TABLE fraud_alerts ADD COLUMN user_id INTEGER REFERENCES users(id)')
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS login_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL,
                    success INTEGER NOT NULL CHECK(success IN (0, 1)),
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                );
                CREATE INDEX IF NOT EXISTS ix_login_attempts_name_time ON login_attempts(username, created_at);
                CREATE INDEX IF NOT EXISTS ix_transactions_time ON transactions(created_at);
                CREATE INDEX IF NOT EXISTS ix_failures_time ON failed_attempts(created_at);
            ''')
        finally:
            connection.close()

    def seed(self):
        """Insert missing demo accounts; never reset an existing balance."""
        connection = self.connect()
        try:
            connection.execute('BEGIN IMMEDIATE')
            for account_id, name in [(1, 'Harsh'), (2, 'Prakhar'), (3, 'Tanisha')]:
                connection.execute('INSERT OR IGNORE INTO users(id, name) VALUES (?, ?)', (account_id, name))
                connection.execute(
                    'INSERT OR IGNORE INTO accounts(id, user_id, balance_paise) VALUES (?, ?, ?)',
                    (account_id, account_id, 1_000_000),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def accounts(self):
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute(
                'SELECT a.id, u.name, a.balance_paise, a.status FROM accounts a '
                'JOIN users u ON a.user_id = u.id ORDER BY a.id'
            )]
        finally:
            connection.close()

    def history(self):
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute('SELECT * FROM transactions ORDER BY id')]
        finally:
            connection.close()

    def failures(self):
        connection = self.connect()
        try:
            return [dict(row) for row in connection.execute('SELECT * FROM failed_attempts ORDER BY id')]
        finally:
            connection.close()

    def total(self):
        return sum(account['balance_paise'] for account in self.accounts())
