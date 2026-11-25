#!/usr/bin/env python3
"""Validate typed values, record ownership and unmodified source provenance."""
from decimal import Decimal

from kg_v2.common import OUT, load, save
from kg_v2.values import value_kind


def validate(graph):
    documents = {(d['page'], d['engine']): d for d in graph['documents']}
    records = {r['id']: r for r in graph['records']}
    entities = {e['id']: e for e in graph['entities']}
    events = {e['id']: e for e in graph['events']}
    statements = {s['id']: s for s in graph['assertions']}
    if len(statements) != len(graph['assertions']):
        raise ValueError('Duplicate statement IDs')
    for entity in entities.values():
        if value_kind(entity['label']):
            raise ValueError('Literal incorrectly promoted to entity: ' + entity['label'])
    def check_evidence(ev):
        doc = documents[(ev['page'], ev['engine'])]; a, b = ev['span']
        if not 0 <= a < b <= len(doc['text']) or doc['text'][a:b] != ev['text']:
            raise ValueError('Evidence does not exactly match its OCR stream')
        if ev.get('bbox'):
            x1, y1, x2, y2 = ev['bbox']; width, height = doc['imageSize']
            if not 0 <= x1 <= x2 <= width or not 0 <= y1 <= y2 <= height:
                raise ValueError('Evidence bounding box outside page')
    for obj in graph['entities'] + graph['assertions'] + graph['events'] + graph['mentions']:
        for ev in obj.get('evidence', []): check_evidence(ev)
    interpretations = graph.get('interpretations', [])
    if len({record['id'] for record in interpretations}) != len(interpretations):
        raise ValueError('Duplicate interpretation IDs')
    for record in interpretations:
        for ev in [*record['evidence'], record['subjectEvidence'], record['valueEvidence']]:
            check_evidence(ev)
        if record.get('extractionMethod') != 'local_uie' or record.get('reviewStatus') != 'unreviewed':
            raise ValueError('Interpretations require model extraction and retain machine review status')
        if not record['subject']['label'] or not record['value']:
            raise ValueError('Empty interpretation endpoint')
    for s in statements.values():
        obj = s['object']
        if s['subject'] is not None and s['subject'] not in entities:
            raise ValueError('Dangling subject')
        if obj['kind'] == 'entity' and obj['id'] not in entities:
            raise ValueError('Dangling object')
        if obj['kind'] == 'event' and obj['id'] not in events:
            raise ValueError('Dangling event')
        if obj['kind'] == 'quantity':
            if Decimal(obj['lower']) > Decimal(obj['upper']): raise ValueError('Reversed quantity interval')
            r = records.get(s.get('recordId'))
            if r:
                for ev in s['evidence']:
                    if not r['span'][0] <= ev['span'][0] < ev['span'][1] <= r['span'][1]:
                        raise ValueError('Quantity crosses artifact record boundary')
        if s['reviewStatus'] != 'unreviewed':
            raise ValueError('Machine stage must not forge human review')
    for event in events.values():
        for role in event['participants']:
            if role['entityId'] not in entities: raise ValueError('Dangling event participant')
    if graph['publication']['automaticAcceptance']:
        raise ValueError('Full publication gate is not calibrated yet')
    if graph.get('artifactIdentity'):
        identity = graph['artifactIdentity']
        canonical = {e['id']: e for e in identity['entities']}
        if len(canonical) != len(identity['entities']): raise ValueError('Duplicate canonical artifacts')
        owned, record_owned = {}, {}
        for artifact in canonical.values():
            if artifact.get('reviewStatus') != 'unreviewed' or artifact.get('independentHistoricalIdentityVerified'):
                raise ValueError('Automatic identity must not forge historical/human verification')
            for member in artifact['members']:
                if member['sourceEntityId'] != f"{member['volume']}:{member['entityId']}":
                    raise ValueError('Invalid artifact namespace')
                if member['volume'] != identity['volume']: continue
                eid, rid = member['entityId'], member['recordId']
                if eid in owned or rid in record_owned: raise ValueError('Duplicate source artifact membership')
                if entities.get(eid, {}).get('kind') != 'artifact' or entities[eid].get('recordId') != rid or rid not in records:
                    raise ValueError('Dangling canonical artifact source')
                owned[eid], record_owned[rid] = artifact['id'], artifact['id']
                for value in member.get('dimensionEvidence', []) + member.get('propertyEvidence', []):
                    if value['statementId'] not in statements: raise ValueError('Dangling identity statement evidence')
                for value in member.get('locationEvidence', []):
                    if value.get('eventId') and value['eventId'] not in events: raise ValueError('Dangling identity event')
        if set(owned) != {e['id'] for e in entities.values() if e['kind'] == 'artifact'}:
            raise ValueError('Incomplete canonical artifact coverage')
        if owned != identity['sourceToCanonical'] or record_owned != identity['recordToCanonical']:
            raise ValueError('Identity maps disagree with canonical membership')
    return {'status': 'passed', 'assertions': len(statements), 'literalEntities': 0,
        'sourceStreams': len(documents), 'automaticAcceptance': False,
        'semanticAccuracy': 'See evaluation; structural validation is not semantic verification'}


if __name__ == '__main__':
    report = validate(load(OUT / 'graph.json'))
    save(OUT / 'validation.json', report)
    print(report)
