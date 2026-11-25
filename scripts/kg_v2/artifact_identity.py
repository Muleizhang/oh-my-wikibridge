"""Exact, evidence-bound artifact identity rules. No embedding or transitive closure."""
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from itertools import combinations
import re

from .common import ident
from .identity import normalize_name
from .values import FIELD_LABELS, UNITS, decimal_string

VERSION = 'artifact-identity-strict-v1'
VIEW_NAMES = ('俯视图', '仰视图', '侧视图', '正视图', '背视图', '正面图', '背面图',
              '侧面图', '俯视', '仰视', '侧视', '正视', '背视', '正面', '背面', '侧面',
              '纹饰展开图', '展开图')
VIEW = re.compile(r'(?:(?:上|下|左|右|中)\s*[:：]\s*)?(?:' + '|'.join(VIEW_NAMES) + r')')
PROPERTIES = {'period', 'made_of', 'artifact_type', 'belongs_to_culture', 'accession_number',
              'inventory_number', 'catalog_number'}
CONTEXTUAL = {'page_heading_inheritance', 'same_page_context', 'contextual_period_assignment',
              'catalog_section_context', 'same_page_culture_context'}
MATERIAL_PARENT = {'青铜': '铜', '红铜': '铜', '黄铜': '铜', '白陶': '陶', '彩陶': '陶',
                   '黑陶': '陶', '灰陶': '陶', '青瓷': '瓷', '白瓷': '瓷'}
PERIOD_PARENT = {'早商': '商代', '晚商': '商代', '殷代': '商代', '商': '商代',
                 '西周': '周代', '东周': '周代', '春秋': '东周', '战国': '东周',
                 '西汉': '汉代', '东汉': '汉代', '汉': '汉代', '唐': '唐代'}


def name_key(text):
    """Remove a parenthetical only when its entire content is a view description."""
    text = normalize_name(text)
    def replace(match):
        parts = re.split(r'[、,，;；/]', match[1])
        return '' if parts and all(VIEW.fullmatch(p.strip()) for p in parts) else match[0]
    return normalize_name(re.sub(r'\(([^()]*)\)', replace, text))


def source_id(volume, entity_id):
    return f'{volume}:{entity_id}'


def single_id(member):
    return ident('canonical-artifact', 'source-record', member['sourceEntityId'])


def bound_evidence(obj, record):
    """A nearby page/location is insufficient: require exact caption ownership."""
    evidence = obj.get('evidence') or []
    if not evidence or obj.get('recordId') != record['id']:
        return False
    for ev in evidence:
        span = ev.get('span', [])
        if (ev.get('page') != record['page'] or ev.get('engine') != record.get('engine', 'ppstructure')
            or len(span) != 2 or not record['span'][0] <= span[0] < span[1] <= record['span'][1]):
            return False
        start, end = span[0] - record['span'][0], span[1] - record['span'][0]
        if record['text'][start:end] != ev.get('text'):
            return False
    return True


def quantity_key(obj):
    unit = UNITS.get(str(obj.get('unit', '')).lower())
    if not unit or obj.get('approximate') or obj.get('qualifier'):
        raise ValueError('uncertain_or_unknown_quantity')
    _, dimension, factor, base = unit
    low, high = Decimal(str(obj['lower'])), Decimal(str(obj['upper']))
    if not low.is_finite() or low <= 0 or low != high or obj.get('dimension') != dimension:
        raise ValueError('range_or_invalid_quantity')
    normalized = decimal_string(low * Decimal(factor))
    cached = obj.get('normalized')
    if cached and (cached.get('unit') != base or Decimal(cached['lower']) != low * Decimal(factor)
                   or Decimal(cached['upper']) != high * Decimal(factor)):
        raise ValueError('quantity_normalization_disagreement')
    return dimension, normalized, base


