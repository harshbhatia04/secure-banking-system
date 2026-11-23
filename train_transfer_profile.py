"""Train the live sender-relative model and record its time-split BankSim evaluation."""
import csv
import hashlib
import json
from bisect import bisect_left, insort
from collections import Counter, defaultdict, deque
from statistics import median

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, confusion_matrix, precision_recall_curve
from threadpoolctl import threadpool_limits

from local_review import FEATURE_NAMES, HISTORY, MODEL_PATH, RECENT_PAYMENTS, VERSION, features, score_transfer
from train_fraud_model import SOURCE_PATH


def export_model(classifier, threshold):
    # The pinned scikit-learn version exposes fitted histogram tree nodes here.
    # Export numeric branches only. The application always supplies finite inputs.
    trees = []
    for (predictor,) in classifier._predictors:
        tree = []
        for node in predictor.nodes:
            if node['is_leaf']:
                tree.append([float(node['value'])])
            else:
                tree.append([int(node['feature_idx']), float(node['num_threshold']),
                             int(node['left']), int(node['right'])])
        trees.append(tree)
    return {'version': VERSION, 'feature_names': list(FEATURE_NAMES),
            'bias': float(classifier._baseline_prediction.item()),
            'trees': trees, 'threshold': threshold}


def select_model(train, validation):
    # Unit-free checks protect the known app regression during model selection.
    routine = [features(10_000, [('known', 10_000)] * 3, 0, 'known', False, typical)
               for typical in (100, 10_000)]
    unusual = features(10_000, [('known', 100)] * 3, 3, 'known', False, 100)
    vx, vy = validation
    candidates = []
    for leaf_count in (7, 15, 31):
        clf = HistGradientBoostingClassifier(max_iter=120, max_leaf_nodes=leaf_count,
                                            min_samples_leaf=50, l2_regularization=1,
                                            early_stopping=False, random_state=42)
        clf.fit(*train)
        *routine_scores, high = clf.predict_proba([*routine, unusual])[:, 1]
        low = max(routine_scores)
        precision, recall, thresholds = precision_recall_curve(vy, clf.predict_proba(vx)[:, 1])
        eligible = np.flatnonzero((thresholds > low) & (thresholds <= high))
        if len(eligible):
            f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-12)
            index = eligible[np.argmax(f1[eligible])]
            candidates.append((float(f1[index]), clf, float(thresholds[index])))
    if not candidates:
        raise ValueError('No candidate separated the routine and unusual transfers')
    return max(candidates, key=lambda candidate: candidate[0])


def main():
    histories = defaultdict(lambda: deque(maxlen=HISTORY))
    recipients = set()
    daily = Counter()
    total = Counter()
    skipped_fraud = Counter()
    sets = {name: ([], []) for name in ('train', 'validation', 'test')}
    previous_day = -1
    recent = deque()
    ordered = []
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
            recent_typical = median(ordered) if ordered else None
            x = features(amount, prior, daily[sender, day], recipient, (sender, recipient) not in recipients,
                         recent_typical)
            if x is None:
                skipped_fraud[split] += label
            else:
                sets[split][0].append(x)
                sets[split][1].append(label)
            prior.append((recipient, amount))
            daily[sender, day] += 1
            recipients.add((sender, recipient))
            if len(recent) == RECENT_PAYMENTS:
                ordered.pop(bisect_left(ordered, recent.popleft()))
            recent.append(amount)
            insort(ordered, amount)
    tx, ty = sets['test']
    with threadpool_limits(limits=4):
        validation_f1, clf, threshold = select_model(sets['train'], sets['validation'])
        expected = clf.predict_proba(tx)[:, 1]
    model = export_model(clf, threshold)
    scores = np.asarray([score_transfer(model, row) for row in tx])
    np.testing.assert_allclose(scores, expected, rtol=1e-12, atol=1e-12)
    tn, fp, fn, tp = map(int, confusion_matrix(ty, scores >= threshold).ravel())
    model.update(source='BankSim synthetic payments',
                 source_sha256=hashlib.sha256(SOURCE_PATH.read_bytes()).hexdigest(),
                 max_leaf_nodes=clf.max_leaf_nodes, validation_f1=validation_f1,
                 threshold_selection='Maximum validation F1 with routine/unusual transfer checks',
                 eligible_rows={s: len(data[1]) for s, data in sets.items()}, all_rows=dict(total),
                 skipped_fraud=dict(skipped_fraud), test=dict(tn=tn, fp=fp, fn=fn, tp=tp,
                 precision=tp/(tp+fp), recall=tp/(tp+fn), average_precision=float(average_precision_score(ty, scores))))
    MODEL_PATH.write_text(json.dumps(model, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in model.items() if key != 'trees'}, indent=2))


if __name__ == '__main__':
    main()
