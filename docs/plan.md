# Scope and milestone checklist

The project now includes the planned web interface and a local professor demo in addition to the Weeks 1-3 core.

| Milestone | Delivered | Remaining |
|---|---|---|
| Week 1: design/setup | Schema, sample data, modules, architecture and ER diagrams, runnable CLI and GUI | — |
| Week 2: transaction core | Deposit, withdraw, transfer, exact money, commit, rollback, failure audit, request deduplication | — |
| Week 3: concurrency | Threads, mutexes, consistent lock ordering, timeouts, dummy deadlock/race demos, concurrency tests, measured runs | PostgreSQL-specific row locks if required by the supervisor |
| Week 4: security/fraud | Password-hashed demo logins, roles, account ownership, CSRF, login throttling, high-value/rapid/failure/unauthorized alerts | Real-world hardening and policy validation |
| Week 5: GUI | Flask dashboard, banking form, activity, admin risk desk, concurrency lab | Hosting or mobile interface if needed |
| Week 6: submission | Repeatable demo, measured runs, technical notes and automated tests | Final report, slides and video if required by the professor |

## Recommended team handoff

- Harsh: explain the schema, atomic transfer and rollback; own backend integration.
- Prakhar: explain threads, critical sections, deadlock conditions, ordered locking and simulator measurements.
- Tanisha: explain the GUI, customer/admin journeys, fraud rules and recorded test evidence.

All members should run the demo and explain why mixed operations change total money while transfers alone do not.
