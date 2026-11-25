#!/usr/bin/env python3
"""Batch caption dimensions with local UIE + GLiNER, preserving OCR and images."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from kg_v2.common import ROOT, ident, load, save
from kg_v2.model_dimensions import VERSION, DIMENSIONS, Enricher, model_records
from kg_v2.dimension_models import extract
from kg_v2_validate import validate

DATA = ROOT/'data/local-kg'


def update_atlas(manifest, graphs):
    items = {item['artifactId']: item for item in manifest['items']}
    rows = {r['id']: r for r in manifest['rows']}
    pages = {(p.get('volume', ''), p.get('volumePage', p['page'])): p for p in manifest['pages']}
    added = Counter()
    for volume, graph in zip(manifest['volumes'], graphs):
        entities = {e['id']: e for e in graph['entities']}
        docs = {(d['page'], d['engine']): d for d in graph['documents']}
        records = {r['id']: r for r in graph['records']}
        for statement in graph['assertions']:
            pred = statement['predicate']
            if pred not in DIMENSIONS or statement['object']['kind'] != 'entity' or not statement.get('evidence'):
                continue
            artifact_id = volume['prefix']+':'+statement.get('recordId', '')
            item = items.get(artifact_id)
            if item is None:
                continue
            target = entities[statement['object']['id']]
            kind, label, field = DIMENSIONS[pred]
            if target['kind'] != kind:
                continue
            value = re.sub(r'(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])', '', target['label']).strip()
            values = item.setdefault(field, [])
            if value not in values:
                values.append(value)
            row_id = volume['prefix']+':'+statement['id']
            if row_id in rows:
                if statement.get('modelScore') is not None:
                    rows[row_id].update(modelScore=statement['modelScore'], extractionMethod=statement.get('extractionMethod'))
                continue
            ev = statement['evidence'][0]
            doc = docs[(ev['page'], ev['engine'])]
            page = pages[(volume['label'], ev['page'])]
            record = records[statement['recordId']]
            locator = f"{volume['label']} · PDF 第 {ev['page']} 页 · 图注 {record['item']}"
            eid = row_id+':e0'
            manifest['evidence'].append({'id': eid, 'page': page['page'], 'ordinal': page['page'],
                'volumePage': ev['page'], 'volume': volume['label'], 'sourceName': doc['source'],
                'locator': locator, 'text': ev['text'], 'previewUrl': page['previewUrl'], 'captionUrl': '',
                'bbox': [v/k for v, k in zip(ev['bbox'], doc['imageSize']*2)] if ev.get('bbox') else None})
            manifest['rows'].append({'id': row_id, 'artifactId': artifact_id, 'artifact': item['artifact'],
                'item': record['item'], 'page': item['page'], 'volumePage': item.get('volumePage'),
                'volume': volume['label'], 'sourceName': doc['source'], 'locator': locator, 'proofLocator': locator,
                'predicate': pred, 'object': value, 'objectId': f'merged:{kind}:{value}',
                'evidenceId': eid, 'quote': record['text'], 'origin': statement['origin'],
                'binding': statement.get('binding'), 'status': '机器候选 · 尚未人工确认',
                'modelScore': statement.get('modelScore'), 'extractionMethod': statement.get('extractionMethod'),
                'issues': statement.get('issues', [])})
            rows[row_id] = manifest['rows'][-1]
            added[pred] += 1
        volume['runId'] = graph.get('runId')
    manifest['summary'].update(graphEdges=len(manifest['rows']),
        predicateCounts=dict(Counter(row['predicate'] for row in manifest['rows'])))
    return dict(added)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--persist', action='store_true')
    parser.add_argument('--batch-size', type=int, default=32)
    parser.add_argument('--site', type=Path, default=DATA/'merged/site')
    args = parser.parse_args()
    started = time.monotonic()
    run_dir = DATA/'dimension-enrichment'
    run_dir.mkdir(exist_ok=True)
    status_path = run_dir/'status.json'
    graphs, enrichers, pending = [], [], []
    for number, root in enumerate([DATA, DATA/'vol2', DATA/'vol3'], 1):
        graph = load(root/'graph.json')
        enricher = Enricher(graph)
        for page in graph['selection']:
            extraction = load(root/f'extractions/v1-p{page:04d}.json')
            for job in model_records(extraction):
                pending.append((enricher, job))
        graphs.append(graph)
        enrichers.append(enricher)
        print(json.dumps({'volume': number, 'queuedRecords': sum(e is enricher for e, _ in pending)}, ensure_ascii=False), flush=True)
    extract(pending, run_dir, args.batch_size)
    reports = []
    for enricher in enrichers:
        report = enricher.report()
        report['validation'] = validate(enricher.graph)
        reports.append(report)
    manifest = load(args.site/'manifest.json')
    if args.write:
        backup = DATA/'archive'/('before-simple-dimensions-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        backup.mkdir(parents=True)
        shutil.copyfile(args.site/'manifest.json', backup/'manifest.json')
        for index, (root, graph, report) in enumerate(zip([DATA, DATA/'vol2', DATA/'vol3'], graphs, reports), 1):
            shutil.copyfile(root/'graph.json', backup/f'vol{index}.graph.json')
            save(root/'graph.json', graph)
            save(root/'simple-dimension-enrichment.json', report)
            if args.persist:
                subprocess.run([sys.executable, str(ROOT/'scripts/kg_v2_store.py')],
                    env=dict(os.environ, WIKIBRIDGE_KG_DATA=str(root)), check=True)
                graphs[index-1] = load(root/'graph.json')
    atlas_added = update_atlas(manifest, graphs)
    if args.write:
        save(args.site/'manifest.json', manifest)
        template = (ROOT/'scripts/atlas_viewer.html').read_text()
        reasoner = re.sub(r'(?m)^export\s+', '', (ROOT/'src/kg-reasoner.js').read_text())
        embedded = json.dumps(manifest, ensure_ascii=False).replace('<', '\\u003c')
        (args.site/'index.html').write_text(template.replace('__REASONER_JS__', reasoner, 1).replace('__MANIFEST_JSON__', embedded, 1))
    result = {'state': 'complete' if args.write else 'dry_run', 'volumes': reports, 'atlasAdded': atlas_added,
              'seconds': round(time.monotonic()-started, 1), 'ocrRerun': False, 'llmCalls': 0}
    save(status_path, result)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
