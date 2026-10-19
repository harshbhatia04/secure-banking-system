"""Local demo identities, password checks and login rate limiting."""
import os
import secrets

from werkzeug.security import check_password_hash, generate_password_hash

DEMO_PASSWORD = os.environ.get('PBL_DEMO_PASSWORD', 'Demo@2026!')


def seed_demo_users(database):
    connection = database.connect()
    try:
        connection.execute('BEGIN IMMEDIATE')
        for user_id, name, username in ((1, 'Harsh Bhatia', 'harsh'),
                                        (2, 'Prakhar Garg', 'prakhar'),
                                        (3, 'Tanisha Kapoor', 'tanisha')):
            connection.execute('UPDATE users SET name = ?, username = ?, role = ? WHERE id = ?',
                               (name, username, 'customer', user_id))
        # Only create the admin if missing; never reset an existing password.
        connection.execute("INSERT OR IGNORE INTO users(id, name, username, role) VALUES (4, 'Admin', 'admin', 'admin')")
        connection.execute("UPDATE users SET name = 'Admin' WHERE id = 4 AND username = 'admin' AND name = 'Professor Demo'")
        for user_id in (1, 2, 3, 4):
            row = connection.execute('SELECT password_hash FROM users WHERE id = ?', (user_id,)).fetchone()
            if row and not row['password_hash']:
                connection.execute('UPDATE users SET password_hash = ? WHERE id = ?',
                                   (generate_password_hash(DEMO_PASSWORD), user_id))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def secret_key_for(database):
    path = database.path.parent / '.secret_key'
    if not path.exists():
        path.write_text(secrets.token_hex(32), encoding='ascii')
    return path.read_text(encoding='ascii').strip()


def authenticate(database, username, password):
    username = username.strip().lower()[:80]
    connection = database.connect()
    try:
        connection.execute('BEGIN IMMEDIATE')
        recent = connection.execute("""SELECT count(*) FROM login_attempts
            WHERE username = ? AND success = 0 AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-5 minutes')""",
            (username,)).fetchone()[0]
        if recent >= 5:
            connection.commit()
            return None, 'Too many attempts. Try again in five minutes.'
        user = connection.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        valid = bool(user and user['password_hash'] and check_password_hash(user['password_hash'], password))
        connection.execute('INSERT INTO login_attempts(username, success) VALUES (?, ?)', (username, int(valid)))
        connection.commit()
        if valid:
            return dict(user), None
        return None, 'Incorrect username or password.'
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
