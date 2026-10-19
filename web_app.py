"""Local Flask interface for the concurrent banking demonstration."""
from functools import wraps
import argparse
from decimal import Decimal
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import threading

from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for

from app import parse_money
from client_sim import run_simulation
from concurrency_manager import deadlock_demo, race_demo
from database import Database
from demo_studio import SCENARIOS, run_scenario
from fraud_detector import record_unauthorized, scan_failed_attempt, scan_failed_login, scan_transaction, transfer_review_context
from groq_fraud import GroqFraudError, configured as groq_configured, scan_groq_risk
from lab_monitor import LabMonitor
from security import DEMO_PASSWORD, authenticate, secret_key_for, seed_demo_users
from transaction_manager import BankingError, TransactionManager
from transaction_trace import TransactionTrace


def create_app(database_path=None):
    app = Flask(__name__)
    database = Database(database_path or os.environ.get('PBL_DB', 'data/banking.db'))
    database.initialize()
    database.seed()
    seed_demo_users(database)
    manager = TransactionManager(database)
    lab_monitor = LabMonitor()
    app.secret_key = secret_key_for(database)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=False, MAX_CONTENT_LENGTH=64 * 1024)
    app.config['DATABASE'] = database
    app.config['MANAGER'] = manager
    app.config['LAB_MONITOR'] = lab_monitor

    def rows(sql, params=()):
        connection = database.connect()
        try:
            return [dict(row) for row in connection.execute(sql, params)]
        finally:
            connection.close()

    def present_alerts(records):
        """Keep provider/model provenance in SQLite while using concise UI labels."""
        for alert in records:
            alert['display_rule'] = alert['rule'].replace('_', ' ').title()
            alert['display_reason'] = alert['reason']
            if alert['rule'] == 'groq_review':
                alert['display_rule'] = 'Intelligence review'
                match = re.fullmatch(r'Groq AI review \([^)]*, (low|medium|high)\): (.+)',
                                     alert['reason'])
                if match:
                    alert['display_reason'] = f'{match.group(1).title()} concern: {match.group(2)}'
                elif alert['reason'].lower().startswith('groq'):
                    alert['display_reason'] = 'Manual review suggested by the configured service.'
            elif alert['rule'] == 'ai_risk':
                alert['display_rule'] = 'Legacy AI review'
                alert['display_reason'] = 'Archived signal from a previous detector; it is not used for new transfers.'
        return records

    def money(amount_paise):
        return f'₹{Decimal(amount_paise) / 100:,.2f}'

    app.jinja_env.filters['money'] = money

    @app.before_request
    def load_identity_and_check_csrf():
        g.user = None
        user_id = session.get('user_id')
        if type(user_id) is int:
            matches = rows('SELECT id, name, username, role FROM users WHERE id = ?', (user_id,))
            if matches:
                g.user = matches[0]
        if request.method == 'POST':
            expected = session.get('csrf_token')
            received = request.form.get('csrf_token', '')
            if not expected or not secrets.compare_digest(expected, received):
                abort(400, description='Form expired. Refresh the page and try again.')

    @app.context_processor
    def context():
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_urlsafe(32)
        return {'current_user': g.user, 'csrf_token': session['csrf_token']}

    def login_required(function):
        @wraps(function)
        def guarded(*args, **kwargs):
            if g.user is None:
                return redirect(url_for('login'))
            return function(*args, **kwargs)
        return guarded

    def admin_required(function):
        @wraps(function)
        @login_required
        def guarded(*args, **kwargs):
            if g.user['role'] != 'admin':
                abort(403)
            return function(*args, **kwargs)
        return guarded

    def owned_accounts():
        if g.user['role'] == 'admin':
            return database.accounts()
        return rows('SELECT a.id, u.name, a.balance_paise, a.status FROM accounts a JOIN users u ON u.id = a.user_id WHERE a.user_id = ? ORDER BY a.id',
                    (g.user['id'],))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if g.user:
            return redirect(url_for('dashboard'))
        if request.method == 'POST':
            username = request.form.get('username', '').strip().lower()
            password = request.form.get('password', '')
            if len(username) > 80 or len(password) > 256:
                flash('Invalid login details.', 'error')
            else:
                user, error = authenticate(database, username, password)
                if user:
                    session.clear()
                    session['user_id'] = user['id']
                    session['csrf_token'] = secrets.token_urlsafe(32)
                    return redirect(url_for('dashboard'))
                if error != 'Too many attempts. Try again in five minutes.':
                    scan_failed_login(database, username)
                flash(error, 'error')
        return render_template('login.html', demo_password=DEMO_PASSWORD)

    @app.post('/logout')
    @login_required
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.get('/')
    @login_required
    def dashboard():
        accounts = owned_accounts()
        ids = [item['id'] for item in accounts]
        if g.user['role'] == 'admin':
            recent = rows('SELECT t.*, us.name AS source_name, ud.name AS destination_name FROM transactions t '
                          'LEFT JOIN accounts sa ON sa.id=t.source_id LEFT JOIN users us ON us.id=sa.user_id '
                          'LEFT JOIN accounts da ON da.id=t.destination_id LEFT JOIN users ud ON ud.id=da.user_id '
                          'ORDER BY t.id DESC LIMIT 8')
            stats = {'transactions': rows('SELECT count(*) AS n FROM transactions')[0]['n'],
                     'alerts': rows('SELECT count(*) AS n FROM fraud_alerts WHERE reviewed=0')[0]['n'],
                     'failures': rows('SELECT count(*) AS n FROM failed_attempts')[0]['n']}
        else:
            recent = rows('SELECT * FROM transactions WHERE source_id IN '
                          '(SELECT id FROM accounts WHERE user_id=?) OR destination_id IN '
                          '(SELECT id FROM accounts WHERE user_id=?) ORDER BY id DESC LIMIT 8',
                          (g.user['id'], g.user['id']))
            stats = {'transactions': len(rows('SELECT id FROM transactions WHERE source_id IN '
                        '(SELECT id FROM accounts WHERE user_id=?) OR destination_id IN '
                        '(SELECT id FROM accounts WHERE user_id=?)', (g.user['id'], g.user['id']))),
                     'alerts': rows('SELECT count(*) AS n FROM fraud_alerts WHERE user_id=? AND reviewed=0',
                                    (g.user['id'],))[0]['n'],
                     'failures': rows('SELECT count(*) AS n FROM failed_attempts WHERE source_id IN '
                                      '(SELECT id FROM accounts WHERE user_id=?)', (g.user['id'],))[0]['n']}
        return render_template('dashboard.html', accounts=accounts, account_ids=ids, recent=recent,
                               total=sum(row['balance_paise'] for row in accounts), stats=stats)

    @app.route('/transfer', methods=['GET', 'POST'])
    @login_required
    def transfer():
        accounts = owned_accounts()
        all_accounts = database.accounts()
        if request.method == 'POST':
            trace = TransactionTrace()
            operation = request.form.get('operation', 'transfer')
            try:
                if operation not in ('transfer', 'deposit', 'withdraw'):
                    raise ValueError('Choose a valid operation')
                source = int(request.form.get('source_id', '0'))
                if source not in {row['id'] for row in accounts}:
                    record_unauthorized(database, g.user['id'], source)
                    abort(403)
                amount = parse_money(request.form.get('amount', ''))
                key = request.form.get('request_key', '').strip() or None
                trace.record('FLASK', 'request_accepted',
                             f'Authenticated user #{g.user["id"]} submitted {operation} of {amount} paise from account #{source}')
                if operation == 'transfer':
                    destination = int(request.form.get('destination_id', '0'))
                    result = manager.transfer(source, destination, amount, request_key=key, trace=trace)
                elif operation == 'deposit':
                    result = manager.deposit(source, amount, request_key=key, trace=trace)
                else:
                    result = manager.withdraw(source, amount, request_key=key, trace=trace)
                ai_unavailable = False
                try:
                    trace.record('RISK', 'rules_started', 'Started post-commit fraud rules on the saved ledger row')
                    alerts = scan_transaction(database, result.transaction_id, g.user['id'])
                    trace.record('RISK', 'rules_finished', f'Fraud rules saved {len(alerts)} review alert(s)')
                    if not result.replayed:
                        if groq_configured():
                            try:
                                trace.record('RISK', 'api_started', 'Started configured AI API review')
                                ai_alerts = scan_groq_risk(database, result.transaction_id, g.user['id'])
                                alerts.extend(ai_alerts)
                                trace.record('RISK', 'api_finished', f'AI API review saved {len(ai_alerts)} alert(s)')
                            except GroqFraudError as exc:
                                app.logger.warning('Groq review unavailable: %s', exc)
                                trace.record('RISK', 'api_unavailable', 'AI API unavailable; rule checks still completed')
                                ai_unavailable = True
                        else:
                            trace.record('RISK', 'api_not_configured', 'No AI API configured; rule checks still completed')
                except (sqlite3.Error, ValueError):
                    app.logger.exception('Fraud scan failed after committed transaction %s', result.transaction_id)
                    trace.record('RISK', 'scan_failed', 'Fraud scan failed after the banking COMMIT')
                    flash('Transaction completed, but its fraud check could not be recorded. Ask the administrator to review it.', 'error')
                else:
                    flash(('Request already processed.' if result.replayed else 'Transaction completed.') +
                          (f' {len(alerts)} review alert(s) created.' if alerts else '') +
                          (' Intelligence review was unavailable; rule checks still ran.' if ai_unavailable else ''),
                          'success')
                if not result.replayed:
                    try:
                        trace.save(database, result.transaction_id)
                    except sqlite3.Error:
                        app.logger.exception('Could not save runtime trace for transaction %s', result.transaction_id)
                        flash('Transaction completed, but its runtime log could not be saved.', 'error')
                if result.replayed:
                    session.pop('success_animation_tx', None)
                else:
                    session['success_animation_tx'] = result.transaction_id
                return redirect(url_for('transaction_detail', transaction_id=result.transaction_id))
            except BankingError as exc:
                if operation in ('transfer', 'withdraw') and 'source' in locals() and source in {row['id'] for row in accounts}:
                    scan_failed_attempt(database, g.user['id'], source)
                flash(str(exc), 'error')
            except (ValueError, TypeError, argparse.ArgumentTypeError) as exc:
                flash(str(exc), 'error')
        selected_destination = next((row['id'] for row in all_accounts
                                     if not accounts or row['id'] != accounts[0]['id']), None)
        return render_template('transfer.html', accounts=accounts, all_accounts=all_accounts,
                               selected_destination=selected_destination)

    @app.get('/activity')
    @login_required
    def activity():
        if g.user['role'] == 'admin':
            transactions = rows('SELECT * FROM transactions ORDER BY id DESC LIMIT 100')
            failures = rows('SELECT * FROM failed_attempts ORDER BY id DESC LIMIT 30')
        else:
            transactions = rows('SELECT * FROM transactions WHERE source_id IN '
                '(SELECT id FROM accounts WHERE user_id=?) OR destination_id IN '
                '(SELECT id FROM accounts WHERE user_id=?) ORDER BY id DESC LIMIT 100',
                (g.user['id'], g.user['id']))
            failures = rows('SELECT * FROM failed_attempts WHERE source_id IN '
                '(SELECT id FROM accounts WHERE user_id=?) ORDER BY id DESC LIMIT 30', (g.user['id'],))
        return render_template('activity.html', transactions=transactions, failures=failures,
                               own_ids={row['id'] for row in owned_accounts()})

    @app.get('/activity/<int:transaction_id>')
    @login_required
    def transaction_detail(transaction_id):
        matches = rows('SELECT t.*, us.name AS source_name, ud.name AS destination_name '
                       'FROM transactions t '
                       'LEFT JOIN accounts sa ON sa.id=t.source_id '
                       'LEFT JOIN users us ON us.id=sa.user_id '
                       'LEFT JOIN accounts da ON da.id=t.destination_id '
                       'LEFT JOIN users ud ON ud.id=da.user_id '
                       'WHERE t.id=?', (transaction_id,))
        if not matches:
            abort(404)
        transaction = matches[0]
        own_ids = {account['id'] for account in owned_accounts()}
        if g.user['role'] != 'admin' and not ({transaction['source_id'], transaction['destination_id']} & own_ids):
            abort(403)
        can_view_alerts = g.user['role'] == 'admin' or transaction['source_id'] in own_ids
        alerts = present_alerts(rows('SELECT rule, reason, reviewed FROM fraud_alerts WHERE transaction_id=? ORDER BY id',
                                     (transaction_id,))) if can_view_alerts else []
        review_context = None
        if g.user['role'] == 'admin' and transaction['operation'] == 'transfer':
            connection = database.connect()
            try:
                review_context = transfer_review_context(connection, transaction)
            finally:
                connection.close()
        trace_events = rows('SELECT sequence, occurred_at, elapsed_ms, process_id, native_thread_id, '
                            'component, action, message, account_id, duration_ms '
                            'FROM transaction_events WHERE transaction_id=? ORDER BY sequence', (transaction_id,))
        acquired_lock_ids = [event['account_id'] for event in trace_events
                             if event['action'] == 'lock_acquired']
        lock_wait_count = sum(event['action'] == 'lock_waiting' for event in trace_events)
        writer_wait_ms = next((event['duration_ms'] for event in trace_events
                               if event['action'] == 'begin_immediate'), None)
        groq_alert = next((alert for alert in alerts if alert['rule'] == 'groq_review'), None)
        risk_actions = {event['action'] for event in trace_events if event['component'] == 'RISK'}
        if groq_alert:
            review_status = 'groq_alert'
        elif 'api_finished' in risk_actions:
            review_status = 'groq_clear'
        elif 'api_unavailable' in risk_actions:
            review_status = 'api_unavailable'
        elif 'local_model_finished' in risk_actions:
            review_status = 'legacy_local'
        else:
            review_status = 'rules_only'
        lock_order = sorted(account_id for account_id in
                            (transaction['source_id'], transaction['destination_id']) if account_id is not None)
        show_success_animation = session.get('success_animation_tx') == transaction_id
        if show_success_animation:
            session.pop('success_animation_tx', None)
        return render_template('transaction_detail.html', transaction=transaction,
                               alerts=alerts, lock_order=lock_order, can_view_alerts=can_view_alerts,
                               show_success_animation=show_success_animation, trace_events=trace_events,
                               acquired_lock_ids=acquired_lock_ids, lock_wait_count=lock_wait_count,
                               writer_wait_ms=writer_wait_ms, review_context=review_context,
                               review_status=review_status)

    @app.get('/lab')
    @admin_required
    def lab():
        report_path = Path(__file__).parent / 'docs' / 'test_results.json'
        report = json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else None
        return render_template('lab.html', report=report)

    @app.get('/lab/api/state')
    @admin_required
    def lab_state():
        response = jsonify(lab_monitor.snapshot())
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/lab/run')
    @admin_required
    def run_lab():
        if lab_monitor.start():
            def work():
                try:
                    lab_monitor.set_stage('Demonstrating a lost update')
                    race = race_demo()
                    lab_monitor.set_stage('Forcing circular wait on two dummy locks')
                    deadlock = deadlock_demo(timeout=0.7, observer=lab_monitor.demo_event)
                    with tempfile.TemporaryDirectory(prefix='banking-web-lab-') as directory:
                        isolated = Database(Path(directory) / 'lab.db')
                        isolated.initialize()
                        isolated.seed()
                        isolated_manager = TransactionManager(isolated)
                        lab_monitor.set_stage('Injecting failure after debit')
                        before = isolated.accounts()
                        rollback_failed = False
                        try:
                            isolated_manager.transfer(1, 2, 100, simulate_failure=True)
                        except BankingError:
                            rollback_failed = True
                        rollback = {'passed': rollback_failed and before == isolated.accounts() and not isolated.history(),
                                    'balances_unchanged': before == isolated.accounts(),
                                    'committed_records': len(isolated.history()),
                                    'failed_records': len(isolated.failures())}
                        lab_monitor.set_stage('Running 50 transfers on 10 Python threads')
                        isolated_manager.locks.observer = lab_monitor.lock_event
                        isolated_manager.locks.visualization_delay = 0.025
                        isolated_manager.observer = lab_monitor.transaction_event
                        sample = run_simulation(isolated_manager, workers=10, operations=50, mode='transfer')
                    lab_monitor.finish({'sample': sample, 'deadlock': deadlock,
                                        'race': race, 'rollback': rollback})
                except Exception as exc:
                    app.logger.exception('Concurrency lab failed')
                    lab_monitor.finish(error=exc)
            threading.Thread(target=work, name='lab-runner', daemon=True).start()
            flash('Lab started. Watch the thread and lock monitor below.', 'success')
        else:
            flash('A lab run is already in progress.', 'error')
        return redirect(url_for('lab'))

    @app.get('/admin')
    @admin_required
    def admin():
        alerts = present_alerts(rows('SELECT f.*, u.name AS user_name FROM fraud_alerts f LEFT JOIN users u ON u.id=f.user_id '
                                     'ORDER BY f.id DESC LIMIT 100'))
        users = rows('SELECT id, name, username, role FROM users ORDER BY id')
        login_failures = rows('SELECT username, created_at FROM login_attempts WHERE success=0 '
                              'ORDER BY id DESC LIMIT 20')
        login_counts = rows("SELECT username, count(*) AS attempts FROM login_attempts WHERE success=0 "
                            "AND created_at >= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-5 minutes') "
                            'GROUP BY username ORDER BY attempts DESC, username')
        return render_template('admin.html', alerts=alerts, users=users,
                               accounts=database.accounts(), failures=database.failures()[-8:][::-1],
                               login_failures=login_failures, login_counts=login_counts,
                               groq_enabled=groq_configured())

    @app.route('/admin/demo', methods=['GET', 'POST'])
    @admin_required
    def admin_demo():
        result = None
        if request.method == 'POST':
            scenario = request.form.get('scenario', '')
            if scenario not in SCENARIOS:
                abort(400, description='Choose a valid demo scenario.')
            result = run_scenario(scenario)
        response = render_template('demo_studio.html', scenarios=SCENARIOS, result=result)
        return response

    @app.post('/admin/alerts/<int:alert_id>/review')
    @admin_required
    def review_alert(alert_id):
        connection = database.connect()
        try:
            cursor = connection.execute('UPDATE fraud_alerts SET reviewed=1 WHERE id=?', (alert_id,))
            if cursor.rowcount == 0:
                abort(404)
        finally:
            connection.close()
        flash('Alert marked as reviewed.', 'success')
        return redirect(url_for('admin'))

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template('error.html', title='Access denied', message='This account cannot open that page.'), 403

    @app.errorhandler(400)
    def bad_request(error):
        return render_template('error.html', title='Request expired', message=error.description), 400

    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=int(os.environ.get('PBL_PORT', '5000')), debug=False, threaded=True)
