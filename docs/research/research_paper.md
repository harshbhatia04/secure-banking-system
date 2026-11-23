# Atomic Transfers and Observable Concurrency in a SQLite Banking Prototype

Harsh Bhatia &nbsp; | &nbsp; Tanisha Kapoor &nbsp; | &nbsp; Prakhar Garg

Graphic Era (Deemed to be University), Dehradun, India

Project Alpha / OSDBMS-V-2026-T234 &nbsp; | &nbsp; Research manuscript, 2 November 2026

## Abstract

A bank transfer can fail even when its debit and credit statements are individually valid: an interruption between them can leave an incomplete payment, while concurrent requests can act on stale balances. This paper presents a small Python and SQLite banking prototype that makes these problems observable. The implementation combines ordered account mutexes, explicit database transactions, persistent request keys and separate records for failed attempts. A Flask interface exposes customer operations, administrative review and a concurrency laboratory. Evaluation on a local Windows machine included 45 automated tests and 24 repeated workloads containing 2,400 operations. All tests passed; every workload preserved its accounting invariant and completed without rejected operations. Transfer-only timings did not show a consistent improvement as the worker count increased. A separate re-evaluation of a saved BankSim classifier produced average precision of 0.6926 and recall of 51.52% at a 0.5 threshold. The work provides a reproducible teaching case connecting operating-system synchronization, database transactions and cautious interpretation of fraud alerts. It does not establish production readiness or detection performance on real customer payments.

Keywords: atomic transactions; SQLite; thread synchronization; idempotency; banking simulation; fraud review.

## 1. Introduction

Consider two withdrawals that both read an account balance before either updates it. Without a protected check-and-update sequence, each request may appear affordable even though their combined amount is not. Transfers add a second failure point because money must leave one account and reach another as one unit. Our project uses these concrete cases to connect OS concepts such as mutual exclusion and circular wait with DBMS concepts such as constraints, commit and rollback.

The study asks three questions: RQ1, do the tested concurrent and failure paths preserve the intended accounting rules? RQ2, how does completion time change between one and twenty worker threads? RQ3, what evidence supports the system's fraud-review features? Its contribution is the implementation, observable demonstrations and reproducible evaluation of established techniques, rather than a new locking algorithm.

## 2. Background and related work

Berenson et al. [1] explain why isolation must be understood through the anomalies a schedule permits. This motivates explicit checks of balances, rollback and duplicate requests in our evaluation. SQLite documents serialized writes and the writer reservation obtained by BEGIN IMMEDIATE [2]; this is the database mechanism used here. Python provides the mutex and timeout primitives for the process-local account layer [3]. BankSim [4] supplies a separate synthetic-data setting for classification. Saito and Rehmsmeier [5] motivate examining precision and recall when the positive class is rare. These sources support the design choices; our measurements concern only the local implementation described below.


---

## 3. System architecture and transaction protocol

Figure 1. Implemented components and execution boundaries. Solid arrows show the main request/storage path. The BankSim experiment has no connection to the current live transfer path.

### 3.1 Data representation and access boundaries

Balances and amounts use integer paise. Users own accounts; successful transactions have unique request keys. Schema checks reject negative balances and invalid operation/source/destination combinations. Failed attempts occupy a separate table so that their records survive payment rollback. Alerts, login attempts and execution events are also separate from the ledger.

Flask checks login state, role, account ownership and form tokens. The trusted CLI and simulator call the service directly. Each operation opens its own SQLite connection. The local database uses WAL mode, enabled foreign keys and synchronous FULL.

### 3.2 Transfer sequence

(1) Validate input. (2) Acquire account mutexes in ascending account-ID order with a bounded wait. (3) Open a connection and issue BEGIN IMMEDIATE. (4) Return the earlier result for an identical committed request key; reject conflicting reuse. (5) Read current account state, check status and funds, debit, credit and insert the ledger row. (6) Commit, close and release locks. An error within the database transaction triggers rollback; eligible failures are audited afterward in a separate transaction.

Manager objects in one process share mutexes by resolved database path. Ordered acquisition prevents circular wait among account locks: a thread cannot hold a higher-ID lock while awaiting a lower-ID lock. It does not guarantee fairness or bound the entire operation to the lock timeout. Independent processes rely on SQLite because they do not share Python mutexes.

### 3.3 Observation and review

Web traces record lock and database events, then persist after payment commit. Rule checks and optional Groq review also follow commit; alerts do not cancel payments. These records are not atomic with the payment. The laboratory uses temporary databases and dummy-memory race/deadlock examples.


