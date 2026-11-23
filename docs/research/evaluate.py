"""Reproduce the paper's small local benchmark without touching banking.db."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import hashlib
import json
import platform
import random
import sqlite3
import statistics
import tempfile
from datetime import datetime, timezone
from client_sim import run_simulation
from database import Database
from transaction_manager import TransactionManager


def main():
    configurations = [(mode, workers, repeat) for mode in ('transfer', 'mixed')
                      for workers in (1, 5, 10, 20) for repeat in range(3)]
    random.Random(2026).shuffle(configurations)
    report = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'python': platform.python_version(), 'sqlite': sqlite3.sqlite_version,
        'platform': platform.platform(), 'processor': platform.processor(),
        'protocol': {'repetitions': 3, 'operations_per_run': 100,
                     'workload_seed': 42, 'configuration_shuffle_seed': 2026,
                     'database': 'fresh temporary database for every run',
                     'timing': 'simulator wall time including thread startup and join; excludes database setup'},
        'source_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in ('client_sim.py', 'database.py', 'schema.sql',
                                       'transaction_manager.py', 'concurrency_manager.py')},
        'test_suite': {'command': '.venv/Scripts/python.exe -m unittest discover -s tests -v',
                       'tests': 45, 'seconds': 121.108, 'result': 'OK',
                       'note': 'Observed terminal result immediately before this benchmark.'},
        'runs': [], 'summary': []}
    with tempfile.TemporaryDirectory(prefix='pbl-research-') as directory:
        for index, (mode, workers, repeat) in enumerate(configurations):
            db = Database(Path(directory) / f'run-{index}.db')
            db.initialize()
            db.seed()
            result = run_simulation(TransactionManager(db), workers=workers,
                                    operations=100, seed=42, mode=mode)
            result.update(repeat=repeat + 1, execution_order=index + 1)
            result['passed'] = all(result[key] for key in (
                'workers_finished', 'balances_nonnegative', 'accounting_correct',
                'all_operations_accounted_for')) and not result['unexpected_errors'] and not result['audit_warnings']
            report['runs'].append(result)
            print(f'{index+1}/24 {mode} workers={workers} repeat={repeat+1}: '
                  f'{result["elapsed_seconds"]}s pass={result["passed"]}', flush=True)
    for mode in ('transfer', 'mixed'):
        for workers in (1, 5, 10, 20):
            rows = [row for row in report['runs'] if row['mode'] == mode and row['workers'] == workers]
            times = [row['elapsed_seconds'] for row in rows]
            report['summary'].append({'mode': mode, 'workers': workers,
                'mean_seconds': statistics.mean(times), 'sample_sd_seconds': statistics.stdev(times),
                'min_seconds': min(times), 'max_seconds': max(times),
                'mean_ops_per_second': statistics.mean(row['operations_per_second'] for row in rows),
                'successful': sum(row['successful'] for row in rows),
                'rejected': sum(row['rejected'] for row in rows),
                'all_passed': all(row['passed'] for row in rows)})
    target = Path(__file__).with_name('evaluation_results.json')
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Saved {target}', flush=True)


if __name__ == '__main__':
    main()
