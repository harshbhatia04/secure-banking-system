"""End-to-end checks for the optional external review and local fallback."""

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from groq_fraud import GroqFraudError
from web_app import create_app


class GroqReviewTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.app = create_app(Path(directory.name) / 'web.db')
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.database = self.app.config['DATABASE']
        self.client.get('/login')
        with self.client.session_transaction() as session:
            token = session['csrf_token']
        self.client.post('/login', data={'csrf_token': token, 'username': 'harsh',
                                         'password': 'Demo@2026!'}, follow_redirects=True)

    def transfer(self):
        with self.client.session_transaction() as session:
            token = session['csrf_token']
        return self.client.post('/transfer', data={
            'csrf_token': token, 'operation': 'transfer', 'source_id': '1',
            'destination_id': '2', 'amount': '5000',
        }, follow_redirects=True)

    def rules(self):
        connection = self.database.connect()
        try:
            return [row[0] for row in connection.execute('SELECT rule FROM fraud_alerts ORDER BY id')]
        finally:
            connection.close()

    def test_groq_review_creates_labelled_alert_without_sending_identity(self):
        result = {'choices': [{'message': {'content': json.dumps({
            'risk_level': 'high', 'review': True, 'reason': 'Large first transfer to a new recipient.'
        })}}]}
        with patch.dict('os.environ', {'GROQ_API_KEY': 'test-key'}), \
                patch('groq_fraud.urlopen', return_value=BytesIO(json.dumps(result).encode())) as send:
            page = self.transfer()
        self.assertEqual(page.status_code, 200)
        self.assertEqual(len(self.database.history()), 1)
        self.assertIn('groq_review', self.rules())
        self.assertNotIn('ai_risk', self.rules())
        request = send.call_args.args[0]
        sent_features = json.loads(json.loads(request.data)['messages'][1]['content'])
        self.assertEqual(sent_features, {'amount_inr': 5000.0,
                                         'earlier_transfers_24h': 0, 'new_recipient': True})
        self.assertNotIn('Harsh', request.data.decode())

    def test_api_failure_uses_local_model_without_undoing_transfer(self):
        with patch.dict('os.environ', {'GROQ_API_KEY': 'test-key'}), \
                patch('web_app.scan_groq_risk', side_effect=GroqFraudError('offline')):
            page = self.transfer()
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'Groq was unavailable', page.data)
        self.assertEqual(len(self.database.history()), 1)
        self.assertIn('ai_risk', self.rules())
        self.assertNotIn('groq_review', self.rules())


if __name__ == '__main__':
    unittest.main()