---

## 4. Evaluation method

### 4.1 Accounting properties

Let B(t) be the sum of all account balances after the observed workload, D the sum of successful deposits and W the sum of successful withdrawals. Internal transfers should preserve the total, while a mixed workload should satisfy:

B(final) = B(initial) + D - W, with every account balance at least zero.

The simulator checks this equality, nonnegative balances, completed worker threads and whether every requested operation has a success or rejection outcome. Individual tests additionally inspect the ledger and failure records. For an injected error after the source debit, the expected outcome is unchanged balances and no committed payment row. For repeated identical request keys, exactly one payment should move money. These are checks of specific executions, not an exhaustive proof over all schedules.

### 4.2 Test scenarios

| Scenario | Observed assertion in the passing suite |
| --- | --- |
| Concurrent deposits | 100 deposits of INR 100 produce INR 20,000 from INR 10,000; the ledger contains 100 rows. |
| Competing withdrawals | 20 requests for INR 1,000 against INR 10,000 yield 10 successes and a zero closing balance. |
| Rollback and cleanup | Failure after debit restores both balances; no success row remains, and another thread can subsequently transfer. |
| Request replay | 20 concurrent uses of one request key yield one new payment; conflicting reuse is rejected. |
| Opposing transfers | Two threads each perform 25 transfers in opposite directions and restore the starting balances. |
| Separate lock registries | 40 concurrent deposits using independent mutex registries preserve the expected total through database serialization. |
| Web and review boundaries | Tests cover ownership, CSRF, roles, alert rules, trace receipts and mocked external-review failures. |

Table 1. Selected assertions from 45 passing tests. The independent-registry scenario uses threads in one process; it is not a multiprocess deployment test.

### 4.3 Workload and timing protocol

Each benchmark started with a new temporary database and three active accounts containing INR 10,000 each. There were 100 queued requests per run. Transfer-only workloads selected two distinct accounts and an integer amount from INR 1 to INR 100. Mixed workloads additionally selected deposit, withdrawal or transfer with equal probability. We tested 1, 5, 10 and 20 workers in both modes, with three repetitions per configuration. Workload seed 42 fixed the request sequence; configuration order was shuffled using seed 2026. Thread scheduling remained uncontrolled.

The environment was Python 3.12.14, SQLite 3.53.1, and Windows-11-10.0.26200-SP0. The processor identifier was Intel64 Family 6 Model 142 Stepping 12, GenuineIntel. The timer included worker creation, barrier synchronization and completion, but excluded schema creation, seeding and workload construction. Runs used the service directly without web tracing or external API calls. No background-load or power-state controls were applied. Mean time, sample standard deviation and mean per-run throughput are reported descriptively; three repetitions are too few for a strong performance claim.


---

## 5. Transaction and concurrency results

The automated suite completed 45 tests in 121.108 seconds with no failures. All 24 benchmark runs passed the accounting, nonnegative-balance and operation-completion checks. Across the runs, 2,400 requests succeeded and none were rejected; no unexpected errors or failure-audit warnings were reported. These workload results concern small, sufficiently funded operations. The separate withdrawal test in Table 1 exercises rejection under insufficient funds.

| Workload | Workers | Mean time (s) | Sample SD (s) | Mean ops/s |
| --- | --- | --- | --- | --- |
| Transfer | 1 | 3.865 | 0.365 | 26.02 |
| Transfer | 5 | 4.004 | 0.793 | 25.62 |
| Transfer | 10 | 3.673 | 0.732 | 28.03 |
| Transfer | 20 | 3.794 | 0.720 | 27.07 |
| Mixed | 1 | 3.823 | 1.252 | 28.02 |
| Mixed | 5 | 3.108 | 0.270 | 32.33 |
| Mixed | 10 | 3.218 | 0.758 | 32.42 |
| Mixed | 20 | 2.524 | 0.351 | 40.12 |

Table 2. Three runs per configuration; 100 operations per run. Throughput is the mean of the three individual run rates, so it need not equal 100 divided by the mean time.

Figure 2. Completion time for 100 requests. Error bars show one sample standard deviation across three repetitions, not confidence intervals.

For transfer-only workloads, mean completion time stayed between 3.67 and 4.00 seconds across worker counts. The small differences and overlapping variability provide no clear evidence of a throughput gain from more threads. Mixed workloads were faster at twenty workers than at one in this sample, but they did not improve monotonically at every intermediate count. The experiment does not isolate whether scheduling, disk activity, connection overhead or another factor caused these differences.

