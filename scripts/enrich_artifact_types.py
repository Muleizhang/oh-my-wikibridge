#!/usr/bin/env python3
"""Add carrier types to all cached volumes and the running atlas, without OCR."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from kg_v2.atlas_site import render_atlas
from kg_v2.common import DATA_ROOT, ROOT, VOLUME_ROOTS, load, save
from kg_v2.artifact_types import enrich_types
from kg_v2_validate import validate


def update_atlas(manifest, graphs):
    items = {item['artifactId']: item for item in manifest['items']}
    rows = {r['id'] for r in manifest['rows']}
    evidence_ids = {e['id'] for e in manifest['evidence']}
    pages = {(p['volume'], p.get('volumePage', p['page'])): p for p in manifest['pages']}
    added = 0
    for volume, graph in zip(manifest['volumes'], graphs):
        entities = {e['id']: e for e in graph['entities']}
        docs = {(d['page'], d['engine']): d for d in graph['documents']}
        for statement in graph['assertions']:
            if statement['predicate'] != 'artifact_type':
                continue
            artifact_id = f"{volume['prefix']}:{statement['recordId']}"
            item = items.get(artifact_id)
            if not item:
                continue
            value = entities[statement['object']['id']]['label']
            item['artifactTypes'] = [value]
            row_id = f"{volume['prefix']}:{statement['id']}"
            if row_id in rows:
                continue
            ev = statement['evidence'][0]
            page = pages[(volume['label'], ev['page'])]
            doc = docs[(ev['page'], ev['engine'])]
            locator = f"{volume['label']} · PDF 第 {ev['page']} 页 · 图注 {statement['binding']['item']}"
            evidence_id = row_id+':e0'
            if evidence_id not in evidence_ids:
                manifest['evidence'].append({'id': evidence_id, 'page': page['page'], 'ordinal': page['page'],
                    'volumePage': ev['page'], 'volume': volume['label'], 'sourceName': doc['source'],
                    'locator': locator, 'text': ev['text'], 'previewUrl': page['previewUrl'], 'captionUrl': '',
                    'bbox': [v/k for v, k in zip(ev['bbox'], doc['imageSize']*2)] if ev.get('bbox') else None})
                evidence_ids.add(evidence_id)
            manifest['rows'].append({'id': row_id, 'artifactId': artifact_id, 'artifact': item['artifact'],
                'item': statement['binding']['item'], 'page': item['page'], 'volumePage': item.get('volumePage'),
                'volume': volume['label'], 'sourceName': doc['source'], 'locator': locator, 'proofLocator': locator,
                'predicate': 'artifact_type', 'object': value, 'objectId': 'merged:artifact_type:'+value,
                'evidenceId': evidence_id, 'quote': ev['text'], 'origin': statement['origin'],
                'binding': statement['binding'], 'status': '机器候选 · 尚未人工确认', 'issues': []})
            rows.add(row_id)
            added += 1
        volume['runId'] = graph.get('runId')
    manifest['summary'].update(graphEdges=len(manifest['rows']),
        artifactTypeItems=sum(bool(i.get('artifactTypes')) for i in manifest['items']))
    return added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--persist', action='store_true')
    parser.add_argument('--site', type=Path, default=DATA_ROOT/'merged/site')
    args = parser.parse_args()
    site = args.site.resolve()
    manifest = load(site/'manifest.json')
    backup = DATA_ROOT/'archive'/('before-artifact-types-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    if args.write:
        backup.mkdir(parents=True)
        shutil.copyfile(site/'manifest.json', backup/'manifest.json')
    graphs, reports = [], []
    for index, root in enumerate(VOLUME_ROOTS, 1):
        graph = load(root/'graph.json')
        report = enrich_types(graph, root/'extractions')
        report['validation'] = validate(graph)
        print(json.dumps({'volume': index, **{k: v for k, v in report.items() if k not in {'skipped', 'types', 'validation'}}}, ensure_ascii=False), flush=True)
        if args.write:
            shutil.copyfile(root/'graph.json', backup/f'vol{index}.graph.json')
            save(root/'graph.json', graph)
            save(root/'artifact-type-enrichment.json', report)
            if args.persist:
                subprocess.run([sys.executable, str(ROOT/'scripts/kg_v2_store.py')],
                               env=dict(os.environ, WIKIBRIDGE_KG_DATA=str(root)), check=True)
                graph = load(root/'graph.json')
        graphs.append(graph)
        reports.append(report)
    added = update_atlas(manifest, graphs)
    if args.write:
        save(site/'manifest.json', manifest)
        (site/'index.html').write_text(render_atlas(json.dumps(manifest, ensure_ascii=False)))
        save(DATA_ROOT/'artifact-type-batch.json', {'volumes': reports, 'atlasAdded': added})
    print(json.dumps({'written': args.write, 'newAtlasEdges': added,
                      'artifactTypeItems': manifest['summary']['artifactTypeItems']}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
