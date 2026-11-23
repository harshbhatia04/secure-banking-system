# Current project validation

Checked on 23 November 2026 using the local Python 3.12.14 environment. All commands below use temporary databases or test clients; they do not modify `data/banking.db`.

| Check | Result | Evidence |
| --- | --- | --- |
| Automated suite | 45 tests passed | `python -m unittest discover -s tests -q` |
| Presentation scenarios | 6 of 6 passed | `python demo.py`; `docs/test_results.json` |
| Measured workloads | 8 of 8 preserved accounting checks | `python demo.py`; `docs/test_results.md` |
| Two-process opposing transfers | 50 of 50 committed; balances returned to starting values | `python process_safety_demo.py` |
| Same request key in two processes | One ledger row, one new payment and one replay | `python process_safety_demo.py` |
| Exit after uncommitted debit | SQLite restored original balances; no success row | `python process_safety_demo.py` |
| Optional hosted AI review | A real API call finished after an isolated committed transfer | Flask test client with temporary database and encrypted local key |
| Phase-III report source | Compiled successfully | Desktop LaTeX compiler, `docs/phase3_report/main.tex` |
| IEEE-format manuscript source | Compiled successfully | Desktop LaTeX compiler, `docs/ieee_research_paper/main.tex` |

The three process checks are recorded in `docs/process_safety_results.json`. They exercise SQLite's cross-process writer serialization and crash rollback. Python account mutexes are process-local, so they are not credited with those cross-process guarantees.

The separate BankSim classifier was re-scored on its existing later-day holdout on 2 November 2026. Its recorded source hash matches the local CSV, and the saved model metrics reproduced within floating-point rounding. This is **not** an independent INR banking validation. The live site uses deterministic rules and optional Groq review after payment commit; the BankSim classifier remains an offline prototype. Research evidence is in `docs/research/`.

For a live demonstration, run `.\run.ps1 -Web` (or `.\run.ps1 -Web -Groq` when the API key is configured). Show a customer transfer and its real thread/lock/SQLite trace, then the admin Risk Desk, Concurrency Lab and Demo Studio. The optional external review can fail independently; the committed payment and deterministic rules remain intact.

These results establish behavior for the tested local scenarios. They do not establish production security, multi-host scalability, crash durability under every hardware failure, or fraud-detection accuracy on real bank data.