SQLite accepts one writer at a time [2], and the workload touches only three accounts, creating contention at the account layer as well. More submitted work therefore need not mean more simultaneous database updates. Ordered mutexes make the application's coordination visible; their performance benefit was not measured because the benchmark contains no comparison with that layer removed. The useful result here is preserved accounting under the tested schedules, rather than a scalability claim.


---

## 6. Fraud review and the offline BankSim experiment

### 6.1 Current website behavior

The live website records understandable rule alerts, including transfers of at least INR 5,000 and five transfers from the same source within sixty seconds. Additional checks cover repeated failed outgoing operations, repeated failed logins and unauthorized account access. These thresholds were chosen for the demonstration and have not been calibrated against real customer behavior. Rule activation tests establish that selected conditions trigger alerts; they do not measure fraud-detection accuracy.

If configured, an external Groq review receives transaction context and returns a concern category and explanation. Tests replace the remote service with controlled responses, including an error response. No live-provider accuracy, latency or availability experiment was performed. The current website does not fall back to the saved BankSim classifier when that service fails. Rule checks remain the local review mechanism, and the already committed payment is not reversed by a review failure.

### 6.2 Dataset, features and verification protocol

BankSim was developed to generate synthetic payment data for fraud research [4]. The local CSV contains 594,643 rows. The existing training code uses three inputs: log(1 + amount), the number of earlier payments for that customer on the same day capped at twenty, and whether the customer-merchant pair has appeared previously. Features are formed before updating the historical counters. Standardization is fitted on training rows, followed by logistic regression with a maximum of 1,000 iterations and random state 42.

The recorded temporal split contains 472,365 training rows with 5,880 fraud labels and 122,278 test rows with 1,320 fraud labels; the later period begins at step 147. For this paper, the saved coefficients were re-scored on that test period without refitting. A fresh scan found no decreasing day steps in file order, and the CSV SHA-256 matched the training artifact. This verifies the recorded calculation on the same holdout, rather than supplying a new independent test set. Within-day sequence follows CSV order; finer event chronology is unavailable in this evaluation.

| Holdout quantity | Verified value |
| --- | --- |
| Average precision | 0.6926 |
| Precision at score >= 0.5 | 83.64% |
| Recall at score >= 0.5 | 51.52% |
| True positives / false positives | 680 / 133 |
| False negatives / true negatives | 640 / 120,825 |

Table 3. Re-evaluation of the saved model on its original later-day BankSim holdout. These are offline scores, not website or real-bank accuracy.

Only about 1.08% of test rows carry a fraud label, making accuracy alone a poor summary: predicting every row as legitimate would already be about 98.92% accurate. Precision-recall analysis is more revealing in this setting [5]. Average precision aggregates precision over recall increments [6]. At the chosen threshold, 680 of 1,320 labelled fraud cases were detected and 640 were missed. The test therefore supports a limited screening experiment, not a claim that most fraud will be prevented. No new threshold tuning or probability calibration was performed.


---

## 7. Discussion and limitations

### 7.1 What the evidence supports

For RQ1, the selected tests and small concurrent workloads show the expected accounting behavior: the implementation does not retain the injected partial debit, spend beyond the tested available funds, or move money again for an identical committed request key. The database transaction is the boundary that groups balance changes with the successful ledger row. The account mutexes give the application an explicit coordination policy and a useful teaching trace. Their ordering argument applies only to that set of locks, not to every resource a future extension might acquire.

For RQ2, the transfer-only results are consistent with a system whose update path remains serialized despite additional worker threads. They do not identify a best worker count. A controlled follow-up should vary the number of accounts and operations, include several workload seeds, report operation-level latency percentiles and compare explicit account locking with database-only serialization. Longer runs and more repetitions would help separate startup and filesystem effects from sustained throughput.

For RQ3, the project has three different types of evidence. Rule tests check implementation behavior. Mocked external-review tests check integration behavior. The BankSim holdout measures one saved model on a synthetic distribution. None of these is a substitute for evaluating the actual website on representative labelled payments. In particular, the model's dataset-day count differs from a rolling twenty-four-hour website count, and its amount distribution has not been validated for the INR demonstration. This is why the offline result is presented separately.

### 7.2 Threats to validity

Coverage and schedule limits. A finite passing suite cannot rule out every interleaving. The independent-registry test does not launch separate OS processes. The dummy lost-update and circular-wait demonstrations intentionally force a failure pattern; they are teaching examples, not measurements of its frequency in a deployed service. Timeouts bound selected waits but do not establish fairness or starvation freedom.

