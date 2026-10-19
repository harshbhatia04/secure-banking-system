PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    username TEXT UNIQUE,
    password_hash TEXT,
    role TEXT NOT NULL DEFAULT 'customer' CHECK(role IN ('customer', 'admin'))
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    balance_paise INTEGER NOT NULL CHECK(typeof(balance_paise) = 'integer' AND balance_paise >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'frozen'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_key TEXT UNIQUE NOT NULL,
    operation TEXT NOT NULL CHECK(operation IN ('deposit', 'withdraw', 'transfer')),
    source_id INTEGER REFERENCES accounts(id),
    destination_id INTEGER REFERENCES accounts(id),
    amount_paise INTEGER NOT NULL CHECK(typeof(amount_paise) = 'integer' AND amount_paise > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        (operation = 'deposit' AND source_id IS NULL AND destination_id IS NOT NULL) OR
        (operation = 'withdraw' AND source_id IS NOT NULL AND destination_id IS NULL) OR
        (operation = 'transfer' AND source_id IS NOT NULL AND destination_id IS NOT NULL AND source_id <> destination_id)
    )
);

-- Committed transactions are successes. Rejected/rolled-back attempts live separately.
CREATE TABLE IF NOT EXISTS failed_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_key TEXT NOT NULL,
    operation TEXT NOT NULL,
    source_id INTEGER,
    destination_id INTEGER,
    amount_paise INTEGER,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Explainable fraud alerts, linked to a committed transaction when applicable.
CREATE TABLE IF NOT EXISTS fraud_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER REFERENCES transactions(id),
    rule TEXT NOT NULL,
    reason TEXT NOT NULL,
    reviewed INTEGER NOT NULL DEFAULT 0 CHECK(reviewed IN (0, 1)),
    user_id INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    success INTEGER NOT NULL CHECK(success IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS ix_login_attempts_name_time ON login_attempts(username, created_at);
CREATE INDEX IF NOT EXISTS ix_transactions_time ON transactions(created_at);
CREATE INDEX IF NOT EXISTS ix_failures_time ON failed_attempts(created_at);

-- Actual events observed while a web transaction runs. They are buffered until
-- the banking COMMIT and saved afterward, so tracing cannot split the payment.
CREATE TABLE IF NOT EXISTS transaction_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    sequence INTEGER NOT NULL,
    occurred_at TEXT NOT NULL,
    elapsed_ms REAL NOT NULL CHECK(elapsed_ms >= 0),
    process_id INTEGER NOT NULL,
    native_thread_id INTEGER NOT NULL,
    component TEXT NOT NULL,
    action TEXT NOT NULL,
    message TEXT NOT NULL,
    account_id INTEGER,
    duration_ms REAL CHECK(duration_ms IS NULL OR duration_ms >= 0),
    UNIQUE(transaction_id, sequence)
);
CREATE INDEX IF NOT EXISTS ix_transaction_events_transaction ON transaction_events(transaction_id, sequence);
