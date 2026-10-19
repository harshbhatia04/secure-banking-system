# GEU Banking System — Concurrent Banking Transaction System

University OS + DBMS project with a local banking GUI, concurrency demonstrations, explainable rule-based alerts, and a lightweight AI fraud-risk score. Python 3.10+ and Flask 3.1.2 are required for the web interface.

## Show the professor: web interface

From PowerShell in this project folder:

```powershell
.\run.ps1 -Web
```

Open `http://127.0.0.1:5000` in a browser. Sign in as `admin` or `harsh` with `Demo@2026!`. The login page also lists all demo usernames. Admin sees the risk desk and concurrency lab; customer users see their own balance, transfer form and activity. Change the shared demo password before first web launch by setting `PBL_DEMO_PASSWORD` in the shell if needed; existing password hashes are not reset on restart.

For a different computer, create a Python virtual environment, install `requirements.txt`, then run `python web_app.py`. The web server listens on loopback only and uses the same `data/banking.db` as the CLI. The repository's `run.ps1` uses the local `.venv` when present. **The CLI intentionally has no login or customer authorization**, so use the GUI for the role/security demonstration.

Suggested live sequence: customer transfer → customer activity → admin risk desk → admin concurrency lab → run live demo. A transfer of ₹5,000 triggers a high-value alert. Five transfers from one account within 60 seconds trigger rapid-activity alerts; three failed outgoing operations within five minutes trigger a failure alert. The admin can mark an alert reviewed. The lab runs on a separate temporary database, so it cannot change the live customer balances.

The interface takes its navigation layout and finance-dashboard cues from the PayFlow project in `Desktop/New folder/PayFlow-UPI-Management-System`. The GUI, branding, styles, routes and banking data in this repository are implemented separately. The reference also suggested distinct customer/admin views and visible fraud reasons. UPI-specific features were left out because this proposal concerns bank-account transactions.

## CLI and automated demonstrations

Open PowerShell in this project folder:

```powershell
.\run.ps1 init
.\run.ps1 accounts
.\run.ps1 transfer 1 2 250.50
.\run.ps1 history
.\run.ps1 simulate --workers 20 --operations 100 --mode transfer
.\run.ps1 deadlock-demo
.\run.ps1 race-demo
.\run.ps1 -Tests
.\run.ps1 -Demo
```

The launcher uses `.venv` if present, then the Codex bundled Python on this computer, then `python` from PATH. If script execution is restricted, use an installed Python directly: `python app.py init`. The CLI requires only the standard library, but `-Tests` also runs web tests and therefore needs Flask installed.

On any computer with Python 3.10+:

```text
python app.py init
python app.py deposit 1 100
python app.py withdraw 1 50
python app.py transfer 1 2 250.50
python app.py simulate --workers 20 --operations 100
python -m unittest discover -s tests -v
python demo.py
```

`init` creates three accounts with INR 10,000 each. Re-running it preserves existing balances. The default database is `data/banking.db`; use `--db` BEFORE the command to use a different one, for example `python app.py --db data/practice.db init`.

CLI amounts are **rupees**. Python service methods and JSON fields ending in `_paise` use **integer paise**: `250.50` rupees becomes `25050` paise. IDs 1, 2 and 3 are the demo accounts.

## What is implemented

- SQLite schema, foreign keys, nonnegative balances and exact integer money.
- Deposits, withdrawals, transfers, validation, insufficient-funds rejection and frozen accounts.
- Atomic balance updates and a successful transaction record in the same database transaction.
- Failure injection after debit, rollback, and separate failed-attempt auditing.
- Per-account Python mutexes shared by service instances, sorted lock acquisition, bounded lock waits and cleanup.
- Threaded simulator with a coordinated start, private database connections, completion checks and accounting measurements.
- Request-key idempotency: repeating the same request does not move money twice.
- Bounded deadlock demonstration and deterministic lost-update demonstration using dummy data.
- Automated tests, a repeatable demo, architecture/ER diagrams and viva notes.

The web interface includes password-hashed demo logins, customer/admin roles, account ownership checks, CSRF-protected forms, five-attempt login throttling, fraud alerts, and the concurrency lab. A separate logistic-regression prototype was trained from the public **BankSim** simulated bank-payment dataset: 472,365 earlier-day rows for training and 122,278 later-day rows held out for evaluation. Its inputs are amount, earlier payments from the same customer that day, and whether the recipient is new. The fitted parameters and evaluation are stored in `data/banksim_model.json`; run `python ai_fraud.py` to inspect them. This local prototype is not used to score live web transfers because its BankSim scores are not calibrated for INR bank-account activity. Login attacks are handled separately by a failed-login rule; BankSim was **not** used to train a login detector. The CLI is a trusted educational tool and does not authenticate users.

