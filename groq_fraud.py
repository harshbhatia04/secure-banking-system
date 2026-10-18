"""Optional, clearly labelled Groq LLM review for committed demo transfers."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = 'https://api.groq.com/openai/v1/chat/completions'
DEFAULT_MODEL = 'openai/gpt-oss-20b'


class GroqFraudError(Exception):
    """The external review could not be completed."""


def configured():
    return bool(os.environ.get('GROQ_API_KEY', '').strip())


def model_name():
    return os.environ.get('GROQ_MODEL', DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _transfer_features(database, transaction_id):
    connection = database.connect()
    try:
        transaction = connection.execute('SELECT * FROM transactions WHERE id=?', (transaction_id,)).fetchone()
        if transaction is None:
            raise ValueError('Committed transaction not found')
        if transaction['operation'] != 'transfer':
            return None
        prior_alert = connection.execute(
            "SELECT 1 FROM fraud_alerts WHERE transaction_id=? AND rule='groq_review' LIMIT 1",
            (transaction_id,)).fetchone()
        if prior_alert:
            return None
        earlier = connection.execute("""SELECT count(*) FROM transactions
            WHERE source_id=? AND operation='transfer' AND id < ?
              AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-1 day')""",
            (transaction['source_id'], transaction_id)).fetchone()[0]
        known = connection.execute("""SELECT 1 FROM transactions
            WHERE source_id=? AND destination_id=? AND operation='transfer' AND id < ? LIMIT 1""",
            (transaction['source_id'], transaction['destination_id'], transaction_id)).fetchone()
        # No customer name, username, account number, or transaction ID leaves the app.
        return {'amount_inr': transaction['amount_paise'] / 100,
                'earlier_transfers_24h': earlier, 'new_recipient': known is None}
    finally:
        connection.close()


def _review_with_groq(features, api_key):
    schema = {
        'type': 'object',
        'properties': {
            'risk_level': {'type': 'string', 'enum': ['low', 'medium', 'high']},
            'review': {'type': 'boolean'},
            'reason': {'type': 'string'},
        },
        'required': ['risk_level', 'review', 'reason'],
        'additionalProperties': False,
    }
    payload = {
        'model': model_name(),
        'messages': [
            {'role': 'system', 'content': (
                'You assist an educational banking demo. Assess whether a completed transfer merits '
                'human review using only the supplied amount, recent frequency, and recipient history. '
                'A review flag is not proof of fraud. Use review=true for medium or high concern. '
                'Give one short, factual reason; do not invent customer details or claim a calibrated probability.')},
            {'role': 'user', 'content': json.dumps(features, separators=(',', ':'))},
        ],
        'response_format': {'type': 'json_schema', 'json_schema': {
            'name': 'transfer_review', 'strict': True, 'schema': schema}},
        'reasoning_effort': 'low',
        'max_completion_tokens': 300,
    }
    request = Request(API_URL, data=json.dumps(payload).encode('utf-8'), method='POST', headers={
        'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=6) as response:
            body = response.read(65537)
    except HTTPError as exc:
        raise GroqFraudError(f'Groq returned HTTP {exc.code}') from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise GroqFraudError('Groq could not be reached') from exc
    if len(body) > 65536:
        raise GroqFraudError('Groq response was too large')
    try:
        answer = json.loads(json.loads(body)['choices'][0]['message']['content'])
        if (answer['risk_level'] not in ('low', 'medium', 'high') or
                type(answer['review']) is not bool or not isinstance(answer['reason'], str)):
            raise ValueError('Invalid review fields')
        answer['reason'] = ''.join(ch for ch in answer['reason'] if ch.isprintable()).strip()[:240]
        if not answer['reason']:
            raise ValueError('Missing review reason')
        return answer
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise GroqFraudError('Groq returned an invalid review') from exc


def scan_groq_risk(database, transaction_id, user_id):
    """Ask Groq for a review signal; write only flagged transfers as alerts."""
    api_key = os.environ.get('GROQ_API_KEY', '').strip()
    if not api_key:
        raise GroqFraudError('GROQ_API_KEY is not configured')
    features = _transfer_features(database, transaction_id)
    if features is None:
        return []
    answer = _review_with_groq(features, api_key)
    if not answer['review']:
        return []
    reason = f"Groq AI review ({model_name()}, {answer['risk_level']}): {answer['reason']}"
    connection = database.connect()
    try:
        connection.execute('BEGIN IMMEDIATE')
        prior = connection.execute(
            "SELECT 1 FROM fraud_alerts WHERE transaction_id=? AND rule='groq_review' LIMIT 1",
            (transaction_id,)).fetchone()
        if prior:
            connection.commit()
            return []
        cursor = connection.execute(
            'INSERT INTO fraud_alerts(transaction_id, user_id, rule, reason) VALUES (?, ?, ?, ?)',
            (transaction_id, user_id, 'groq_review', reason))
        connection.commit()
        return [{'id': cursor.lastrowid, 'rule': 'groq_review', 'reason': reason}]
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
