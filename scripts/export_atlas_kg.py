#!/usr/bin/env python3
"""Export the local typed KG into the standalone motif star-atlas manifest."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re

from PIL import Image
from kg_v2.atlas_site import render_atlas
from kg_v2.plate_images import attach_plate_images, source_pdf
from kg_v2.identity_manifest import apply_manifest_identity

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / 'data/local-kg'
PREDICATES = {
    'artifact_type': 'artifact_type',
    'period': 'period',
    'decorated_with': 'motif',
    'made_of': 'material',
    'decorated_with_material': 'decoration_material',
    'has_shape': 'shape',
    'uses_technique': 'technique',
    'belongs_to_culture': 'culture',
    'has_composition': 'composition',
    'decorated_part': 'decoration_part',
    'decoration_role': 'decoration_role',
    'excavated_at': 'place',
    'discovered_at': 'place',
    'collected_at': 'place',
    'held_by': 'organization',
}
STATUS = '机器候选 · 尚未人工确认'
PERIOD_LABEL = re.compile(
    r'新石器|原始社会|仰韶|半坡|庙底沟|马家窑|半山|马厂|河姆渡|良渚|龙山|大汶口|红山|裴李岗|磁山|屈家岭|马家浜|大溪|'
    r'夏代|二里头|夏文化|商|殷|周代|周朝|西周|东周|春秋|战国|秦|西汉|东汉|两汉|汉|'
    r'三国|曹魏|蜀汉|孙吴|魏晋|两晋|西晋|东晋|南北朝|北朝|南朝|十六国|北魏|东魏|西魏|北齐|北周|'
    r'隋|唐|五代|十国|宋|辽|金|西夏|元|明|清|民国|近代|现代|当代'
)


def read_json(path):
    return json.loads(Path(path).read_text())


def evidence_box(evidence, documents):
    bbox = evidence.get('bbox')
    doc = documents.get((evidence.get('page'), evidence.get('engine')))
    size = doc.get('imageSize') if doc else None
    if not bbox or not size or not size[0] or not size[1]:
        return None
    return [bbox[0] / size[0], bbox[1] / size[1], bbox[2] / size[0], bbox[3] / size[1]]


def export(graph_path, image_manifest_path, image_dir, output, plate_manifest_path=None):
    graph = read_json(graph_path)
    image_manifest = read_json(image_manifest_path)
    entities = {entity['id']: entity for entity in graph.get('entities', [])}
    records = {record['id']: record for record in graph.get('records', [])}
    documents = {(doc['page'], doc['engine']): doc for doc in graph.get('documents', [])}
    concept_by_member = {}
    for concept in graph.get('identityReview', {}).get('concepts', []):
        if concept.get('kind') not in set(PREDICATES.values()) - {'place', 'organization'}:
            continue
        target = (concept['id'], concept['name'])
        for member_id in concept.get('memberIds', []):
            concept_by_member.setdefault(member_id, target)

    source_name = next((doc.get('source') for doc in graph.get('documents', []) if doc.get('source')), '本地语料')
    row_groups = defaultdict(list)
    evidence_items = {}
    counts = Counter()
    omitted_periods = defaultdict(lambda: {'count': 0, 'pages': set(), 'records': set()})
    supported_pages = set()
    for statement in graph.get('assertions', []):
        predicate = statement.get('predicate')
        if predicate not in PREDICATES:
            continue
        record_id = statement.get('recordId')
        subject = entities.get(statement.get('subject'))
        if not record_id and subject:
            record_id = subject.get('recordId')
        record = records.get(record_id)
        target = entities.get((statement.get('object') or {}).get('id'))
        expected_kind = PREDICATES[predicate]
        if not record or not subject or subject.get('kind') != 'artifact':
            continue
        if not target or target.get('kind') != expected_kind:
            continue
        evidence = statement.get('evidence') or []
        if not evidence:
            continue

        if predicate == 'period' and not PERIOD_LABEL.search(target['label']):
            omitted = omitted_periods[target['label']]
            omitted['count'] += 1
            omitted['pages'].add(int(evidence[0]['page']))
            omitted['records'].add(record_id)
            continue

        page = int(evidence[0]['page'])
        locator = f"PDF 第 {record['page']} 页 · 图注 {record.get('item', '')}"
        row_groups[record_id].append({
            'statement': statement,
            'target': target,
            'evidence': evidence[0],
            'page': page,
            'locator': locator,
        })
        supported_pages.update([int(record['page']), page])
        counts[predicate] += 1

    if not row_groups:
        raise ValueError('No graphable artifact relations found in the local KG')

    omitted_period_rows = [{
        'label': label,
        'count': value['count'],
        'pages': sorted(value['pages']),
        'records': len(value['records']),
    } for label, value in sorted(omitted_periods.items())]

    output = Path(output).resolve()
    thumbs = output / 'thumbs'
    thumbs.mkdir(parents=True, exist_ok=True)
    page_assets = image_manifest.get('pages', {})
    source_pages = sorted({int(p) for p in graph.get('selection', [])} or {int(d['page']) for d in graph['documents']})
    preview_urls = {}
    for index, page in enumerate(source_pages, 1):
        asset = page_assets.get(str(page))
        source = Path(image_dir) / asset['file'] if asset else None
        if not source or not source.is_file():
            continue
        thumb_name = f'p{page:04d}.jpg'
        thumb_path = thumbs / thumb_name
        with Image.open(source) as image:
            image.thumbnail((640, 640), Image.Resampling.LANCZOS)
            image.convert('RGB').save(thumb_path, format='JPEG', quality=76, optimize=True)
        preview_urls[page] = f'thumbs/{thumb_name}'
        if index % 100 == 0:
            print(f'Page previews {index}/{len(source_pages)}', flush=True)

    rows, items, pages = [], [], []
    entries_by_page = Counter()
    for record_id, relations in sorted(row_groups.items(), key=lambda pair: (
            int(records[pair[0]]['page']), int(records[pair[0]].get('item', 0)), pair[0])):
        record = records[record_id]
        page = int(record['page'])
        preview = preview_urls.get(page, '')
        first_evidence_id = None
        for relation in relations:
            statement = relation['statement']
            target = relation['target']
            evidence = relation['evidence']
            evidence_id = f"{statement['id']}:e0"
            first_evidence_id = first_evidence_id or evidence_id
            evidence_page = int(evidence['page'])
            evidence_preview = preview_urls.get(evidence_page, '')
            evidence_items[evidence_id] = {
                'id': evidence_id,
                'sourceId': graph.get('runId', source_name),
                'sourceName': source_name,
                'kind': 'page',
                'page': evidence_page,
                'ordinal': evidence_page,
                'locator': relation['locator'],
                'text': evidence.get('text', ''),
                'previewUrl': evidence_preview,
                'captionUrl': '',
                'bbox': evidence_box(evidence, documents),
                'status': STATUS,
            }
            concept_id, object_label = concept_by_member.get(
                target['id'], (target['id'], target['label']))
            rows.append({
                'id': statement['id'],
                'artifactId': record_id,
                'artifact': record['label'],
                'item': record.get('item'),
                'page': page,
                'locator': relation['locator'],
                'proofLocator': relation['locator'],
                'predicate': statement['predicate'],
                'objectId': concept_id,
                'object': object_label,
                'quote': evidence.get('text', ''),
                'evidenceId': evidence_id,
                'qualifiers': statement.get('qualifiers', []),
                'issues': statement.get('issues', []),
                'status': STATUS,
                'origin': statement.get('origin'),
                'projectionStatus': statement.get('projectionStatus'),
                'supersededBy': statement.get('supersededBy', []),
                'correction': statement.get('correction'),
                'binding': statement.get('binding'),
                'supportingEvidence': [{**ev, 'previewUrl': preview_urls.get(int(ev['page']), ''),
                    'normalizedBbox': evidence_box(ev, documents)} for ev in statement.get('evidence', [])],
            })
        entries_by_page[page] += 1
        items.append({
            'artifactId': record_id,
            'artifact': record['label'],
            'item': record.get('item'),
            'page': page,
            'locator': f"PDF 第 {page} 页 · 图注 {record.get('item', '')}",
            'status': STATUS,
            'quote': record.get('text', ''),
            'evidenceId': first_evidence_id,
            'imageUrl': preview,
            'detailUrl': preview,
            'captionUrl': '',
            'pageUrl': preview,
            'imageKind': 'page',
            'detailLabel': '原书整页',
        })

    for page in source_pages:
        pages.append({
            'page': page,
            'previewUrl': preview_urls.get(page, ''),
            'entries': entries_by_page[page],
        })

    source_title = re.sub(r'_\d+$', '', Path(source_name).stem).replace('_', ' · ')
    title = f'{source_title} · 本地知识图谱候选（尚未人工确认）'
    manifest = {
        'title': title,
        'sourceName': source_name,
        'runId': graph.get('runId'),
        'status': STATUS,
        'summary': {
            'sourcePages': graph.get('summary', {}).get('pages', 0),
            'sourceRecords': len(records),
            'graphItems': len(items),
            'graphEdges': len(rows),
            'graphablePages': len(supported_pages),
            'unreviewedAssertions': sum(counts.values()),
            'predicateCounts': dict(counts),
            'omittedUnrecognizedPeriodCandidates': sum(x['count'] for x in omitted_period_rows),
            'quantitiesNotRenderedAsEdges': graph.get('summary', {}).get('quantities', 0),
            'openRelationsNotRenderedAsEdges': sum(
                1 for assertion in graph.get('assertions', [])
                if str(assertion.get('predicate', '')).startswith('open:')),
        },
        'pages': pages,
        'items': items,
        'rows': rows,
        'evidence': list(evidence_items.values()),
        'omittedPeriodCandidates': omitted_period_rows,
        'interpretations': [{**record, 'pageUrl': preview_urls.get(record['page'], ''),
                            'locator': f"PDF 第 {record['page']} 页"}
                           for record in graph.get('interpretations', [])],
    }
    explicit_plate_manifest = plate_manifest_path is not None
    plate_manifest_path = (Path(plate_manifest_path) if plate_manifest_path else
                           Path(graph_path).parent / 'plate-images' / 'manifest.json')
    if plate_manifest_path.is_file():
        attach_plate_images(manifest, plate_manifest_path, source_pdf(graph_path), output)
    elif explicit_plate_manifest:
        raise FileNotFoundError(plate_manifest_path)
    apply_manifest_identity(manifest, graph.get('artifactIdentity'))
    output.mkdir(parents=True, exist_ok=True)
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False))
    (output / 'atlas_viewer.html').write_text(render_atlas(''), encoding='utf-8')
    print(json.dumps(manifest['summary'], ensure_ascii=False, indent=2))
    print(f"Star atlas ready: {output / 'atlas_viewer.html'}")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--graph', type=Path, default=DEFAULT_DATA / 'graph.json')
    parser.add_argument('--page-images', type=Path, default=DEFAULT_DATA / 'page-images.json')
    parser.add_argument('--image-dir', type=Path, default=DEFAULT_DATA / 'images')
    parser.add_argument('--output', type=Path, default=DEFAULT_DATA / 'star-atlas')
    parser.add_argument('--plate-manifest', type=Path,
                        help='Source-verified artifact/detail/caption crops; defaults to graph directory/plate-images/manifest.json')
    args = parser.parse_args()
    export(args.graph, args.page_images, args.image_dir, args.output, args.plate_manifest)


if __name__ == '__main__':
    main()
