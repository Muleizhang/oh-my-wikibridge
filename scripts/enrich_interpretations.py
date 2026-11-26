#!/usr/bin/env python3
"""Extract and persist source-grounded symbolic labels using offline Chinese UIE."""
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
from kg_v2.interpretations import Extractor, VERSION
from kg_v2_validate import validate


def update_atlas(manifest, graphs):
    result = [record for record in manifest.get('interpretations', []) if record.get('origin') != VERSION]
    pages = {(p['volume'], p.get('volumePage', p['page'])): p for p in manifest['pages']}
    for volume, graph in zip(manifest['volumes'], graphs):
        for record in graph.get('interpretations', []):
            if record.get('origin') != VERSION:
                continue
            page = pages[(volume['label'], record['page'])]
            result.append({**record, 'id': volume['prefix']+':'+record['id'],
                'page': page['page'], 'volumePage': record['page'], 'volume': volume['label'],
                'pageUrl': page['previewUrl'], 'locator': f"{volume['label']} · PDF 第 {record['page']} 页"})
        volume['runId'] = graph.get('runId')
    manifest['interpretations'] = result
    manifest['summary'].update(interpretations=len(result), graphEdges=len(manifest['rows'])+len(result)*2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--persist', action='store_true')
    parser.add_argument('--refresh', action='store_true', help='Rebuild candidates from cached neural predictions')
    args = parser.parse_args()
    data = DATA_ROOT
    output = data/'semantic-enrichment'
    graphs = [load(root/'graph.json') for root in VOLUME_ROOTS]
    if args.refresh or not (output/'candidates.json').exists():
        records, report = Extractor(output).run(graphs)
        save(output/'candidates.json', records); save(output/'report.json', report)
    else:
        records, report = load(output/'candidates.json'), load(output/'report.json')
    for volume, graph in enumerate(graphs, 1):
        graph['interpretations'] = [r for r in graph.get('interpretations', []) if r.get('origin') != VERSION]
        graph['interpretations'] += [r for r in records if r['volumeNumber'] == volume]
        graph['summary']['interpretations'] = len(graph['interpretations'])
        validate(graph)
    if args.write:
        backup = data/'archive'/('before-interpretations-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        backup.mkdir(parents=True)
        shutil.copyfile(data/'merged/site/manifest.json', backup/'manifest.json')
        for index, (root, graph) in enumerate(zip(VOLUME_ROOTS, graphs), 1):
            shutil.copyfile(root/'graph.json', backup/f'vol{index}.graph.json')
            save(root/'graph.json', graph)
            if args.persist:
                subprocess.run([sys.executable, str(ROOT/'scripts/kg_v2_store.py')],
                    env=dict(os.environ, WIKIBRIDGE_KG_DATA=str(root)), check=True)
                graphs[index-1] = load(root/'graph.json')
        site = data/'merged/site'
        manifest = load(site/'manifest.json')
        update_atlas(manifest, graphs)
        save(site/'manifest.json', manifest)
        (site/'index.html').write_text(render_atlas(json.dumps(manifest, ensure_ascii=False)))
    report = {**report, 'state': 'complete' if args.write else 'dry_run'}
    save(output/'status.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
