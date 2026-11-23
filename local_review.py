"""Local review of committed demo transfers using the sender's recent history."""
import json
import math
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from statistics import median


MODEL_PATH = Path(__file__).with_name('data') / 'transfer_profile_v1.json'
VERSION = 'transfer-profile-v1'
HISTORY = 20
MIN_HISTORY = 3


def features(amount, history, earlier_today, new_recipient):
    """Use a dimensionless amount ratio in both training and inference."""
    if len(history) < MIN_HISTORY or median(history) <= 0:
        return None
    return [math.log1p(amount / median(history)), min(earlier_today, 20), int(new_recipient)]


@lru_cache(maxsize=1)
def load_model():
    model = json.loads(MODEL_PATH.read_text(encoding='utf-8'))
    if model['version'] != VERSION or len(model['weights']) != 3:
        raise ValueError('Unsupported local model artifact')
    return model


def scan_local_review(database, transaction_id, user_id):
    model = load_model()
    with closing(database.connect()) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM transactions WHERE id=?', (transaction_id,)).fetchone()
        if row is None or row['operation'] != 'transfer':
            return []
        if conn.execute('SELECT 1 FROM local_reviews WHERE transaction_id=?', (transaction_id,)).fetchone():
            return []
        sender = row['source_id']
        prior = [r[0] for r in conn.execute("""SELECT amount_paise FROM transactions
            WHERE source_id=? AND operation='transfer' AND id<? ORDER BY id DESC LIMIT ?""",
            (sender, transaction_id, HISTORY))]
        today = conn.execute("""SELECT count(*) FROM transactions WHERE source_id=?
            AND operation='transfer' AND id<? AND created_at>=?""",
            (sender, transaction_id, row['created_at'][:10])).fetchone()[0]
        known = conn.execute("""SELECT 1 FROM transactions WHERE source_id=? AND destination_id=?
            AND operation='transfer' AND id<? LIMIT 1""",
            (sender, row['destination_id'], transaction_id)).fetchone()
        inputs = features(row['amount_paise'], prior, today, known is None)
        score = None
        status = 'insufficient_history'
        reason = f'{len(prior)} earlier transfers available. The sender profile requires at least {MIN_HISTORY}.'
        alerts = []
        if inputs is not None:
            z = model['bias'] + sum(w*x for w, x in zip(model['weights'], inputs))
            score = 1 / (1 + math.exp(-max(-60, min(60, z))))
            status = 'review' if score >= model['threshold'] else 'clear'
            ratio = row['amount_paise'] / median(prior)
            reason = (f'Amount was {ratio:.2f} times the median of the last {len(prior)} outgoing '
                      f'transfers. {today} earlier today (UTC). Recipient: {"known" if known else "new"}.')
            if status == 'review':
                alert = conn.execute("""INSERT INTO fraud_alerts(transaction_id,user_id,rule,reason)
                    VALUES (?,?,'local_profile',?)""", (transaction_id, user_id, reason))
                alerts.append({'id': alert.lastrowid, 'rule': 'local_profile', 'reason': reason})
        conn.execute("""INSERT INTO local_reviews(transaction_id,model_version,status,score,threshold,reason)
            VALUES (?,?,?,?,?,?)""", (transaction_id, VERSION, status, score, model['threshold'], reason))
        return alerts
