"""Explainable rules; alerts are recorded after successful ledger commits."""

HIGH_VALUE_PAISE = 500_000  # INR 5,000, convenient for a local demonstration.
RAPID_COUNT = 5
FAILED_COUNT = 3


def transfer_review_context(connection, transaction):
    """Return observed transfer context at commit time, without a model score."""
    if transaction['operation'] != 'transfer':
        return None
    earlier = connection.execute("""SELECT count(*) FROM transactions
        WHERE source_id=? AND operation='transfer' AND id < ?
          AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', ?, '-1 day')""",
        (transaction['source_id'], transaction['id'], transaction['created_at'])).fetchone()[0]
    recent_minute = connection.execute("""SELECT count(*) FROM transactions
        WHERE source_id=? AND operation='transfer' AND id < ?
          AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', ?, '-60 seconds')""",
        (transaction['source_id'], transaction['id'], transaction['created_at'])).fetchone()[0]
    known = connection.execute("""SELECT 1 FROM transactions
        WHERE source_id=? AND destination_id=? AND operation='transfer' AND id < ? LIMIT 1""",
        (transaction['source_id'], transaction['destination_id'], transaction['id'])).fetchone()
    return {'amount_paise': transaction['amount_paise'], 'earlier_24h': earlier,
            'earlier_60s': recent_minute, 'new_recipient': known is None}


def scan_transaction(database, transaction_id, user_id):
    connection = database.connect()
    try:
        connection.execute('BEGIN IMMEDIATE')
        transaction = connection.execute('SELECT * FROM transactions WHERE id = ?', (transaction_id,)).fetchone()
        if transaction is None:
            connection.rollback()
            raise ValueError('Committed transaction not found')
        if transaction['operation'] != 'transfer':
            connection.commit()
            return []
        rules = []
        if transaction['amount_paise'] >= HIGH_VALUE_PAISE:
            rules.append(('high_value', 'Transfer of INR 5,000 or more'))
        recent = connection.execute("""SELECT count(*) FROM transactions
            WHERE source_id = ? AND operation = 'transfer'
              AND id <= ? AND created_at <= ?
              AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', ?, '-60 seconds')""",
            (transaction['source_id'], transaction_id,
             transaction['created_at'], transaction['created_at'])).fetchone()[0]
        if recent >= RAPID_COUNT:
            rules.append(('rapid_activity', f'{recent} transfers from this account within 60 seconds'))
        created = []
        for rule, reason in rules:
            prior = connection.execute('SELECT id FROM fraud_alerts WHERE transaction_id = ? AND rule = ?',
                                       (transaction_id, rule)).fetchone()
            if prior:
                continue
            cursor = connection.execute('INSERT INTO fraud_alerts(transaction_id, user_id, rule, reason) VALUES (?, ?, ?, ?)',
                                        (transaction_id, user_id, rule, reason))
            created.append({'id': cursor.lastrowid, 'rule': rule, 'reason': reason})
        connection.commit()
        return created
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def scan_failed_attempt(database, user_id, account_id):
    connection = database.connect()
    try:
        connection.execute('BEGIN IMMEDIATE')
        recent = connection.execute("""SELECT count(*) FROM failed_attempts
            WHERE source_id = ? AND operation IN ('withdraw', 'transfer')
              AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-5 minutes')""",
            (account_id,)).fetchone()[0]
        if recent == FAILED_COUNT:
            connection.execute('INSERT INTO fraud_alerts(user_id, rule, reason) VALUES (?, ?, ?)',
                               (user_id, 'repeated_failures', 'Three failed outgoing operations within five minutes'))
        connection.commit()
        return recent >= FAILED_COUNT
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def scan_failed_login(database, username):
    connection = database.connect()
    try:
        connection.execute('BEGIN IMMEDIATE')
        recent = connection.execute("""SELECT count(*) FROM login_attempts
            WHERE username = ? AND success = 0
              AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-5 minutes')""", (username,)).fetchone()[0]
        if recent == 5:
            user = connection.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
            connection.execute('INSERT INTO fraud_alerts(user_id, rule, reason) VALUES (?, ?, ?)',
                               (user['id'] if user else None, 'login_failures', f'Five failed logins for {username} within five minutes'))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def record_unauthorized(database, user_id, account_id):
    connection = database.connect()
    try:
        connection.execute('BEGIN IMMEDIATE')
        reason = f'User {user_id} attempted to operate account {account_id} without ownership'
        connection.execute('INSERT INTO failed_attempts(request_key, operation, source_id, reason) VALUES (?, ?, ?, ?)',
                           (f'unauthorized-{user_id}-{account_id}', 'unauthorized', account_id, reason))
        connection.execute('INSERT INTO fraud_alerts(user_id, rule, reason) VALUES (?, ?, ?)',
                           (user_id, 'unauthorized_access', reason))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
