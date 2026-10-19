from pathlib import Path
import tempfile
import time
import unittest

from web_app import create_app
from fraud_detector import transfer_review_context


class WebTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.app = create_app(Path(directory.name) / 'web.db')
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.database = self.app.config['DATABASE']

    def token(self):
        self.client.get('/login')
        with self.client.session_transaction() as session:
            return session['csrf_token']

    def sign_in(self, username='harsh'):
        response = self.client.post('/login', data={'username': username, 'password': 'Demo@2026!',
                             'csrf_token': self.token()}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Admin overview' if username == 'admin' else b'Good evening', response.data)
        if username == 'admin':
            self.assertNotIn(b'Professor Demo', response.data)
            self.assertNotIn(b'Good evening', response.data)

    def test_login_and_page_rendering(self):
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Every balance', response.data)
        self.sign_in()
        for path in ('/', '/transfer', '/activity'):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_login_required_and_admin_separation(self):
        self.assertEqual(self.client.get('/').status_code, 302)
        self.sign_in()
        self.assertEqual(self.client.get('/admin').status_code, 403)
        self.assertEqual(self.client.get('/admin/demo').status_code, 403)
        self.assertEqual(self.client.get('/lab').status_code, 403)
        self.assertEqual(self.client.get('/lab/api/state').status_code, 403)
        self.assertEqual(self.client.post('/lab/run', data={'csrf_token': self.token()}).status_code, 403)

    def test_csrf_and_account_ownership(self):
        self.sign_in()
        self.assertEqual(self.client.post('/transfer', data={'operation': 'deposit', 'source_id': '1', 'amount': '10'}).status_code, 400)
        response = self.client.post('/transfer', data={'csrf_token': self.token(), 'operation': 'withdraw',
                                    'source_id': '2', 'amount': '1'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(self.database.history()), 0)
        connection = self.database.connect()
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM fraud_alerts WHERE rule='unauthorized_access'").fetchone()[0], 1)
        finally:
            connection.close()

    def test_transfer_fraud_and_customer_history_scope(self):
        self.sign_in()
        response = self.client.post('/transfer', data={'csrf_token': self.token(), 'operation': 'transfer',
                                    'source_id': '1', 'destination_id': '2', 'amount': '5000'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'review alert', response.data)
        self.assertIn(b'One durable transaction', response.data)
        self.assertEqual(len(self.database.history()), 1)
        connection = self.database.connect()
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM fraud_alerts WHERE rule='high_value'").fetchone()[0], 1)
            ai_alert = connection.execute("SELECT reason FROM fraud_alerts WHERE rule='ai_risk'").fetchone()
            self.assertIsNone(ai_alert)
        finally:
            connection.close()
        self.assertEqual(self.database.accounts()[0]['balance_paise'], 500_000)
        self.assertEqual(self.database.accounts()[1]['balance_paise'], 1_500_000)

    def test_transaction_detail_uses_ledger_and_respects_account_scope(self):
        self.sign_in()
        response = self.client.post('/transfer', data={'csrf_token': self.token(), 'operation': 'transfer',
                                    'source_id': '1', 'destination_id': '2', 'amount': '5000'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], '/activity/1')
        detail = self.client.get('/activity/1')
        self.assertIn(b'One durable transaction', detail.data)
        self.assertIn(b'High Value', detail.data)
        self.assertIn(b'id="paymentSuccess"', detail.data)
        self.assertNotIn(b'id="paymentSuccess"', self.client.get('/activity/1').data)
        self.client.post('/logout', data={'csrf_token': self.token()})
        self.sign_in('tanisha')
        self.assertEqual(self.client.get('/activity/1').status_code, 403)
        self.client.post('/logout', data={'csrf_token': self.token()})
        self.sign_in('prakhar')
        recipient_detail = self.client.get('/activity/1')
        self.assertEqual(recipient_detail.status_code, 200)
        self.assertNotIn(b'High Value', recipient_detail.data)

    def test_admin_inspection_shows_review_context_without_exposing_it_to_recipient(self):
        self.sign_in('harsh')
        for amount in ('100', '5000'):
            response = self.client.post('/transfer', data={
                'csrf_token': self.token(), 'operation': 'transfer',
                'source_id': '1', 'destination_id': '2', 'amount': amount})
            self.assertEqual(response.status_code, 302)
        self.client.post('/logout', data={'csrf_token': self.token()})
        self.sign_in('admin')
        first = self.client.get('/activity/1')
        second = self.client.get('/activity/2')
        for page in (first, second):
            self.assertIn(b'What the detector saw', page.data)
            self.assertIn(b'How reviews work', page.data)
            self.assertIn(b'Earlier outgoing transfers', page.data)
        connection = self.database.connect()
        try:
            first_context = transfer_review_context(connection, connection.execute(
                'SELECT * FROM transactions WHERE id=1').fetchone())
            second_context = transfer_review_context(connection, connection.execute(
                'SELECT * FROM transactions WHERE id=2').fetchone())
        finally:
            connection.close()
        self.assertEqual(first_context['earlier_24h'], 0)
        self.assertEqual(second_context['earlier_24h'], 1)
        self.assertNotIn(b'BankSim', first.data)
        self.assertIn(b'High Value', second.data)
        self.assertNotIn(b'BankSim', second.data)
        self.app.config['MANAGER'].deposit(1, 100)
        self.assertIn(b'Transfer-risk review does not apply', self.client.get('/activity/3').data)
        self.client.post('/logout', data={'csrf_token': self.token()})
        self.sign_in('prakhar')
        self.assertNotIn(b'How reviews work', self.client.get('/activity/2').data)

    def test_replayed_request_does_not_show_new_success_animation(self):
        self.sign_in()
        data = {'operation': 'transfer', 'source_id': '1', 'destination_id': '2',
                'amount': '100', 'request_key': 'presentation-duplicate'}
        first = self.client.post('/transfer', data={**data, 'csrf_token': self.token()})
        self.assertEqual(first.status_code, 302)
        self.assertIn(b'id="paymentSuccess"', self.client.get(first.headers['Location']).data)
        replay = self.client.post('/transfer', data={**data, 'csrf_token': self.token()},
                                  follow_redirects=True)
        self.assertEqual(replay.status_code, 200)
        self.assertIn(b'Request already processed', replay.data)
        self.assertNotIn(b'id="paymentSuccess"', replay.data)
        self.assertEqual(len(self.database.history()), 1)

    def test_receipt_contains_real_backend_trace_without_replay_duplicates(self):
        self.sign_in()
        data = {'operation': 'transfer', 'source_id': '1', 'destination_id': '2',
                'amount': '25', 'request_key': 'observed-transfer'}
        response = self.client.post('/transfer', data={**data, 'csrf_token': self.token()})
        self.assertEqual(response.status_code, 302)
        receipt = self.client.get(response.headers['Location'])
        self.assertIn(b'OBSERVED BACKEND EVENTS', receipt.data)
        self.assertIn(b'COMMIT made ledger row #1', receipt.data)

        connection = self.database.connect()
        try:
            events = [dict(row) for row in connection.execute(
                'SELECT * FROM transaction_events WHERE transaction_id=1 ORDER BY sequence')]
        finally:
            connection.close()
        actions = [event['action'] for event in events]
        self.assertEqual([event['account_id'] for event in events
                          if event['action'] == 'lock_acquired'], [1, 2])
        self.assertLess(actions.index('ledger_inserted'), actions.index('committed'))
        self.assertLess(actions.index('committed'), actions.index('lock_released'))
        self.assertLess(actions.index('lock_released'), actions.index('rules_started'))
        self.assertEqual({event['native_thread_id'] for event in events},
                         {events[0]['native_thread_id']})

        self.client.post('/transfer', data={**data, 'csrf_token': self.token()})
        connection = self.database.connect()
        try:
            saved_count = connection.execute(
                'SELECT count(*) FROM transaction_events WHERE transaction_id=1').fetchone()[0]
        finally:
            connection.close()
        self.assertEqual(saved_count, len(events))

    def test_invalid_amount_does_not_crash(self):
        self.sign_in()
        response = self.client.post('/transfer', data={'csrf_token': self.token(), 'operation': 'deposit',
                                    'source_id': '1', 'amount': 'bad'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'positive rupee amount', response.data)

    def test_repeated_failed_operations_create_alert(self):
        self.sign_in()
        for _ in range(2):
            response = self.client.post('/transfer', data={'csrf_token': self.token(), 'operation': 'withdraw',
                                        'source_id': '1', 'amount': '10001'}, follow_redirects=True)
            self.assertEqual(response.status_code, 200)
        connection = self.database.connect()
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM fraud_alerts WHERE rule='repeated_failures'").fetchone()[0], 0)
        finally:
            connection.close()
        response = self.client.post('/transfer', data={'csrf_token': self.token(), 'operation': 'withdraw',
                                    'source_id': '1', 'amount': '10001'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        connection = self.database.connect()
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM fraud_alerts WHERE rule='repeated_failures'").fetchone()[0], 1)
        finally:
            connection.close()

    def test_login_attempt_limit_and_alert(self):
        for _ in range(4):
            response = self.client.post('/login', data={'csrf_token': self.token(), 'username': 'harsh',
                                         'password': 'wrong'}, follow_redirects=True)
            self.assertEqual(response.status_code, 200)
        connection = self.database.connect()
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM login_attempts WHERE username='harsh' AND success=0").fetchone()[0], 4)
            self.assertEqual(connection.execute("SELECT count(*) FROM fraud_alerts WHERE rule='login_failures'").fetchone()[0], 0)
        finally:
            connection.close()
        self.client.post('/login', data={'csrf_token': self.token(), 'username': 'hars',
                             'password': 'wrong'}, follow_redirects=True)
        response = self.client.post('/login', data={'csrf_token': self.token(), 'username': 'harsh',
                                    'password': 'wrong'}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        response = self.client.post('/login', data={'csrf_token': self.token(), 'username': 'harsh',
                                    'password': 'Demo@2026!'}, follow_redirects=True)
        self.assertIn(b'Too many attempts', response.data)
        connection = self.database.connect()
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM fraud_alerts WHERE rule='login_failures'").fetchone()[0], 1)
        finally:
            connection.close()
        self.sign_in('admin')
        desk = self.client.get('/admin')
        self.assertIn(b'Failed sign-in attempts', desk.data)
        self.assertIn(b'hars', desk.data)
        self.assertIn(b'5/5', desk.data)

    def test_rapid_transfer_alert_starts_on_fifth_payment(self):
        self.sign_in()
        for number in range(1, 6):
            response = self.client.post('/transfer', data={'csrf_token': self.token(), 'operation': 'transfer',
                                        'source_id': '1', 'destination_id': '2', 'amount': '1'})
            self.assertEqual(response.status_code, 302)
            connection = self.database.connect()
            try:
                count = connection.execute("SELECT count(*) FROM fraud_alerts WHERE rule='rapid_activity'").fetchone()[0]
                self.assertEqual(count, 1 if number == 5 else 0)
            finally:
                connection.close()

    def test_alert_timestamp_survives_upgrade_of_old_database(self):
        self.sign_in()
        self.client.post('/transfer', data={'csrf_token': self.token(), 'operation': 'transfer',
                         'source_id': '1', 'destination_id': '2', 'amount': '5000'})
        connection = self.database.connect()
        try:
            connection.execute('DROP TRIGGER set_fraud_alert_time')
            connection.execute('DROP TABLE fraud_alerts')
            connection.execute('''CREATE TABLE fraud_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER REFERENCES transactions(id),
                rule TEXT NOT NULL, reason TEXT NOT NULL,
                reviewed INTEGER NOT NULL DEFAULT 0, user_id INTEGER REFERENCES users(id))''')
            connection.execute("INSERT INTO fraud_alerts(transaction_id, rule, reason, user_id) "
                               "VALUES (1, 'high_value', 'Existing alert', 1)")
        finally:
            connection.close()
        self.database.initialize()
        connection = self.database.connect()
        try:
            old_time = connection.execute('SELECT created_at FROM fraud_alerts WHERE id=1').fetchone()[0]
            self.assertEqual(old_time, connection.execute('SELECT created_at FROM transactions WHERE id=1').fetchone()[0])
            connection.execute("INSERT INTO fraud_alerts(rule, reason) VALUES ('login_failures', 'New alert')")
            self.assertIsNotNone(connection.execute('SELECT created_at FROM fraud_alerts WHERE id=2').fetchone()[0])
        finally:
            connection.close()

    def test_admin_alert_review_and_lab(self):
        self.sign_in('admin')
        self.assertEqual(self.client.get('/admin').status_code, 200)
        self.assertEqual(self.client.get('/lab').status_code, 200)
        before = self.database.total()
        response = self.client.post('/lab/run', data={'csrf_token': self.token()}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'What is happening now', response.data)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = self.client.get('/lab/api/state').get_json()
            if not state['running']:
                break
            time.sleep(.05)
        self.assertIsNone(state['error'])
        self.assertEqual(state['result']['sample']['successful'], 50)
        self.assertTrue(state['result']['rollback']['passed'])
        self.assertEqual(state['committed'], 50)
        self.assertTrue(any(event['kind'] == 'waiting' for event in state['events']))
        self.assertEqual(self.database.total(), before)
        connection = self.database.connect()
        try:
            cursor = connection.execute("INSERT INTO fraud_alerts(rule, reason) VALUES ('test', 'Review me')")
            alert_id = cursor.lastrowid
        finally:
            connection.close()
        response = self.client.post(f'/admin/alerts/{alert_id}/review',
                                    data={'csrf_token': self.token()}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Reviewed', response.data)

    def test_admin_demo_scenarios_are_real_and_isolated(self):
        self.sign_in('admin')
        self.assertIn(b'Demo studio', self.client.get('/admin/demo').data)
        original_accounts = self.database.accounts()
        for scenario, evidence in (
            ('normal', b'No rule alert created'),
            ('high_value', b'High Value'),
            ('rapid', b'Rapid Activity'),
            ('rollback', b'ROLLBACK discarded'),
            ('duplicate', b'Existing ledger row'),
        ):
            with self.subTest(scenario=scenario):
                response = self.client.post('/admin/demo',
                    data={'csrf_token': self.token(), 'scenario': scenario})
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'CHECKS PASSED', response.data)
                self.assertIn(evidence, response.data)
                self.assertEqual(self.database.accounts(), original_accounts)
                self.assertEqual(self.database.history(), [])
                self.assertEqual(self.database.failures(), [])
        self.assertEqual(self.client.post('/admin/demo', data={
            'csrf_token': self.token(), 'scenario': 'invalid'}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
