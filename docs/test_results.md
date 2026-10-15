# Recorded demonstration results

Generated: 2026-10-08T14:00:45.634244+00:00

Python: 3.12.14; SQLite WAL, BEGIN IMMEDIATE, synchronous FULL

Overall result: PASS

These are measured local results, not promised performance. Each workload uses a fresh temporary database.

| Scenario | Result |
|---|---|
| 100_deposits | PASS |
| overspending | PASS |
| rollback | PASS |
| opposing_transfers | PASS |
| deadlock | PASS |
| race_condition | PASS |

| Workload | Threads | Operations | Successful | Rejected | Seconds | Accounting |
|---|---:|---:|---:|---:|---:|---|
| transfer | 1 | 100 | 100 | 0 | 2.0321 | PASS |
| transfer | 5 | 100 | 100 | 0 | 2.9817 | PASS |
| transfer | 10 | 100 | 100 | 0 | 1.9656 | PASS |
| transfer | 20 | 100 | 100 | 0 | 3.7386 | PASS |
| mixed | 1 | 100 | 100 | 0 | 1.8207 | PASS |
| mixed | 5 | 100 | 100 | 0 | 2.2646 | PASS |
| mixed | 10 | 100 | 100 | 0 | 1.5364 | PASS |
| mixed | 20 | 100 | 100 | 0 | 1.6595 | PASS |

SQLite allows one writer at a time, so additional threads need not increase throughput.
The seed fixes the requested operations; thread execution order and timing can vary.
The mixed workload checks initial total + successful deposits - successful withdrawals.
See test_results.json for totals, thread activity, and deadlock events.
