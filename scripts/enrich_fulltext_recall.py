#!/usr/bin/env python3
"""Supplement craft, composition and interpretation coverage with local UIE."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil

from kg_v2.common import ROOT, ident, load, save
from kg_v2.identity import normalize_name
from kg_v2.identity_manifest import apply_manifest_identity
from kg_v2.recall_extraction import RecallExtractor, VERSION, labels
from kg_v2_validate import validate
from kg_v2_store import persist

DATA = ROOT/'data/local-kg'
ROOTS = [DATA, DATA/'vol2', DATA/'vol3']
FIELDS = {'technique': ('uses_technique', 'techniques'), 'composition': ('has_composition', 'compositions')}


def atlas_counts(manifest):
    predicates = Counter(r['predicate'] for r in manifest['rows'])
    concepts = Counter(r['kind'] for r in manifest.get('interpretations', []))
    return {'artifactTechniqueRelations': predicates['uses_technique'],
            'artifactCompositionRelations': predicates['has_composition'],
            'proseTechniqueRelations': concepts['technique'], 'proseCompositionRelations': concepts['composition'],
            'symbolicRelations': concepts['symbolism'], 'beliefRelations': concepts['belief'],
            'ritualRelations': concepts['ritual'], 'sourceRelations': len(manifest.get('interpretations', []))}


def apply_candidates(graph, artifacts, concepts):
    # Re-filtering a cached pass replaces only its own machine output. Otherwise
    # an earlier false positive would survive every subsequent filtering fix.
    before_entities = {e['id']: e for e in graph['entities']}
    prior_artifacts = {(a['subject'], a['predicate'], normalize_name(before_entities[a['object']['id']]['label']))
        for a in graph['assertions'] if a['object']['kind'] == 'entity' and a['object']['id'] in before_entities}
    prior_concepts = {(v['page'], v['kind'], normalize_name(v['subject']['label']), normalize_name(v['value']))
                      for v in graph.get('interpretations', [])}
    replaced = [a for a in graph['assertions'] if a.get('origin') == VERSION]
    replaced_targets = {a['object']['id'] for a in replaced if a['object']['kind'] == 'entity'}
    graph['assertions'] = [a for a in graph['assertions'] if a.get('origin') != VERSION]
    graph['entities'] = [e for e in graph['entities'] if e['id'] not in replaced_targets]
    graph['interpretations'] = [v for v in graph.get('interpretations', []) if v.get('origin') != VERSION]
    entities = {e['id']: e for e in graph['entities']}
    owners = {e['recordId']: e for e in graph['entities'] if e['kind'] == 'artifact'}
    known = {(a['subject'], a['predicate'], normalize_name(entities[a['object']['id']]['label']))
             for a in graph['assertions'] if a['object']['kind'] == 'entity' and a['object']['id'] in entities}
    added = Counter()
    for value in artifacts:
        owner = owners.get(value['recordId'])
        if not owner:
            continue
        key = owner['id'], value['predicate'], normalize_name(value['value'])
        if key in known:
            continue
        target = ident('entity', VERSION, value['recordId'], value['kind'], value['value'])
        entity = {'id': target, 'label': value['value'], 'kind': value['kind'], 'recordId': value['recordId'],
            'scope': 'source_mention', 'identityStatus': 'unresolved', 'aliases': [value['value']],
            'evidence': [value['valueEvidence']], 'origin': VERSION}
        graph['entities'].append(entity); entities[target] = entity
        graph['assertions'].append({'id': value['id'], 'subject': owner['id'], 'recordId': value['recordId'],
            'predicate': value['predicate'], 'label': value['relationLabel'], 'object': {'kind': 'entity', 'id': target},
            'evidence': [value['valueEvidence']], 'origin': VERSION, 'extractionMethod': 'local_uie',
            'modelScore': value['modelScore'], 'binding': {'kind': 'local_uie', 'scope': 'catalog_record',
                'recordId': value['recordId'], 'model': value['model'], 'revision': value['revision'],
                'raw': value['valueEvidence']['text'], 'route': value['route']},
            'qualifiers': [], 'issues': [], 'status': 'candidate', 'reviewStatus': 'unreviewed'})
        known.add(key)
        if key not in prior_artifacts: added[value['kind']] += 1
    interpretations = graph.setdefault('interpretations', [])
    known_concepts = {(v['page'], v['kind'], normalize_name(v['subject']['label']), normalize_name(v['value']))
                      for v in interpretations}
    concept_added = Counter()
    for value in concepts:
        key = value['page'], value['kind'], normalize_name(value['subject']['label']), normalize_name(value['value'])
        if key not in known_concepts:
            interpretations.append(value); known_concepts.add(key)
            if key not in prior_concepts: concept_added[value['kind']] += 1
    graph['summary'].update(entities=len(graph['entities']), assertions=len(graph['assertions']),
                            interpretations=len(interpretations))
    graph['fulltextRecall'] = {'version': VERSION, 'artifactAdded': dict(added), 'conceptAdded': dict(concept_added),
                              'fineTuning': False, 'ocrRerun': False, 'llmCalls': 0}
    validate(graph)
    return graph['fulltextRecall']


def update_manifest(manifest, graphs):
    """Update the source projection first; keep image and identity decisions intact."""
    source_items = manifest.get('sourceItems', manifest['items'])
    source_rows = [r for r in manifest.get('sourceRows', manifest['rows']) if r.get('origin') != VERSION]
    manifest['interpretations'] = [v for v in manifest.get('interpretations', []) if v.get('origin') != VERSION]
    items = {i.get('sourceRecordId', i['artifactId']): i for i in source_items}
    row_ids = {r['id'] for r in source_rows}
    evidence_ids = {e['id'] for e in manifest['evidence']}
    interpretation_ids = {r['id'] for r in manifest.get('interpretations', [])}
    pages = {(p['volume'], p.get('volumePage', p['page'])): p for p in manifest['pages']}
    for volume, graph in zip(manifest['volumes'], graphs):
        prefix = volume['prefix']; entities = {e['id']: e for e in graph['entities']}
        records = {r['id']: r for r in graph['records']}
        for assertion in graph['assertions']:
            if assertion.get('origin') != VERSION:
                continue
            source_id = prefix+':'+assertion['recordId']; item = items.get(source_id)
            if item is None:
                continue
            target = entities[assertion['object']['id']]; pred, field = FIELDS[target['kind']]
            values = item.setdefault(field, [])
            if target['label'] not in values: values.append(target['label'])
            row_id = prefix+':'+assertion['id']
            if row_id in row_ids:
                continue
            ev = assertion['evidence'][0]; page = pages[(volume['label'], ev['page'])]
            record = records[assertion['recordId']]; locator = f"{volume['label']} · PDF 第 {ev['page']} 页 · 图注 {record['item']}"
            evidence_id = row_id+':e0'
            evidence = {'id': evidence_id, 'page': page['page'], 'ordinal': page['page'],
                'volumePage': ev['page'], 'volume': volume['label'], 'sourceName': page.get('sourceName', ''),
                'locator': locator, 'text': ev['text'], 'previewUrl': page['previewUrl'], 'captionUrl': '',
                'sourceStatementId': row_id, 'sourceRecordId': source_id}
            if evidence_id not in evidence_ids:
                manifest['evidence'].append(evidence); evidence_ids.add(evidence_id)
            row = {'id': row_id, 'artifactId': source_id, 'sourceRecordId': source_id, 'artifact': item['artifact'],
                'item': record['item'], 'page': item['page'], 'volumePage': item.get('volumePage'),
                'volume': volume['label'], 'sourceName': item.get('sourceName', ''), 'locator': locator,
                'proofLocator': locator, 'predicate': pred, 'object': target['label'],
                'objectId': f"merged:{target['kind']}:{target['label']}", 'evidenceId': evidence_id,
                'quote': record['text'], 'origin': VERSION, 'binding': assertion['binding'],
                'status': '机器候选 · 尚未人工确认', 'modelScore': assertion['modelScore'],
                'extractionMethod': 'local_uie', 'issues': [],
                **{key: item[key] for key in ['imageUrl', 'detailUrl', 'pageUrl', 'imageKind', 'captionUrl'] if key in item}}
            source_rows.append(row); row_ids.add(row_id)
        for value in graph.get('interpretations', []):
            identifier = prefix+':'+value['id']
            if identifier in interpretation_ids:
                continue
            page = pages[(volume['label'], value['page'])]
            manifest.setdefault('interpretations', []).append({**value, 'id': identifier, 'page': page['page'],
                'volumePage': value['page'], 'volume': volume['label'], 'pageUrl': page['previewUrl'],
                'locator': f"{volume['label']} · PDF 第 {value['page']} 页"})
            interpretation_ids.add(identifier)
        volume['runId'] = graph.get('runId')
    row_dimensions = defaultdict(lambda: defaultdict(list))
    for row in source_rows:
        row_dimensions[row.get('sourceRecordId', row.get('artifactId'))][row['predicate']].append(row['object'])
    for item in source_items:
        source_id = item.get('sourceRecordId', item['artifactId'])
        for pred, field in FIELDS.values():
            item[field] = list(dict.fromkeys(row_dimensions[source_id][pred]))
    if manifest.get('artifactIdentity'):
        manifest['sourceItems'], manifest['sourceRows'] = source_items, source_rows
        apply_manifest_identity(manifest, manifest['artifactIdentity'])
    else:
        manifest['items'], manifest['rows'] = source_items, source_rows
    manifest['summary'].update(graphEdges=len(manifest['rows'])+2*len(manifest.get('interpretations', [])),
        interpretations=len(manifest.get('interpretations', [])),
        predicateCounts=dict(Counter(r['predicate'] for r in manifest['rows'])))
    if manifest.get('artifactIdentity'):
        manifest['identityRunId'] = ident('identity-projection', [g.get('runId') for g in graphs],
                                          manifest['artifactIdentity']['recordToCanonical'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--persist', action='store_true')
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--batch-size', type=int, default=32)
    args = parser.parse_args()
    output = DATA/'fulltext-recall'
    output.mkdir(exist_ok=True)
    if args.refresh or not (output/'artifact-candidates.json').exists():
        graphs = [load(root/'graph.json') for root in ROOTS]
        artifacts, concepts, report = RecallExtractor(output, args.batch_size).run(graphs)
        save(output/'artifact-candidates.json', artifacts); save(output/'concept-candidates.json', concepts)
        save(output/'report.json', report)
    else:
        artifacts, concepts, report = [load(output/name) for name in
            ['artifact-candidates.json', 'concept-candidates.json', 'report.json']]
    # Reload immediately before writing so extraction never restores stale graphs.
    screened = Counter()
    def screen(values):
        accepted = []
        for value in values:
            if value['value'] in labels(value['kind'], value['valueEvidence']['text']):
                accepted.append(value)
            else:
                screened[value['kind']] += 1
        return accepted
    artifacts, concepts = screen(artifacts), screen(concepts)
    report['writeScreeningRejected'] = dict(screened)
    watched = [root/'graph.json' for root in ROOTS]+[DATA/'merged/site/manifest.json']
    versions = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in watched}
    graphs = [load(root/'graph.json') for root in ROOTS]
    reports = [apply_candidates(graph, [v for v in artifacts if v['volumeNumber'] == volume],
                                [v for v in concepts if v['volumeNumber'] == volume])
               for volume, graph in enumerate(graphs, 1)]
    manifest = load(DATA/'merged/site/manifest.json')
    baseline_path = output/'baseline.json'
    baseline = load(baseline_path) if baseline_path.exists() else {'counts': atlas_counts(manifest)}
    if args.write:
        for path, stamp in versions.items():
            if (path.stat().st_size, path.stat().st_mtime_ns) != stamp:
                raise RuntimeError('Concurrent source update; rerun with cached predictions: '+str(path))
        backup = DATA/'archive'/('before-fulltext-recall-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
        backup.mkdir(parents=True)
        shutil.copyfile(DATA/'merged/site/manifest.json', backup/'manifest.json')
        if not baseline_path.exists(): save(baseline_path, {**baseline, 'backup': str(backup.relative_to(ROOT))})
        for volume, (root, graph) in enumerate(zip(ROOTS, graphs), 1):
            shutil.copyfile(root/'graph.json', backup/f'vol{volume}.graph.json')
            if args.persist:
                source_path = Path(load(root/'source.json')['path'])
                if not source_path.is_absolute(): source_path = ROOT/source_path
                database_report = persist(graph, Path.home()/'.local/share/cn.wikibridge.desktop', source_file=source_path)
                save(root/'database-import.json', database_report)
            save(root/'graph.json', graph)
            save(root/'summary.json', graph['summary'])
    update_manifest(manifest, graphs)
    report['atlasComparison'] = {'before': baseline['counts'], 'after': atlas_counts(manifest)}
    if args.write:
        site = DATA/'merged/site'; path = site/'manifest.json'
        if (path.stat().st_size, path.stat().st_mtime_ns) != versions[path]:
            raise RuntimeError('Concurrent atlas update; rerun with cached predictions')
        save(path, manifest)
        reasoner = re.sub(r'(?m)^export\s+', '', (ROOT/'src/kg-reasoner.js').read_text())
        (site/'index.html').write_text((ROOT/'scripts/atlas_viewer.html').read_text()
            .replace('__REASONER_JS__', reasoner, 1)
            .replace('__MANIFEST_JSON__', json.dumps(manifest, ensure_ascii=False).replace('<', '\\u003c'), 1))
    report.update(state='complete' if args.write else 'dry_run', additions=reports)
    save(output/'status.json', report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
