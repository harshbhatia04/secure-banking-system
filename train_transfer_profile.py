"""Train the live sender-relative model and record its time-split BankSim evaluation."""
import csv
import hashlib
import json
from collections import Counter, defaultdict, deque

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, confusion_matrix, precision_recall_curve

from local_review import HISTORY, MODEL_PATH, VERSION, features
from train_fraud_model import SOURCE_PATH


def main():
    histories = defaultdict(lambda: deque(maxlen=HISTORY))
    recipients = set()
    daily = Counter()
    total = Counter()
    skipped_fraud = Counter()
    sets = {name: ([], []) for name in ('train', 'validation', 'test')}
    previous_day = -1
    with SOURCE_PATH.open(encoding='utf-8-sig', newline='') as source:
        for row in csv.DictReader(source):
            day = int(row['step'])
            if day < previous_day:
                raise ValueError('Expected chronologically ordered BankSim days')
            previous_day = day
            split = 'train' if day < 120 else 'validation' if day < 147 else 'test'
            total[split] += 1
            sender, recipient = row['customer'], row['merchant']
            amount, label = float(row['amount']), int(row['fraud'])
            prior = histories[sender]
            x = features(amount, prior, daily[sender, day], (sender, recipient) not in recipients)
            if x is None:
                skipped_fraud[split] += label
            else:
                sets[split][0].append(x)
                sets[split][1].append(label)
            prior.append(amount)
            daily[sender, day] += 1
            recipients.add((sender, recipient))
    clf = LogisticRegression(max_iter=1000, random_state=42).fit(*sets['train'])
    vx, vy = sets['validation']
    precision, recall, thresholds = precision_recall_curve(vy, clf.predict_proba(vx)[:, 1])
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-12)
    threshold = float(thresholds[np.argmax(f1)])
    tx, ty = sets['test']
    scores = clf.predict_proba(tx)[:, 1]
    tn, fp, fn, tp = map(int, confusion_matrix(ty, scores >= threshold).ravel())
    model = dict(version=VERSION, source='BankSim synthetic payments',
                 source_sha256=hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest(),
                 feature_names=['log1p_amount_to_recent_median', 'earlier_today_capped', 'new_recipient'],
                 weights=clf.coef_[0].tolist(), bias=float(clf.intercept_[0]), threshold=threshold,
                 threshold_selection='Maximum F1 on days 120-146; test starts at day 147',
                 eligible_rows={s: len(data[1]) for s, data in sets.items()}, all_rows=dict(total),
                 skipped_fraud=dict(skipped_fraud), test=dict(tn=tn, fp=fp, fn=fn, tp=tp,
                 precision=tp/(tp+fp), recall=tp/(tp+fn), average_precision=float(average_precision_score(ty, scores))))
    MODEL_PATH.write_text(json.dumps(model, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(model, indent=2))


if __name__ == '__main__':
    main()