To reproduce training, run `python train_fraud_model.py --download` once. This downloads the 48 MB BankSim CSV to the ignored `data/external/` directory and rebuilds `data/banksim_model.json`; restart the web server afterward. Training requires `scikit-learn`, included in `requirements.txt`, while normal web serving uses only Flask and Python's standard library. See `docs/fraud_model.md` for the source, license, test metrics, and domain limits.

For an interim external AI review, run `.\run.ps1 -Web -Groq`. On this Windows account, the launch script loads the Groq key from the ignored, Windows-encrypted `data/.groq_key.dpapi` file. If the file is absent, it prompts for a key without echoing it. The Groq demo starts at `http://127.0.0.1:5001/` so the local site on port 5000 can stay open. Alternatively, set `GROQ_API_KEY` in the server's environment and restart the site. The default hosted model is `openai/gpt-oss-20b` (override with `GROQ_MODEL`). Groq reviews committed transfers and labels any resulting alert `groq_review`. If it is unavailable, the deterministic rules still run and the transfer remains committed; the local BankSim prototype is not a live fallback. Never put the API key in Git or the ZIP. See `docs/fraud_model.md` for the data sent and limitations.

## Demonstrate rollback

```powershell
.\run.ps1 accounts
.\run.ps1 transfer 1 2 500 --fail-after-debit
.\run.ps1 accounts
.\run.ps1 failures
```

The transfer prints an expected error and returns exit code 1. Both account balances stay unchanged. No successful transfer is recorded. The failure is logged after rollback in a separate transaction. Malformed inputs are rejected before execution and are not persisted. If database contention also prevents failure auditing, the error includes an `audit_warning` rather than claiming it was saved.

## Demonstrate duplicate-request protection

```powershell
.\run.ps1 transfer 1 2 100 --request-key presentation-001
.\run.ps1 transfer 1 2 100 --request-key presentation-001
```

The second result has `replayed: true` and the same transaction ID. Reusing that key for a different amount or operation is rejected. Failed requests have no committed transaction and can be retried.

## Concurrency and deadlocks

Each client is a real Python thread. Account operations acquire Python mutexes in ascending account-ID order. A transfer acquires both locks; a deposit or withdrawal acquires one. A shared registry ensures that separate service objects in one process use the same mutexes.

After acquiring account locks, each worker opens its own SQLite connection and executes `BEGIN IMMEDIATE` before reading balances. SQLite serializes writers across connections and processes. This is a database write reservation, **not PostgreSQL-style row locking**. There is no `SELECT FOR UPDATE` in this implementation. WAL permits reader/writer overlap but still only one writer. Extra threads may make the workload slower.

Python locks demonstrate critical sections and ordered locking within one process. The database transaction protects persistent consistency even when Python lock registries are independent. All money mutations must go through the transaction service; direct SQL can bypass application-level validation.

The lock order is always: sorted account locks, then database write transaction. Database connections close and account locks release on success and failure. There is a five-second account-lock budget and a five-second SQLite busy timeout by default. Failure logging may need a further database wait. No unbounded automatic retries are used.

`deadlock-demo` intentionally takes A then B in one thread, B then A in another. Barriers ensure both first locks are held. Both second acquisitions time out; the dummy locks are then released. It demonstrates circular waiting and recovery, not a general deadlock detector. Normal transfers prevent this circular wait with ordered locking. The race demonstration uses a barrier to force two threads to read the same old balance before writing; the corrected version uses a mutex.

## Tests and recorded results

`python -m unittest discover -s tests -v` runs the automated suite in temporary databases. `python demo.py` runs six presentation scenarios and eight measured workloads, saving `docs/test_results.json` and `docs/test_results.md`. It does not alter the normal banking database.

Run the simulator on an otherwise idle database: unrelated transactions during its before/after measurements would affect its accounting check. A fixed seed reproduces requested operations, not thread scheduling. General workloads can legitimately reject operations; accounting includes only successful deposits and withdrawals.

See `docs/architecture.md` for design and ER diagrams, `docs/demo_guide.md` for the presentation, and `docs/plan.md` for milestone status.
