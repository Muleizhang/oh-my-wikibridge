#!/usr/bin/env python3
"""Build source records, typed assertions and explicit unresolved mentions."""
import hashlib
import re
from collections import Counter, defaultdict

from kg_v2.common import OUT, ident, load, save, selected_pages
from kg_v2.contracts import publication_gate, statement_issues
from kg_v2.records import attributes, events_and_places, local_evidence
from kg_v2.values import FIELD_LABELS, parse_quantity, value_kind
from kg_v2.caption_fields import supplement_relations

PRONOUNS = {'它', '它们', '其', '有的', '有些', '这种', '这些', '此', '这', '作法', '方法', '图案', '纹饰'}


def concept_kind(text):
    if text in PRONOUNS or len(text) < 2 or len(text) > 26 or re.search('[，。；、]', text) or value_kind(text):
        return None
    for suffixes, kind in [(('纹', '纹样'), 'motif'), (('法', '工艺', '技法'), 'technique'),
                           (('文化',), 'culture'), (('遗址', '墓地', '县', '省', '村'), 'place')]:
        if text.endswith(suffixes):
            return kind
    return None


def main():
    documents, records, entities, statements, events, mentions, disagreements, baseline_values = [], [], {}, [], [], [], [], []
    pages = selected_pages(); baseline_records = {}
    raw_open = []
    for page in pages:
        extraction = load(OUT / f'extractions/v1-p{page:04d}.json')
        doc, old = extraction['document'], extraction['baselineDocument']
        documents += [doc, old]; records += extraction['records']
        baseline_records.update({(r['page'], r['item'], r['occurrence']): r for r in extraction['baselineRecords']})
        by_record = {r['id']: r for r in extraction['records']}
        new_values = attributes(doc, extraction['records'])
        old_values = attributes(old, extraction['baselineRecords']); baseline_values += old_values
        old_key = defaultdict(list)
        for s in old_values:
            old_key[(s['binding']['item'], s['predicate'])].append(s)
        for s in new_values:
            matches = old_key.get((s['binding']['item'], s['predicate']), [])
            if matches and any(x['object']['normalized'] != s['object']['normalized'] for x in matches):
                s['issues'].append('ocr_numeric_disagreement')
                disagreements.append({'statementId': s['id'], 'kind': 'numeric_disagreement',
                    'page': page, 'new': s['object'], 'old': [x['object'] for x in matches],
                    'evidence': s['evidence'] + [e for x in matches for e in x['evidence']]})
        statements += new_values
        for r in extraction['records']:
            if r['issues']:
                continue
            eid = ident('entity', r['id'])
            entities[eid] = {'id': eid, 'label': r['label'], 'kind': 'artifact', 'recordId': r['id'],
                'scope': 'source_record', 'identityStatus': 'cross_record_identity_unresolved',
                'aliases': [r['label']], 'evidence': [local_evidence(doc, *r['titleSpan'])],
                'description': r['text'], 'objectMultiplicity': 'not_independently_verified'}
        evts, places, stmts = events_and_places(doc, extraction['records'])
        events += evts; entities.update({e['id']: e for e in places}); statements += stmts
        for field in extraction['fields']:
            record = by_record[field['recordId']]
            eid = ident('entity', record['id'])
            if eid not in entities:
                continue
            start, end = field['span']; raw = field['text']; kind = field['kind']
            if doc['text'][start:end] != raw:
                raise ValueError('UIE field lost provenance')
            ev = local_evidence(doc, start, end)
            # Location/holder fields must agree with the explicit event marker.
            if kind in {'place', 'organization'}:
                marker = '出土' if kind == 'place' else '藏'
                if marker not in record['text'][end-record['span'][0]:end-record['span'][0]+12]:
                    mentions.append({'id': ident('mention', page, start, end, kind), 'label': raw,
                        'typeProposal': kind, 'entityId': None, 'status': 'unresolved',
                        'reason': '字段提示与局部事件标记不一致', 'evidence': [ev]})
                # Explicit field parser already stores the event; avoid duplicate shortcuts.
                continue
            issue = []
            if value_kind(raw):
                obj = parse_quantity(raw) or {'kind': 'time', 'raw': raw, 'value': raw, 'precision': 'year'}
                issue.append('field_value_type_conflict')
            else:
                target = ident('entity', record['id'], kind, start, end)
                entities[target] = {'id': target, 'label': raw, 'kind': kind, 'scope': 'source_mention',
                    'identityStatus': 'unresolved', 'aliases': [raw], 'evidence': [ev], 'description': record['text']}
                obj = {'kind': 'entity', 'id': target}
            pred = {'motif': 'decorated_with', 'period': 'period', 'material': 'made_of', 'technique': 'uses_technique'}[kind]
            statements.append({'id': ident('statement', record['id'], pred, start, end), 'subject': eid,
                'recordId': record['id'], 'predicate': pred, 'label': field['field'], 'object': obj,
                'qualifiers': [], 'evidence': [ev], 'origin': 'uie_caption_field', 'issues': issue,
                'binding': {'kind': 'caption_scope', 'item': record['item']},
                'modelScore': field['modelScore'], 'status': 'candidate'})

        extra_entities, extra_statements = supplement_relations(extraction, entities, statements)
        entities.update({e['id']: e for e in extra_entities})
        statements += extra_statements

        # Open prose remains open; unidentified phrases do not become graph entities.
        for window in extraction['prose']:
            for fact in window['facts']:
                ev = local_evidence(doc, window['start'], window['end'])
                args = {}; ids = {}; argument_evidence = {}
                for role in ('subject', 'object'):
                    a, b = fact['template_spans'][role]; a += window['start']; b += window['start']
                    raw = fact[role]; kind = concept_kind(raw); mid = ident('mention', page, a, b)
                    arg_ev = local_evidence(doc, a, b); argument_evidence[role] = arg_ev
                    if kind:
                        target = ident('entity', mid, kind)
                        entities.setdefault(target, {'id': target, 'label': raw, 'kind': kind,
                            'scope': 'source_mention', 'identityStatus': 'unresolved', 'aliases': [raw],
                            'evidence': [arg_ev], 'description': window['paragraphContext']})
                        args[role] = {'kind': 'entity', 'id': target}; ids[role] = target
                    else:
                        parsed = parse_quantity(raw)
                        args[role] = parsed or {'kind': 'unresolved', 'mentionId': mid, 'raw': raw}
                        ids[role] = None
                    mentions.append({'id': mid, 'label': raw, 'typeProposal': kind,
                        'entityId': ids[role], 'status': 'typed_candidate' if kind else 'unresolved',
                        'reason': '类型后缀候选，待核验' if kind else '未确定身份，不创建默认实体', 'evidence': [arg_ev]})
                predicate = fact['predicate']
                pred = 'alias' if re.fullmatch(r'[亦又也习]?(称|称为|称作|叫|叫作)', predicate) else 'open:' + predicate
                issues = ['semantic_support_pending']
                qualifiers = fact.get('qualifiers', [])
                statements.append({'id': ident('statement', page, fact['template_spans'], window['start'], predicate),
                    'subject': ids['subject'], 'subjectMention': args['subject'], 'recordId': None,
                    'predicate': pred, 'label': predicate, 'object': args['object'],
                    'qualifiers': qualifiers, 'evidence': [ev], 'argumentEvidence': argument_evidence,
                    'origin': 'ltp_open_template', 'issues': issues,
                    'binding': {'kind': 'sentence_with_paragraph_context', 'paragraph': window['paragraphContext']},
                    'status': 'candidate'})
                raw_open.append({'predicate': predicate, 'subjectType': concept_kind(fact['subject']),
                                 'objectType': concept_kind(fact['object']), 'evidence': ev})
            # Temporal roles attach to events; never turn collection dates into artifact age.
            for frame in window['frames']:
                if frame['trigger'] not in {'采集', '采集到', '出土', '发现', '收藏', '入藏'}:
                    continue
                times = [a for a in frame['arguments'] if a['role'] in {'ARGM-TMP', '时间语境'}]
                if not times:
                    continue
                objects = [a for a in frame['arguments'] if a['role'] == 'A1']
                events.append({'id': ident('event', page, window['start'], frame['trigger'], frame['arguments']),
                    'kind': 'collection' if frame['trigger'].startswith('采集') else 'source_event',
                    'label': frame['trigger'], 'recordId': None, 'participants': [],
                    'unresolvedArguments': objects + [a for a in frame['arguments'] if a['role'] not in {'A1', 'ARGM-TMP'}],
                    'time': {'kind': 'time', 'raw': times[0]['text'], 'value': times[0]['text'], 'precision': 'source'},
                    'evidence': [local_evidence(doc, window['start'], window['end'])],
                    'status': 'candidate', 'issues': ['event_participant_identity_pending']})

    # Preserve every competing quantity assertion, marking conflicts rather than overwriting.
    grouped = defaultdict(list)
    for s in statements:
        if s['object']['kind'] == 'quantity': grouped[(s['subject'], s['predicate'])].append(s)
    for values in grouped.values():
        distinct = {str(v['object']['normalized']) for v in values}
        if len(distinct) > 1:
            for s in values: s['issues'].append('conflicting_values')
    for s in statements:
        s['issues'] = sorted(set(s['issues'] + statement_issues(s, entities)))
        s['reviewStatus'] = 'unreviewed'
    definitions = []
    for predicate in sorted({p['predicate'] for p in raw_open}):
        examples = [p for p in raw_open if p['predicate'] == predicate]
        definitions.append({'id': ident('predicate', predicate), 'rawPredicate': predicate,
            'status': 'definition_pending', 'definition': None, 'examples': examples[:5], 'candidateCount': len(examples)})
    # Audit OCR changes without silently replacing the old stream.
    for record in records:
        previous = baseline_records.get((record['page'], record['item'], record['occurrence']))
        if previous and previous['label'] != record['label']:
            disagreements.append({'kind': 'label_disagreement', 'recordId': record['id'], 'page': record['page'],
                'old': previous['label'], 'new': record['label'], 'resolution': 'two source versions retained; not automatically verified'})
    graph = {'version': 'typed-kg-v2', 'selection': pages, 'documents': documents, 'records': records,
        'entities': list(entities.values()), 'assertions': list({s['id']: s for s in statements}.values()),
        'events': list({e['id']: e for e in events}.values()),
        'mentions': list({m['id']: m for m in mentions}.values()), 'ocrDisagreements': disagreements,
        'relationProposals': definitions, 'identityProposals': [], 'identityDecisions': [],
        'publication': publication_gate({}), 'reviewStatus': 'unreviewed'}
    graph['summary'] = {'pages': len(pages), 'records': len(records), 'entities': len(entities),
        'quantities': sum(s['object']['kind'] == 'quantity' for s in graph['assertions']),
        'assertions': len(graph['assertions']), 'events': len(graph['events']),
        'unresolvedMentions': sum(m['entityId'] is None for m in graph['mentions']),
        'pendingAssertions': sum(bool(s['issues']) for s in graph['assertions']), 'verifiedAssertions': 0,
        'relationProposals': len(definitions), 'ocrDisagreements': len(disagreements)}
    save(OUT / 'graph.json', graph)
    save(OUT / 'baseline-quantity-assertions.json', baseline_values)
    save(OUT / 'summary.json', graph['summary'])
    print(graph['summary'], flush=True)


if __name__ == '__main__':
    main()
