"""Re-score the saved BankSim model on its recorded later-day holdout."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import csv
import json
import hashlib
import platform
from datetime import datetime, timezone
import collections
import math
from train_fraud_model import SOURCE_PATH


def main():
    previous = -1
    decreases = 0
    rows = 0
    original = json.loads((ROOT / 'data/banksim_model.json').read_text(encoding='utf-8'))
    daily_count, seen = collections.Counter(), set()
    scores = []
    train_rows = train_fraud = 0
    with SOURCE_PATH.open(newline='', encoding='utf-8-sig') as source:
        for row in csv.DictReader(source):
            day = int(row['step'])
            decreases += day < previous
            previous = day
            rows += 1
            customer, recipient = row['customer'], row['merchant']
            features = (math.log1p(float(row['amount'])), min(daily_count[(customer, day)], 20),
                        int((customer, recipient) not in seen))
            label = int(row['fraud'])
            if day >= original['test_start_day']:
                z = original['bias'] + sum(w * (x-m)/s for x, m, s, w in zip(
                    features, original['means'], original['scales'], original['weights']))
                score = 1 / (1 + math.exp(-z))
                scores.append((score, label))
            else:
                train_rows += 1
                train_fraud += label
            daily_count[(customer, day)] += 1
            seen.add((customer, recipient))
    if decreases:
        raise ValueError('Dataset day order is not monotonic; review features before reporting metrics')
    destination = Path(__file__).with_name('model_evaluation.json')
    scores.sort(reverse=True)
    positives = sum(label for _, label in scores)
    tp = fp = 0
    ap = 0.0
    i = 0
    while i < len(scores):
        j = i
        group_tp = 0
        while j < len(scores) and scores[j][0] == scores[i][0]:
            group_tp += scores[j][1]
            j += 1
        tp += group_tp
        fp += j - i - group_tp
        ap += (group_tp / positives) * (tp / (tp + fp))
        i = j
    selected = [label for score, label in scores if score >= original['threshold']]
    hits = sum(selected)
    result = {'training_rows': train_rows, 'training_fraud': train_fraud,
        'test_rows': len(scores), 'test_fraud': positives,
        'test_start_day': original['test_start_day'], 'threshold': original['threshold'],
        'source_sha256': hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest(),
        'average_precision': ap, 'precision': hits / len(selected), 'recall': hits / positives,
        'true_positive': hits, 'false_positive': len(selected) - hits,
        'false_negative': positives - hits,
        'true_negative': len(scores) - positives - (len(selected) - hits)}
    result['verification'] = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'python': platform.python_version(),
        'rows': rows, 'day_order_decreases': decreases,
        'source_matches_saved_sha256': result['source_sha256'] == original['source_sha256'],
        'training_script_sha256': hashlib.sha256((ROOT / 'train_fraud_model.py').read_bytes()).hexdigest(),
        'absolute_metric_differences': {key: abs(result[key] - original[key])
            for key in ('average_precision', 'precision', 'recall')},
        'note': 'Saved coefficients re-scored with Python standard library; no model refit. Original model artifact was not overwritten.'}
    destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result['verification'], indent=2))


if __name__ == '__main__':
    main()
