#!/usr/bin/env python3
"""Backfill source-bound caption candidates from cached OCR, without model/API calls."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import shutil

from kg_v2.common import OUT, load, save
from kg_v2.caption_fields import VERSION, supplement_relations
from kg_v2.identity import build_identity_review
from kg_v2_validate import validate


def enrich(graph, extraction_dir):
    entities = {e['id']: e for e in graph['entities']}
    added = []
    for page in graph['selection']:
        path = extraction_dir / f'v1-p{page:04d}.json'
        if not path.exists():
            raise FileNotFoundError(path)
        extra_entities, statements = supplement_relations(load(path), entities, graph['assertions'])
        entities.update({e['id']: e for e in extra_entities})
        graph['entities'] += extra_entities
        graph['assertions'] += statements
        added += statements
        graph['identityDecisions'] += [{'entityId': e['id'], 'decision': 'unresolved',
            'reason': '图注补抽候选；尚未执行跨实体重排或人工确认', 'candidateIds': []} for e in extra_entities]
    report = {'version': VERSION, 'addedAssertions': len(added),
        'byPredicate': dict(Counter(s['predicate'] for s in added)),
        'byOrigin': dict(Counter(s['origin'] for s in added)),
        'pages': sorted({s['evidence'][0]['page'] for s in added}),
        'network': 'none', 'modelsRerun': False, 'semanticAccuracy': 'not_independently_measured',
        'periodScope': 'Explicit name prefix or unambiguous same-page heading only; no cross-page propagation',
        'previousRunId': graph.get('runId')}
    if added:
        graph['summary'].update(entities=len(graph['entities']), assertions=len(graph['assertions']),
            pendingAssertions=sum(bool(s['issues']) for s in graph['assertions']))
        graph['identityReview'] = build_identity_review(graph)
        graph['captionEnrichment'] = report
        graph.setdefault('linking', {})['captionSupplementReranking'] = 'not_run; existing proposals preserved'
        graph.setdefault('evaluation', {})['captionSupplement'] = {
            'status': 'not_independently_measured', 'version': VERSION,
            'note': 'Earlier evaluation does not measure the precision or recall of these added relations.'}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='Persist validated candidates; preserve original graph in archive')
    args = parser.parse_args()
    graph_path = OUT / 'graph.json'
    graph = load(graph_path)
    report = enrich(graph, OUT / 'extractions')
    report['validation'] = validate(graph)
    if args.write and report['addedAssertions']:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = OUT / 'archive' / f'before-{VERSION}-{stamp}.json'
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(graph_path, backup)
        save(graph_path, graph)
        save(OUT / 'summary.json', graph['summary'])
        save(OUT / 'caption-enrichment-run.json', report)
        print('Previous graph preserved:', backup)
    print({key: value for key, value in report.items() if key != 'pages'})


if __name__ == '__main__':
    main()
