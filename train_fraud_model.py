"""Train the transfer-risk model from the public BankSim labelled CSV.

Run after downloading the source: python train_fraud_model.py
Use --download to fetch the source from the credited GitHub mirror.
"""
import argparse
import collections
import csv
import hashlib
import json
import math
from pathlib import Path
from urllib.request import urlretrieve


ROOT = Path(__file__).parent
SOURCE_PATH = ROOT / 'data' / 'external' / 'banksim.csv'
MODEL_PATH = ROOT / 'data' / 'banksim_model.json'
SOURCE_URL = ('https://raw.githubusercontent.com/niravdedhiya/'
              'Fraud-Detection-BankSim/main/data/bs140513_032310.csv')


def train(source_path=SOURCE_PATH, model_path=MODEL_PATH):
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import average_precision_score, precision_score, recall_score
    from sklearn.preprocessing import StandardScaler

    features, labels, days = [], [], []
    daily_count = collections.Counter()
    seen_recipients = set()
    with Path(source_path).open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        required = {'step', 'customer', 'merchant', 'amount', 'fraud'}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError(f'BankSim CSV needs columns: {sorted(required)}')
        for row in reader:
            day = int(row['step'])
            customer = row['customer']
            recipient = row['merchant']
            amount = float(row['amount'])
            fraud = int(row['fraud'])
            if amount < 0 or fraud not in (0, 1):
                raise ValueError('Invalid BankSim amount or fraud label')
            features.append((math.log1p(amount), min(daily_count[(customer, day)], 20),
                             int((customer, recipient) not in seen_recipients)))
            labels.append(fraud)
            days.append(day)
            daily_count[(customer, day)] += 1
            seen_recipients.add((customer, recipient))

    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(labels, dtype=np.int8)
    day_values = np.asarray(days, dtype=np.int32)
    cutoff = float(np.quantile(day_values, 0.8))
    train_mask = day_values < cutoff
    test_mask = ~train_mask
    if len(set(y[train_mask])) < 2 or len(set(y[test_mask])) < 2:
        raise ValueError('Both training and later-day test periods need fraud and legitimate rows')

    scaler = StandardScaler().fit(x[train_mask])
    classifier = LogisticRegression(max_iter=1000, random_state=42).fit(
        scaler.transform(x[train_mask]), y[train_mask])
    predictions = classifier.predict_proba(scaler.transform(x[test_mask]))[:, 1]
    threshold = 0.5
    flagged = predictions >= threshold
    result = {
        'source_name': 'BankSim synthetic bank payments',
        'source_url': 'https://www.kaggle.com/ntnu-testimon/banksim1',
        'source_mirror': SOURCE_URL,
        'source_sha256': hashlib.sha256(Path(source_path).read_bytes()).hexdigest(),
        'license': 'CC BY-NC-SA 4.0',
        'feature_names': ['log1p_amount', 'earlier_payments_today', 'new_recipient'],
        'means': scaler.mean_.tolist(),
        'scales': scaler.scale_.tolist(),
        'weights': classifier.coef_[0].tolist(),
        'bias': float(classifier.intercept_[0]),
        'threshold': threshold,
        'training_rows': int(train_mask.sum()),
        'training_fraud': int(y[train_mask].sum()),
        'test_rows': int(test_mask.sum()),
        'test_fraud': int(y[test_mask].sum()),
        'test_start_day': int(day_values[test_mask].min()),
        'average_precision': float(average_precision_score(y[test_mask], predictions)),
        'precision': float(precision_score(y[test_mask], flagged, zero_division=0)),
        'recall': float(recall_score(y[test_mask], flagged, zero_division=0)),
    }
    Path(model_path).parent.mkdir(parents=True, exist_ok=True)
    Path(model_path).write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(f'Trained on {result["training_rows"]:,} rows; tested on {result["test_rows"]:,} later-day rows.')
    print(f'Fraud labels: {result["training_fraud"]:,} train / {result["test_fraud"]:,} test.')
    print(f'Holdout average precision: {result["average_precision"]:.3f}; '
          f'precision {result["precision"]:.1%}, recall {result["recall"]:.1%} at 50% threshold.')
    print(f'Saved {model_path}')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true', help='download BankSim CSV from the credited mirror first')
    args = parser.parse_args()
    if args.download:
        SOURCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        print(f'Downloading {SOURCE_URL}')
        urlretrieve(SOURCE_URL, SOURCE_PATH)
    train()