def profiles(graph, volume, holds=()):
    entities = {e['id']: e for e in graph['entities']}
    records = {r['id']: r for r in graph['records']}
    statements, events = defaultdict(list), defaultdict(list)
    disagreements = {x.get('statementId') for x in graph.get('ocrDisagreements', [])
                     if x.get('status') not in {'resolved', 'dismissed'}}
    for s in graph['assertions']:
        statements[s.get('subject')].append(s)
    for event in graph['events']:
        for role in event.get('participants', []):
            if role.get('role') == 'object': events[role['entityId']].append(event)
    holds_by_record = defaultdict(list)
    for hold in holds:
        if hold.get('active', True): holds_by_record[hold['sourceRecordId']].append(hold)
    result = []
    for e in graph['entities']:
        if e['kind'] != 'artifact': continue
        r = records.get(e.get('recordId'))
        if r is None: raise ValueError('Source artifact without record: ' + e['id'])
        pid = source_id(volume, e['id'])
        p = {'id': pid, 'sourceEntityId': pid, 'sourceRecordId': source_id(volume, r['id']),
             'volume': volume, 'entityId': e['id'], 'recordId': r['id'], 'rawName': e['label'],
             'name': name_key(e['label']), 'page': r['page'], 'item': r['item'],
             'recordText': r['text'], 'recordIssues': r.get('issues', []),
             'issues': [], 'locations': [], 'dimensionSignature': [], 'knownProperties': {},
             'dimensionEvidence': [], 'locationEvidence': [], 'propertyEvidence': [],
             'contextualPropertiesNotUsed': []}
        issues = p['issues']
        issues.extend('record:' + str(x) for x in r.get('issues', []))
        issues.extend('entity:' + str(x) for x in e.get('issues', []))
        if not e.get('evidence') or not p['name']: issues.append('name_evidence_missing')
        if e.get('objectMultiplicity') in {'multiple', 'ambiguous', 'group'}:
            issues.append('record_object_scope_unresolved')
        for hold in holds_by_record[p['sourceRecordId']]:
            if hold.get('name') and name_key(hold['name']) != p['name']:
                issues.append('hold_record_content_changed')
            issues.append('unresolved_hold:' + hold['reason'])
        locations = set()
        for event in events[e['id']]:
            if event.get('kind') != 'excavation': continue
            locs = [entities.get(a['entityId']) for a in event['participants'] if a['role'] == 'location']
            objects = [a for a in event['participants'] if a['role'] == 'object']
            if len(locs) != 1 or not locs[0] or len(objects) != 1 or not bound_evidence(event, r) or event.get('issues'):
                issues.append('excavation_event_unreliable'); continue
            loc = normalize_name(locs[0]['label'])
            locations.add(loc)
            p['locationEvidence'].append({'eventId': event['id'], 'label': loc,
                                          'evidence': deepcopy(event['evidence'])})
        dimensions = defaultdict(set)
        known = defaultdict(set)
        for s in statements[e['id']]:
            from .projection import active_assertion
            if not active_assertion(s): continue
            if s.get('reviewStatus') == 'rejected': continue
            pred, obj = s['predicate'], s['object']
            if obj.get('kind') == 'quantity':
                if pred not in FIELD_LABELS: issues.append('unknown_measurement_field'); continue
                if s.get('issues') or s['id'] in disagreements:
                    issues.append('dimension_issue:' + s['id'])
                if not bound_evidence(s, r): issues.append('dimension_ownership_unreliable')
                try: dimension, value, unit = quantity_key(obj)
                except (KeyError, ValueError, InvalidOperation):
                    issues.append('dimension_unreliable:' + s['id']); continue
                dimensions[pred].add((dimension, value, unit))
                p['dimensionEvidence'].append({'statementId': s['id'], 'predicate': pred,
                    'object': deepcopy(obj), 'evidence': deepcopy(s.get('evidence', []))})
            elif pred == 'excavated_at':
                target = entities.get(obj.get('id'))
                if not target or target['kind'] != 'place' or s.get('issues') or not bound_evidence(s, r):
                    issues.append('excavation_statement_unreliable'); continue
                # Check explicit excavation wording as well as the typed predicate.
                if '出土' not in r['text']: issues.append('excavation_not_explicit'); continue
                loc = normalize_name(target['label'])
                locations.add(loc)
                p['locationEvidence'].append({'statementId': s['id'], 'label': loc,
                                              'evidence': deepcopy(s['evidence'])})
            elif pred in PROPERTIES:
                target = entities.get(obj.get('id'))
                label = normalize_name(target['label'] if target else str(obj.get('value') or obj.get('raw') or ''))
                if s.get('origin') in CONTEXTUAL or (s.get('binding') or {}).get('kind') in {'same_page_heading', 'page_context'}:
                    p['contextualPropertiesNotUsed'].append(s['id']); continue
                if s.get('issues') or not bound_evidence(s, r):
                    issues.append('identity_property_unreliable:' + s['id']); continue
                if label:
                    # Same-system accession numbers must conflict, not museum names.
                    system = s.get('numberSystem') or (s.get('binding') or {}).get('numberSystem')
                    if pred in {'accession_number', 'inventory_number', 'catalog_number'}:
                        if not system: issues.append('identifier_system_unknown'); continue
                        label = normalize_name(str(system)) + ':' + label
                    known[pred].add(label)
                    p['propertyEvidence'].append({'statementId': s['id'], 'predicate': pred,
                                                  'value': label, 'evidence': deepcopy(s['evidence'])})
        if len(locations) != 1: issues.append('location_missing' if not locations else 'location_ambiguous')
        # A list of sites or a bare broken fragment is not an exact excavation site.
        if any(re.search(r'[、,，;；]|(?:等地|一带|附近)|^号墓$', loc) for loc in locations):
            issues.append('location_not_exact')
        if not dimensions: issues.append('dimensions_missing')
        if any(len(v) != 1 for v in dimensions.values()): issues.append('dimension_internal_conflict')
        p['locations'] = sorted(locations)
        p['dimensionSignature'] = sorted([pred, *v] for pred, vals in dimensions.items() for v in sorted(vals))
        p['knownProperties'] = {k: sorted(v) for k, v in known.items()}
        p['issues'] = sorted(set(issues))
        p['eligible'] = not p['issues']
        result.append(p)
    return result


