"""Score committed transfers with the locally stored BankSim-trained model."""
import json
import math
from pathlib import Path


MODEL_PATH = Path(__file__).parent / 'data' / 'banksim_model.json'
MODEL = json.loads(MODEL_PATH.read_text(encoding='utf-8'))
RISK_THRESHOLD = MODEL['threshold']


def risk_score(amount_paise, earlier_transfers_today, new_recipient):
    """Return a BankSim-style risk estimate and the three input features."""
    raw = (math.log1p(amount_paise / 100), min(earlier_transfers_today, 20), int(new_recipient))
    z = MODEL['bias'] + sum(weight * ((value - mean) / scale)
                            for weight, value, mean, scale in zip(
                                MODEL['weights'], raw, MODEL['means'], MODEL['scales']))
    return 1 / (1 + math.exp(-max(-60, min(60, z)))), raw


def _transfer_inputs(connection, transaction):
    """Inputs as they stood when this committed transfer was recorded."""
    earlier = connection.execute("""SELECT count(*) FROM transactions
        WHERE source_id=? AND operation='transfer' AND id < ?
          AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', ?, '-1 day')""",
        (transaction['source_id'], transaction['id'], transaction['created_at'])).fetchone()[0]
    prior_recipient = connection.execute("""SELECT 1 FROM transactions
        WHERE source_id=? AND destination_id=? AND operation='transfer' AND id < ? LIMIT 1""",
        (transaction['source_id'], transaction['destination_id'], transaction['id'])).fetchone()
    return earlier, prior_recipient is None


def transfer_risk_details(database, transaction_id):
    """Explain the local model's score for a committed transfer; never create an alert."""
    connection = database.connect()
    try:
        transaction = connection.execute('SELECT * FROM transactions WHERE id=?', (transaction_id,)).fetchone()
        if transaction is None:
            raise ValueError('Committed transaction not found')
        if transaction['operation'] != 'transfer':
            return None
        earlier, new_recipient = _transfer_inputs(connection, transaction)
        recent_minute = connection.execute("""SELECT count(*) FROM transactions
            WHERE source_id=? AND operation='transfer' AND id < ?
              AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', ?, '-60 seconds')""",
            (transaction['source_id'], transaction_id, transaction['created_at'])).fetchone()[0]
        score, raw = risk_score(transaction['amount_paise'], earlier, new_recipient)
        contributions = [weight * ((value - mean) / scale)
                         for weight, value, mean, scale in zip(
                             MODEL['weights'], raw, MODEL['means'], MODEL['scales'])]
        strongest = max(range(3), key=lambda index: contributions[index])
        if score >= RISK_THRESHOLD:
            signal = ('the transfer amount', 'recent transfer activity', 'the new recipient')[strongest]
            explanation = (f'This score crosses the {RISK_THRESHOLD:.0%} review threshold; '
                           f'{signal} is the strongest upward model input for this transfer.')
        elif earlier >= 4:
            explanation = ('Earlier transfers raise the score, but the amount and recipient history '
                           f'leave it below the {RISK_THRESHOLD:.0%} model threshold. '
                           'The rapid-activity rule is checked separately.')
        elif new_recipient:
            explanation = ('A new recipient adds some risk, but this amount and the limited earlier '
                           f'activity keep the score below the {RISK_THRESHOLD:.0%} review threshold.')
        else:
            explanation = ('This amount, earlier activity and recipient history together keep the '
                           f'score below the {RISK_THRESHOLD:.0%} review threshold.')
        return {'amount_paise': transaction['amount_paise'], 'earlier': earlier,
                'recent_minute': recent_minute,
                'new_recipient': new_recipient, 'score': score,
                'threshold': RISK_THRESHOLD, 'explanation': explanation}
    finally:
        connection.close()


def scan_ai_risk(database, transaction_id, user_id):
    """Score one committed transfer and save one review alert when warranted."""
    connection = database.connect()
    try:
        connection.execute('BEGIN IMMEDIATE')
        transaction = connection.execute('SELECT * FROM transactions WHERE id = ?', (transaction_id,)).fetchone()
        if transaction is None:
            raise ValueError('Committed transaction not found')
        if transaction['operation'] != 'transfer':
            connection.commit()
            return []
        previous = connection.execute("SELECT id FROM fraud_alerts WHERE transaction_id=? AND rule='ai_risk'",
                                      (transaction_id,)).fetchone()
        if previous:
            connection.commit()
            return []
        earlier, new_recipient = _transfer_inputs(connection, transaction)
        score, _ = risk_score(transaction['amount_paise'], earlier, new_recipient)
        if score < RISK_THRESHOLD:
            connection.commit()
            return []
        factors = [f'transfer amount INR {transaction["amount_paise"] / 100:,.2f}',
                   f'{earlier} earlier outgoing transfers today',
                   'new recipient' if new_recipient else 'known recipient']
        reason = f'AI risk score {score:.2%} (BankSim-trained): ' + ', '.join(factors)
        cursor = connection.execute('INSERT INTO fraud_alerts(transaction_id, user_id, rule, reason) VALUES (?, ?, ?, ?)',
                                    (transaction_id, user_id, 'ai_risk', reason))
        connection.commit()
        return [{'id': cursor.lastrowid, 'rule': 'ai_risk', 'reason': reason, 'score': round(score, 4)}]
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == '__main__':
    print(f'Model: {MODEL_PATH}')
    print(f'Source: {MODEL["source_name"]} ({MODEL["source_url"]})')
    print(f'Training rows: {MODEL["training_rows"]:,}; fraud labels: {MODEL["training_fraud"]:,}')
    print(f'Later-day test rows: {MODEL["test_rows"]:,}; fraud labels: {MODEL["test_fraud"]:,}')
    print(f'Holdout average precision: {MODEL["average_precision"]:.3f}')
    print(f'Holdout precision/recall at {RISK_THRESHOLD:.0%}: '
          f'{MODEL["precision"]:.1%} / {MODEL["recall"]:.1%}')
    print(f'Example INR 5,000 first transfer: {risk_score(500_000, 0, True)[0]:.2%} risk')
    print('BankSim is a simulated payment dataset. Its scores are not calibrated for this INR transfer demo.')
