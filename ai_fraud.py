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
        earlier = connection.execute("""SELECT count(*) FROM transactions
            WHERE source_id=? AND operation='transfer' AND id < ?
              AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-1 day')""",
            (transaction['source_id'], transaction_id)).fetchone()[0]
        prior_recipient = connection.execute("""SELECT 1 FROM transactions
            WHERE source_id=? AND destination_id=? AND operation='transfer' AND id < ? LIMIT 1""",
            (transaction['source_id'], transaction['destination_id'], transaction_id)).fetchone()
        new_recipient = prior_recipient is None
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
