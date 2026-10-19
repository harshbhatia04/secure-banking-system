"""Repeatable presentation scenarios using the real banking code on an isolated DB."""
from pathlib import Path
import tempfile

from database import Database
from fraud_detector import scan_transaction, transfer_review_context
from transaction_manager import BankingError, TransactionManager
from transaction_trace import TransactionTrace


SCENARIOS = {
    'normal': {
        'title': 'Ordinary payment', 'subtitle': 'A small transfer to a new recipient',
        'concept': 'One commit, no review alert', 'number': '01',
        'talking_point': 'The worker takes account locks in ID order. SQLite commits the debit, credit and ledger row together; the review finds no reason to flag it.',
    },
    'high_value': {
        'title': 'High-value payment', 'subtitle': 'A ₹5,000 transfer crosses the rule threshold',
        'concept': 'Amount-threshold review', 'number': '02',
        'talking_point': 'The transfer commits first. The ₹5,000 threshold then creates a rule-based review alert; this is not a fraud verdict.',
    },
    'rapid': {
        'title': 'Rapid payments', 'subtitle': 'Five transfers from one account within a minute',
        'concept': 'Activity threshold becomes an alert', 'number': '03',
        'talking_point': 'Each transfer is valid alone. The fifth committed transfer crosses the 60-second activity threshold, so the rule creates an alert.',
    },
    'rollback': {
        'title': 'Failure after debit', 'subtitle': 'Inject an error between debit and credit',
        'concept': 'Rollback preserves both balances', 'number': '04',
        'talking_point': 'An injected error occurs after the debit statement. SQLite rolls the entire transaction back, so neither balance nor the ledger changes.',
    },
    'duplicate': {
        'title': 'Repeated request', 'subtitle': 'Submit the same transfer key twice',
        'concept': 'One ledger row and one debit', 'number': '05',
        'talking_point': 'Both requests carry the same idempotency key. The second request sees the existing ledger row and returns it without charging the account again.',
    },
}


def run_scenario(name):
    if name not in SCENARIOS:
        raise ValueError('Unknown demo scenario')
    with tempfile.TemporaryDirectory(prefix='geu-bank-demo-') as directory:
        database = Database(Path(directory) / 'scenario.db')
        database.initialize()
        database.seed()
        manager = TransactionManager(database)
        before = database.accounts()
        runs = []
        last_transaction_id = None
        replayed = False
        error = None

        def transfer(label, amount, *, key=None, fail=False):
            nonlocal last_transaction_id, replayed, error
            trace = TransactionTrace()
            try:
                outcome = manager.transfer(1, 2, amount, request_key=key,
                                           simulate_failure=fail, trace=trace)
                last_transaction_id = outcome.transaction_id
                replayed = outcome.replayed
                if not outcome.replayed:
                    trace.record('RISK', 'review_started', 'Reviewing the committed transfer')
                    rule_alerts = scan_transaction(database, outcome.transaction_id, 1)
                    trace.record('RISK', 'review_finished',
                                 f'Created {len(rule_alerts)} rule review alert(s)')
            except BankingError as exc:
                error = str(exc)
                trace.record('SERVICE', 'request_failed', error)
            runs.append({'label': label, 'events': trace.events})

        if name == 'normal':
            transfer('Transfer ₹100', 10_000)
        elif name == 'high_value':
            transfer('Transfer ₹5,000', 500_000)
        elif name == 'rapid':
            for index in range(5):
                transfer(f'Transfer {index + 1} of 5 · ₹100', 10_000)
        elif name == 'rollback':
            transfer('Injected failure · ₹100', 10_000, fail=True)
        elif name == 'duplicate':
            transfer('First submission · ₹100', 10_000, key='presentation-same-request')
            transfer('Retry with same request key', 10_000, key='presentation-same-request')

        after = database.accounts()
        history = database.history()
        failures = database.failures()
        connection = database.connect()
        try:
            alerts = [dict(row) for row in connection.execute(
                'SELECT rule, reason, transaction_id FROM fraud_alerts ORDER BY id')]
        finally:
            connection.close()
        context = None
        if history:
            connection = database.connect()
            try:
                transaction = connection.execute('SELECT * FROM transactions WHERE id=?',
                                                 (last_transaction_id,)).fetchone()
                context = transfer_review_context(connection, transaction)
            finally:
                connection.close()
        rules = {alert['rule'] for alert in alerts}
        balances = {account['id']: account['balance_paise'] for account in after}
        original = {account['id']: account['balance_paise'] for account in before}
        checks = {
            'normal': [
                ('One durable ledger row', len(history) == 1),
                ('₹100 debited and credited', balances[1] == original[1] - 10_000 and balances[2] == original[2] + 10_000),
                ('No review alert', not alerts),
            ],
            'high_value': [
                ('One durable ledger row', len(history) == 1),
                ('High-value rule alert created', 'high_value' in rules),
                ('No unrelated alert created', rules == {'high_value'}),
            ],
            'rapid': [
                ('Five durable ledger rows', len(history) == 5),
                ('Rapid-activity rule alert created', 'rapid_activity' in rules),
                ('Total balances conserved', sum(balances.values()) == sum(original.values())),
            ],
            'rollback': [
                ('Balances restored', balances == original),
                ('No committed ledger row', not history),
                ('Failed attempt audited', len(failures) == 1),
            ],
            'duplicate': [
                ('One durable ledger row after two submissions', len(history) == 1),
                ('₹100 debited only once', balances[1] == original[1] - 10_000),
                ('Second request replayed', replayed),
            ],
        }[name]
        return {'scenario': name, **SCENARIOS[name], 'before': before, 'after': after,
                'ledger_count': len(history), 'failure_count': len(failures),
                'alerts': alerts, 'context': context, 'runs': runs, 'error': error,
                'replayed': replayed, 'checks': checks,
                'passed': all(passed for _, passed in checks)}