def ancestor(a, b, parents):
    seen = set()
    while a not in seen:
        if a == b: return True
        seen.add(a)
        if a not in parents: break
        a = parents[a]
    return False


def property_conflicts(a, b):
    conflicts = []
    for pred in sorted(set(a['knownProperties']) & set(b['knownProperties'])):
        aa, bb = set(a['knownProperties'][pred]), set(b['knownProperties'][pred])
        if aa == bb: continue
        parents = PERIOD_PARENT if pred == 'period' else MATERIAL_PARENT if pred == 'made_of' else {}
        compatible = (all(any(ancestor(x, y, parents) or ancestor(y, x, parents) for y in bb) for x in aa)
                      and all(any(ancestor(x, y, parents) or ancestor(y, x, parents) for x in aa) for y in bb))
        if not compatible: conflicts.append({'field': pred, 'left': sorted(aa), 'right': sorted(bb)})
    return conflicts


def compare(a, b, rejected=()):
    result = {'left': a['id'], 'right': b['id'], 'reasons': [], 'dimensionConflicts': [], 'propertyConflicts': []}
    why = result['reasons']
    if frozenset([a['id'], b['id']]) in rejected: why.append('human_rejected_or_revoked')
    if a['name'] != b['name']: why.append('name_mismatch')
    if len(a['locations']) != 1 or a['locations'] != b['locations']: why.append('location_mismatch_or_missing')
    da = {v[0]: v[1:] for v in a['dimensionSignature']}
    db = {v[0]: v[1:] for v in b['dimensionSignature']}
    for k in sorted(set(da) & set(db)):
        if da[k] != db[k]: result['dimensionConflicts'].append({'field': k, 'left': da[k], 'right': db[k]})
    if not da or not db: why.append('dimensions_missing')
    elif a['dimensionSignature'] != b['dimensionSignature']: why.append('dimension_signature_mismatch')
    result['propertyConflicts'] = property_conflicts(a, b)
    if result['propertyConflicts']: why.append('known_identity_property_conflict')
    if a['issues'] or b['issues']: why.append('unresolved_evidence_issues')
    result['leftIssues'], result['rightIssues'] = a['issues'], b['issues']
    result['status'] = ('strict_rule_supported' if not why else 'human_rejected' if 'human_rejected_or_revoked' in why
                        else 'recorded_dimension_conflict' if result['dimensionConflicts']
                        else 'identity_property_conflict' if result['propertyConflicts']
                        else 'insufficient_or_unreliable_evidence')
    return result