Persistence and deployment limits. Rollback testing injects a Python-level failure, not a power loss or storage-device fault. WAL and synchronous FULL are configured, but crash recovery, backup restoration, replication and failover were not tested. Failure audits, traces and alerts are separate writes. A committed payment may therefore exist without all of its supporting review records if a subsequent write fails. Reliable delivery of those records would need additional design and evaluation.

Measurement limits. All timings come from one Windows machine, three accounts and short local workloads. No web-network latency, large account population, long-lived workload, controlled disk state or production traffic was included. The same request seed was repeated to hold request mix constant; the experiment does not measure sensitivity to other mixes. No statistical significance or comparison with another database is claimed.

Detection limits. The BankSim calculation reuses an existing holdout and saved coefficients. Its labels come from simulation, and its features retain the input file's within-day ordering. There is no real-customer validation, cost-sensitive threshold selection, drift study or calibrated interpretation of scores. External concern labels are also not probabilities of fraud. All alerts require contextual review.

## 8. Conclusion

The prototype provides a concrete setting in which students can follow a payment from a concurrent request through locking, transactional updates and review records. Forty-five tests and twenty-four benchmark runs supported the intended accounting behavior under the evaluated conditions. Timing variation and SQLite's single-writer design limit performance conclusions. The separate BankSim result further shows why a plausible fraud score must be accompanied by recall, data provenance and deployment limits. Future work should broaden failure and multiprocess testing, improve review-record reliability and evaluate detection on an appropriate independent dataset.


---

## Reproducibility and project responsibilities

The accompanying source workspace contains the following experiment scripts and evidence. The benchmark operates on temporary databases and leaves the demonstration banking database unchanged. Source hashes in the result files identify the evaluated implementation. The model check uses the existing local CSV; its original data location and download mirror are recorded in data/banksim_model.json.

| Artifact / command from project root | Purpose |
| --- | --- |
| python -m unittest discover -s tests -v | Run the banking, web, model-artifact and mocked review tests. |
| python docs/research/evaluate.py | Repeat the 24 threaded workloads; writes evaluation_results.json in the same directory. |
| python docs/research/evaluate_model.py | Re-score the saved classifier; writes model_evaluation.json with the source hash and confusion counts. |
| python docs/research/build_paper.py | Build this PDF and the editable Markdown manuscript using ReportLab. |

Use the project Python environment for the test suite and benchmark; rebuilding the PDF additionally requires ReportLab. The model-verification script uses the Python standard library and requires data/external/banksim.csv. Re-running experiments will change timings. The run reported here was performed on 2 November 2026.

Project responsibilities: Harsh Bhatia - atomic operations, thread coordination, race/deadlock demonstrations and fraud-review work. Tanisha Kapoor - database schema, storage, queries and project documentation. Prakhar Garg - web interface, integration and testing, with supporting work on database-backed displays and thread/lock-event visualization.

## References

[1] H. Berenson, P. Bernstein, J. Gray, J. Melton, E. O'Neil and P. O'Neil. "A Critique of ANSI SQL Isolation Levels." Proceedings of ACM SIGMOD, pp. 1-10, 1995. Technical report MSR-TR-95-51. Microsoft Research full text.

https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-95-51.pdf

[2] SQLite. "Isolation in SQLite." Official documentation. Accessed 2 November 2026. sqlite.org/isolation.html.

https://www.sqlite.org/isolation.html

[3] Python Software Foundation. "threading - Thread-based parallelism." Python 3.12 documentation. Accessed 2 November 2026. Python threading documentation.

https://docs.python.org/3.12/library/threading.html

[4] E. A. Lopez-Rojas and S. Axelsson. "BankSim: A Bank Payments Simulator for Fraud Detection Research." Proceedings of the 26th European Modeling and Simulation Symposium, pp. 144-152, 2014. EMSS original paper.

https://www.msc-les.org/proceedings/emss/2014/EMSS2014_144.pdf

[5] T. Saito and M. Rehmsmeier. "The Precision-Recall Plot Is More Informative than the ROC Plot When Evaluating Binary Classifiers on Imbalanced Datasets." PLOS ONE, 10(3), e0118432, 2015. doi:10.1371/journal.pone.0118432. Publisher article.

https://doi.org/10.1371/journal.pone.0118432

[6] scikit-learn developers. "average_precision_score." API reference. Accessed 2 November 2026. Metric definition.

https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html
