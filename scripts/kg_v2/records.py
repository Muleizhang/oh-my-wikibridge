"""Extract typed attributes within a single caption; never nearest-name binding."""
import re

from .common import evidence, ident
from .documents import box_union
from .values import extract_quantities


def local_evidence(document, start, end):
    blocks = [b for b in document['blocks'] if b['start'] < end and b['end'] > start]
    return evidence(document['page'], start, end, document['text'], box_union([b['bbox'] for b in blocks]),
                    blocks[0]['id'] if len(blocks) == 1 else None, document['engine'])


def attributes(document, records):
    result = []
    for record in records:
        start, stop = record['span']
        for value in extract_quantities(document['text'][start:stop]):
            a, b = value['span']; a += start; b += start
            result.append({'id': ident('statement', record['id'], value['predicate'], value['object'], a),
                'subject': None if record['issues'] else ident('entity', record['id']),
                'recordId': record['id'], 'predicate': value['predicate'], 'label': value['label'],
                'object': value['object'], 'qualifiers': [],
                'evidence': [local_evidence(document, a, b)], 'origin': 'record_field_parser',
                'binding': {'kind': 'caption_scope', 'recordId': record['id'], 'item': record['item']},
                'issues': list(record['issues']), 'status': 'candidate'})
    return result


def events_and_places(document, records):
    events, place_entities, statements = [], {}, []
    for record in records:
        if record['issues']:
            continue
        # Caption location lines are explicit scoped fields, not general prose grammar.
        lines = list(re.finditer(r'[^\n]+', record['text']))
        for line in lines[1:]:
            text = line.group().strip()
            for match in re.finditer(r'(?P<place>(?:(?!出土|发现|采集|收藏|藏)[\u3400-\u9fff、，]){2,45})(?P<verb>出土|发现|采集|收藏|藏)', text):
                raw_place = match['place']
                if any(x in raw_place for x in ('厘米', '毫米', '高', '口径')):
                    continue
                begin = record['span'][0] + line.start() + line.group().find(text) + match.start()
                end = begin + len(match.group())
                kind = {'出土': 'excavation', '发现': 'discovery', '采集': 'collection', '藏': 'custody', '收藏': 'custody'}[match['verb']]
                # A multi-place list cannot automatically mean independent events at every place.
                issues = ['multiple_places_in_one_field'] if re.search('[、，]', raw_place) else []
                pid = ident('entity', 'place_mention', record['id'], begin, raw_place)
                place_entities[pid] = {'id': pid, 'label': raw_place, 'kind': 'organization' if kind == 'custody' else 'place',
                    'scope': 'source_mention', 'identityStatus': 'unresolved', 'aliases': [raw_place],
                    'evidence': [local_evidence(document, begin, begin + len(raw_place))]}
                event_id = ident('event', record['id'], kind, begin)
                evt = {'id': event_id, 'kind': kind, 'label': match['verb'], 'recordId': record['id'],
                    'participants': [{'role': 'object', 'entityId': ident('entity', record['id'])},
                                     {'role': 'holder' if kind == 'custody' else 'location', 'entityId': pid}],
                    'time': None, 'evidence': [local_evidence(document, begin, end)], 'status': 'candidate', 'issues': issues}
                events.append(evt)
                statements.append({'id': ident('statement', event_id), 'subject': ident('entity', record['id']),
                    'recordId': record['id'], 'predicate': 'participated_in', 'label': match['verb'],
                    'object': {'kind': 'event', 'id': event_id}, 'qualifiers': [], 'evidence': evt['evidence'],
                    'origin': 'record_event_field', 'binding': {'kind': 'caption_scope', 'item': record['item']},
                    'issues': issues, 'status': 'candidate'})
    return events, list(place_entities.values()), statements
