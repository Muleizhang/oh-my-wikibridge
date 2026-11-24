"""Scope-complete, owner-sensitive scoring; never relabel assistant data as gold."""
import math
from collections import Counter


def wilson_lower(correct, total, z=1.96):
    if not total:
        return None
    p = correct / total; denominator = 1 + z * z / total
    return (p + z*z/(2*total) - z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))) / denominator


def quantity_key(page, item, predicate, obj):
    return (page, item, predicate, obj.get('value'), obj['unit'], bool(obj.get('approximate')))


def score_quantities(reference, statements, records):
    scope = {(s['page'], i) for s in reference['scope'] for i in s['items']}
    record_map = {r['id']: r for r in records}
    expected = Counter(quantity_key(r['page'], r['item'], r['predicate'], r['object']) for r in reference['assertions'])
    predictions = []
    for s in statements:
        record = record_map.get(s.get('recordId'))
        if record and (record['page'], record['item']) in scope and s['object']['kind'] == 'quantity':
            predictions.append(quantity_key(record['page'], record['item'], s['predicate'], s['object']))
    actual = Counter(predictions)
    tp = sum((actual & expected).values()); fp = sum((actual - expected).values()); fn = sum((expected - actual).values())
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {'referenceAuthority': reference['authority'], 'independent': reference['independent'],
        'scope': reference['scope'], 'expected': sum(expected.values()), 'predicted': sum(actual.values()),
        'truePositive': tp, 'falsePositive': fp, 'falseNegative': fn,
        'precision': precision, 'recall': recall, 'precisionLower95': wilson_lower(tp, tp + fp),
        'falsePositives': [list(k) for k in (actual - expected).elements()],
        'falseNegatives': [list(k) for k in (expected - actual).elements()],
        'matching': 'page + caption item + field + numeric value + unit + approximation; exact multiset',
        'interpretation': 'Development diagnostic only; does not authorize automatic acceptance'}
