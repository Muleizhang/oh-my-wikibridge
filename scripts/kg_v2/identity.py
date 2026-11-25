"""Group name occurrences for review without making identity decisions."""
import re
import unicodedata
from collections import defaultdict

from .common import ident

NORMALIZATION_VERSION = 'name-format-v1'
CONCEPT_KINDS = {'motif', 'period', 'technique', 'material', 'culture'}
HAN_GAP = re.compile(r'(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])')


def normalize_name(text):
    # Keep the original label/evidence; this key is only for retrieval/grouping.
    # Preserve word boundaries in names such as "New York".
    text = ' '.join(unicodedata.normalize('NFKC', text).split())
    return HAN_GAP.sub('', text)


def lexical_candidates(entities, index):
    entity = entities[index]
    names = {normalize_name(n) for n in [entity['label'], *entity.get('aliases', [])]} - {''}
    return [i for i, other in enumerate(entities) if i != index and names.intersection(
        normalize_name(n) for n in [other['label'], *other.get('aliases', [])])]


def lexical_candidate_index(entities, max_bucket=64, anchor_count=4):
    buckets = defaultdict(set)
    for index, entity in enumerate(entities):
        for name in {normalize_name(n) for n in [entity['label'], *entity.get('aliases', [])]} - {''}:
            buckets[name].add(index)
    candidates = [set() for _ in entities]
    for members in buckets.values():
        members = sorted(members)
        if len(members) <= max_bucket:
            for offset, left in enumerate(members):
                candidates[left].update(members[:offset]); candidates[left].update(members[offset+1:])
        else:
            anchors = members[:anchor_count]
            for left in members:
                candidates[left].update(anchor for anchor in anchors if anchor != left)
                if left in anchors:
                    candidates[left].update(members[anchor_count:])
    return candidates


def build_identity_review(graph):
    entities = {e['id']: e for e in graph['entities']}
    documents = {(d['page'], d['engine']): d for d in graph['documents']}
    records = {r['id']: r for r in graph['records']}
    records_by_page = defaultdict(list)
    for record in graph['records']: records_by_page[record['page']].append(record)
    sources, members, pair_groups = {}, defaultdict(list), defaultdict(list)
    different, conflicts = [], []
    for entity in entities.values():
        ev = entity['evidence'][0]
        record = records.get(entity.get('recordId'))
        if record is None:
            owners = [r for r in records_by_page[ev['page']]
                      if r.get('engine', 'ppstructure') == ev['engine']
                      and r['span'][0] <= ev['span'][0] < ev['span'][1] <= r['span'][1]]
            record = owners[0] if len(owners) == 1 else None
        text = documents.get((ev['page'], ev['engine']), {}).get('text', '')
        context = (record['text'] if record else entity.get('description') or
                   text[max(0, ev['span'][0]-70):ev['span'][1]+100] or ev['text'])
        key = (entity['kind'], normalize_name(entity['label']))
        members[key].append(entity['id'])
        sources[entity['id']] = {
            'entityId': entity['id'], 'rawName': entity['label'], 'normalizedName': key[1],
            'kind': entity['kind'], 'page': ev['page'], 'item': record['item'] if record else None,
            'recordId': record['id'] if record else None, 'context': context,
            'evidence': entity['evidence'],
        }
    for pair in graph['identityProposals']:
        a, b = sources[pair['left']], sources[pair['right']]
        if a['kind'] != b['kind']:
            conflicts.append(pair['id'])
        elif a['normalizedName'] == b['normalizedName'] and a['normalizedName']:
            pair_groups[(a['kind'], a['normalizedName'])].append(pair['id'])
        else:
            different.append(pair['id'])
    groups, concepts = [], []
    source_scope = graph['documents'][0].get('source', '') if graph['documents'] else ''
    for (kind, name), ids in members.items():
        if not name:
            continue
        ids = sorted(ids, key=lambda eid: (sources[eid]['page'], sources[eid]['evidence'][0]['span'][0], eid))
        concept_id = ident('concept', source_scope, kind, name) if kind in CONCEPT_KINDS else None
        group = {'id': ident('name-group', kind, name), 'name': name, 'kind': kind,
            'memberIds': ids, 'proposalIds': pair_groups[(kind, name)],
            'variants': list(dict.fromkeys(sources[eid]['rawName'] for eid in ids)),
            'pages': sorted({sources[eid]['page'] for eid in ids}), 'conceptId': concept_id,
            'identityConfirmed': False}
        if concept_id:
            concepts.append({**group, 'id': concept_id, 'status': 'name_normalized_concept',
                             'assignmentBasis': 'same normalized name and proposed type within this source'})
            for eid in ids:
                sources[eid]['conceptId'] = concept_id
        if len(ids) > 1:
            groups.append(group)
    groups.sort(key=lambda g: (-len(g['memberIds']), g['name'], g['kind']))
    concepts.sort(key=lambda g: (-len(g['memberIds']), g['name'], g['kind']))
    return {'normalizationVersion': NORMALIZATION_VERSION,
        'policy': 'Same-name, same-type motif/period/technique/material/culture mentions share a source-scoped concept. Artifacts, places and organizations retain separate identities. Manual same-name rejections suspend concept grouping in the graph view.',
        'sources': sources, 'groups': groups, 'concepts': concepts, 'differentNameProposalIds': different,
        'typeConflictProposalIds': conflicts,
        'summary': {'nameGroups': len(groups), 'groupedOccurrences': sum(len(g['memberIds']) for g in groups),
                    'concepts': len(concepts), 'conceptOccurrences': sum(len(c['memberIds']) for c in concepts),
                    'instanceNameGroups': sum(not g['conceptId'] for g in groups),
                    'sameNamePairs': sum(len(g['proposalIds']) for g in groups),
                    'differentNamePairs': len(different), 'typeConflictPairs': len(conflicts),
                    'totalPairs': len(graph['identityProposals']), 'automaticIdentityMerges': 0}}
