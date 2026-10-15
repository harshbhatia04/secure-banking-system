# Presentation guide: approximately 8 minutes

Start `.\run.ps1 -Web` and open `http://127.0.0.1:5000`. Log in as `harsh` / `Demo@2026!`, show the customer dashboard, perform a transfer, then sign out and use `admin` / `Demo@2026!`. Show the risk desk and run the concurrency lab. The lab uses temporary databases. For recorded benchmark numbers, run `python demo.py` or `.\run.ps1 -Demo`.

For a clean GUI demonstration, use these exact actions:

1. Sign in as `harsh`. On **Move money**, choose transfer from account 1 to account 2 for ₹5,000. Return to Overview and Activity; balances and the committed record should agree.
2. Sign out and sign in as `admin`. On **Risk desk**, show both the `High Value` rule alert and the `AI Risk` alert. Explain that the AI score comes from a local logistic-regression model trained on the public BankSim simulated-payment dataset. It uses amount, earlier same-day outgoing activity and whether the recipient is new. Show the labelled dataset source and held-out metrics in `docs/fraud_model.md`, then mark an alert reviewed.
3. Open **Concurrency lab** and click **Run live demo**. Watch the live lock rows: green names hold account locks and amber names wait. The wait-for graph draws arrows from real waiting workers to the current lock holder. The event stream records each request, acquisition, release, and commit. The short lock delay is only for visibility in this isolated demonstration.
4. When the run completes, point to the lost update (100 vs 200), the separately forced two-lock deadlock that ends by timeout, 50/50 committed transfers with a constant total, and unchanged balances after injected rollback. Real transfers acquire account locks in increasing ID order, so the live transfer graph should have no cycle.
5. Explain that the lab uses a separate temporary database. The ordinary banking database is unaffected by this demonstration.

If account 1 has already spent too much for the ₹5,000 example, make a simulated deposit first, or use any account with sufficient balance while signed in as admin. The GUI never creates actual financial transactions.

For a live walkthrough:

1. Show `docs/architecture.md` and `schema.sql`. Explain users, accounts and committed transactions. Amounts are integer paise.
2. Run `.\run.ps1 init` and `.\run.ps1 accounts`. Show three sample accounts; initialization preserves any existing balances.
3. Run `.\run.ps1 transfer 1 2 100`, then `accounts` and `history`. Explain atomic debit, credit and transaction record.
4. Record balances, then run `.\run.ps1 transfer 1 2 100 --fail-after-debit`. This command is expected to return an error. Show unchanged balances and the separate `failures` record.
5. Run `.\run.ps1 race-demo`. Expected result is 100 without the mutex, 200 with it; both workers were supposed to add 100.
6. Run `.\run.ps1 deadlock-demo`. Show both threads holding one lock and timing out on the other. Explain how sorted account IDs remove circular wait in the real transfer service.
7. Run `.\run.ps1 simulate --workers 20 --operations 100 --mode transfer`. Check `workers_finished`, `accounting_correct`, and `all_operations_accounted_for` are true; total money stays constant.
8. Show `docs/test_results.md` and `.\run.ps1 -Tests`. Discuss SQLite's single-writer limit, the login/role checks, and rule-based fraud alerts.

## Viva questions

**What is the critical section?** Reading and validating account balances, updating balances, and committing their transaction record while protecting the affected accounts.

**What is a race condition?** A result that depends on an unsafe interleaving. Two threads can read the same old balance and overwrite each other's update.

**What are the four deadlock conditions?** Mutual exclusion, hold-and-wait, no preemption, and circular wait. Ordered lock acquisition eliminates circular wait for these account locks. Timeouts provide a bounded escape if an unexpected wait occurs; a timeout by itself does not prove a deadlock.

**Why both Python locks and database transactions?** Python mutexes demonstrate thread synchronization within one process. Database transactions provide rollback and persistent consistency, including between processes that do not share Python memory.

**Does the GIL protect account balances?** No. A multi-step read/check/write sequence is not made atomic by the GIL, and database I/O allows other threads to run.

**Why separate database connections?** Each worker owns its transaction lifecycle; workers must not accidentally commit or roll back each other's work.

**Does SQLite lock individual account rows?** No. `BEGIN IMMEDIATE` reserves its single writer. Python has account-level mutexes, but database writes are serialized. PostgreSQL row locking is a later option.

**How do you test conservation of money?** Transfers preserve the total. Mixed workloads must satisfy final total = initial total + successful deposits - successful withdrawals.

**Does a fraud alert mean a rejected transaction?** No. A committed transfer can be flagged as suspicious. Failed and unauthorized attempts are logged separately and can also create alerts.

**Where is the AI training data?** BankSim's labelled CSV is stored at `data/external/banksim.csv` on this demo computer. It has 594,643 rows and a `fraud` label. Run `python ai_fraud.py` to show the training count, later-day test count, and model metrics. Run `python train_fraud_model.py --download` to fetch it and retrain on another computer. The resulting small `data/banksim_model.json` is what the website loads; the training CSV is separate from the live SQLite banking database.

**Is the AI model a real bank fraud model?** It is trained and evaluated on a public, labelled **simulated** bank-payment dataset, not on this bank's real transfer or login records. Its 83.6% precision and 51.5% recall at the 50% threshold apply only to the held-out BankSim days. Currency and payment behavior differ from this INR transfer app, so its displayed scores are teaching examples, not reliable real-world probabilities.

**Does AI detect failed logins too?** No. Five failed logins in five minutes cause a separate security-rule alert and temporary throttle. BankSim contains payments, not authentication events, so claiming this model learned login attacks would be inaccurate. See `docs/fraud_model.md` for the dataset boundary.

**Does this implement starvation prevention?** No strict fairness guarantee is claimed for Python locks. Waits are bounded and failures are surfaced. A fair queue could be investigated later.
