"""Local review of committed demo transfers using the sender's recent history."""
import json
import math
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from statistics import median


MODEL_PATH = Path(__file__).with_name('data') / 'transfer_profile_v2.json'
VERSION = 'transfer-profile-v2'
HISTORY = 20
MIN_HISTORY = 3
RECENT_PAYMENTS = 256
FEATURE_NAMES = (
    'amount_to_sender_median', 'amount_to_sender_max', 'sender_max_to_median',
    'amount_above_fraction', 'amount_to_recipient_median', 'recent_recipient_count',
    'earlier_today', 'new_recipient', 'history_count', 'amount_to_recent_payments_capped',
)


def features(amount, history, earlier_today, recipient, new_recipient, recent_typical):
    """Build currency-independent features from earlier (recipient, amount) pairs."""
    if len(history) < MIN_HISTORY:
        return None
    amounts = [value for _, value in history]
    typical = median(amounts)
    if typical <= 0:
        return None
    largest = max(amounts)
    recipient_amounts = [value for destination, value in history if destination == recipient]
    recipient_typical = (median(recipient_amounts) if recipient_amounts else 0) or typical
    sender_ratio = amount / typical
    # A large population-relative amount only adds a strong signal when it also
    # stands out against the sender's own activity.
    recent_ratio = min(amount / (recent_typical or typical), max(1, sender_ratio) ** 3)
    return [
        math.log1p(sender_ratio),
        math.log1p(amount / largest),
        math.log1p(largest / typical),
        sum(value < amount for value in amounts) / len(amounts),
        math.log1p(amount / recipient_typical),
        len(recipient_amounts),
        min(earlier_today, HISTORY),
        int(new_recipient),
        len(amounts),
        math.log1p(recent_ratio),
    ]


def score_transfer(model, inputs):
    """Evaluate the exported trees in pure Python."""
    raw = model['bias']
    for tree in model['trees']:
        index = 0
        while len(tree[index]) == 4:
            feature, threshold, left, right = tree[index]
            index = left if inputs[feature] <= threshold else right
        raw += tree[index][0]
    return 1 / (1 + math.exp(-max(-60, min(60, raw))))


@lru_cache(maxsize=1)
def load_model():
    model = json.loads(MODEL_PATH.read_text(encoding='utf-8'))
    if (model['version'] != VERSION or tuple(model['feature_names']) != FEATURE_NAMES
            or not model['trees']):
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
        prior = [tuple(payment) for payment in conn.execute("""SELECT destination_id,amount_paise FROM transactions
            WHERE source_id=? AND operation='transfer' AND id<? ORDER BY id DESC LIMIT ?""",
            (sender, transaction_id, HISTORY))]
        today = conn.execute("""SELECT count(*) FROM transactions WHERE source_id=?
            AND operation='transfer' AND id<? AND created_at>=? AND created_at<=?""",
            (sender, transaction_id, row['created_at'][:10], row['created_at'])).fetchone()[0]
        known = conn.execute("""SELECT 1 FROM transactions WHERE source_id=? AND destination_id=?
            AND operation='transfer' AND id<? LIMIT 1""",
            (sender, row['destination_id'], transaction_id)).fetchone()
        recent_amounts = [payment[0] for payment in conn.execute("""SELECT amount_paise FROM transactions
            WHERE operation='transfer' AND id<? ORDER BY id DESC LIMIT ?""",
            (transaction_id, RECENT_PAYMENTS))]
        recent_typical = median(recent_amounts) if recent_amounts else None
        inputs = features(row['amount_paise'], prior, today, row['destination_id'], known is None,
                          recent_typical)
        score = None
        status = 'insufficient_history'
        reason = f'{len(prior)} earlier transfers available. The sender profile requires at least {MIN_HISTORY}.'
        alerts = []
        if inputs is not None:
            score = score_transfer(model, inputs)
            status = 'review' if score >= model['threshold'] else 'clear'
            ratio = row['amount_paise'] / median(amount for _, amount in prior)
            reason = (f'Amount was {ratio:.2f} times the median of the last {len(prior)} outgoing '
                      f'transfers. {today} earlier today (UTC). Recipient: {"known" if known else "new"}.')
            if status == 'review':
                alert = conn.execute("""INSERT INTO fraud_alerts(transaction_id,user_id,rule,reason)
                    VALUES (?,?,'local_profile',?)""", (transaction_id, user_id, reason))
                alerts.append({'id': alert.lastrowid, 'rule': 'local_profile', 'reason': reason})
        conn.execute("""INSERT INTO local_reviews(transaction_id,model_version,status,score,threshold,reason)
            VALUES (?,?,?,?,?,?)""", (transaction_id, VERSION, status, score, model['threshold'], reason))
        return alerts