def plan(all_profiles, registry):
    """Complete-link checks in exact buckets; missing evidence can never bridge a group."""
    rejected = {frozenset(x['members']) for x in registry.get('rejectedPairs', []) if x.get('active', True)}
    buckets = defaultdict(list)
    for p in all_profiles:
        if len(p['locations']) == 1: buckets[(p['name'], p['locations'][0])].append(p)
    pair_results, groups = [], []
    used = set()
    for key, members in sorted(buckets.items()):
        if len(members) < 2: continue
        members = sorted(members, key=lambda p: p['id'])
        checks = {frozenset([a['id'], b['id']]): compare(a, b, rejected) for a, b in combinations(members, 2)}
        pair_results.extend(checks.values())
        partitions = []
        for p in members:
            for group in partitions:
                if all(checks[frozenset([p['id'], other['id']])]['status'] == 'strict_rule_supported' for other in group):
                    group.append(p); break
            else: partitions.append([p])
        for group in partitions:
            if len(group) < 2: continue
            # The identity key never contains a run, page offset, floating tolerance, or vector.
            signature = [VERSION, group[0]['name'], group[0]['locations'], group[0]['dimensionSignature']]
            canonical = ident('canonical-artifact', signature)
            if canonical in used: canonical = ident('canonical-artifact', signature, group[0]['id'])
            used.add(canonical)
            previous = {registry.get('canonicalBySource', {}).get(p['id']) for p in group} - {None}
            if len(previous) == 1 and next(iter(previous)) not in {single_id(p) for p in group}:
                old = next(iter(previous))
                if old not in {g['id'] for g in groups}: canonical = old
            groups.append({'id': canonical, 'label': group[0]['name'], 'name': group[0]['name'],
                'location': group[0]['locations'][0], 'dimensionSignature': group[0]['dimensionSignature'],
                'members': deepcopy(group), 'decision': 'automatic_rule_supported', 'ruleVersion': VERSION,
                'reviewStatus': 'unreviewed', 'independentHistoricalIdentityVerified': False,
                'pairChecks': [checks[frozenset([a['id'], b['id']])] for a, b in combinations(group, 2)]})
    assigned = {p['id']: g['id'] for g in groups for p in g['members']}
    canonical = list(groups)
    for p in sorted(all_profiles, key=lambda p: p['id']):
        if p['id'] not in assigned:
            cid = single_id(p); assigned[p['id']] = cid
            member = {k: deepcopy(p[k]) for k in ('id', 'sourceEntityId', 'sourceRecordId', 'volume',
                'entityId', 'recordId', 'rawName', 'page', 'item', 'issues')}
            canonical.append({'id': cid, 'label': p['rawName'], 'members': [member],
                              'decision': 'source_record_only', 'ruleVersion': VERSION,
                              'reviewStatus': 'unreviewed', 'independentHistoricalIdentityVerified': False})
    summary = {'sourceArtifacts': len(all_profiles), 'canonicalArtifacts': len(canonical),
        'mergedGroups': len(groups), 'mergedSourceRecords': sum(len(g['members']) for g in groups),
        'duplicateReduction': sum(len(g['members'])-1 for g in groups),
        'candidateBuckets': sum(len(b) > 1 for b in buckets.values()), 'candidatePairs': len(pair_results),
        'pairStatusCounts': dict(Counter(p['status'] for p in pair_results)),
        'sourceIssueCounts': dict(Counter(x for p in all_profiles for x in p['issues'])),
        'crossVolumeGroups': sum(len({p['volume'] for p in g['members']}) > 1 for g in groups)}
    historical_members = defaultdict(set)
    for operation in registry.get('history', []):
        for field in ('beforeMapping', 'afterMapping'):
            for member, cid in operation.get(field, {}).items(): historical_members[cid].add(member)
    for member, cid in registry.get('canonicalBySource', {}).items(): historical_members[cid].add(member)
    redirects = {cid: sorted({assigned[m] for m in members if m in assigned})
                 for cid,members in historical_members.items() if cid not in {e['id'] for e in canonical}}
    return {'version': VERSION, 'entities': sorted(canonical, key=lambda x: x['id']),
            'groups': sorted(groups, key=lambda x: x['id']), 'sourceToCanonical': assigned,
            'recordToCanonical': {p['sourceRecordId']: assigned[p['id']] for p in all_profiles},
            'summary': summary, 'pairDecisions': pair_results, **({'redirects': redirects} if redirects else {})}


def project_identity(identity, volume):
    relevant = [deepcopy(e) for e in identity['entities'] if any(m['volume'] == volume for m in e['members'])]
    local = [m for e in relevant for m in e['members'] if m['volume'] == volume]
    mapping = {m['entityId']: e['id'] for e in relevant for m in e['members'] if m['volume'] == volume}
    return {'version': VERSION, 'volume': volume, 'entities': relevant,
            'sourceToCanonical': mapping,
            'recordToCanonical': {m['recordId']: mapping[m['entityId']] for m in local},
            'summary': {'sourceArtifacts': len(local), 'canonicalArtifacts': len(relevant),
                'mergedGroups': sum(len(e['members']) > 1 for e in relevant),
                'automaticIdentityMerges': len(local)-len(relevant)},
            'decisionMeaning': 'Project rule supported candidate identity; not human or independent historical verification',
            **({'redirects': identity['redirects']} if identity.get('redirects') else {})}
