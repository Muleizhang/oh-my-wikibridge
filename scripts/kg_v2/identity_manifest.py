"""Project a reversible artifact identity layer into an atlas manifest.

Source catalog entries and statements are never replaced by their representatives:
``sourceItems`` / ``sourceRows`` retain them, while ``items`` / ``rows`` are the
canonical query and display projection.  Rebuilding always starts from the source
collections, so a new decision (including an undo) cannot compound an old merge.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import json

from .identity import normalize_name
from .projection import active_assertion


def is_artifact_row(row):
    """Interpretations/concepts are subjects of their own statements."""
    if row.get('subjectKind') and row['subjectKind'] != 'artifact':
        return False
    return not row.get('subjectKey') or row['subjectKey'].startswith('artifact:')


def _unique(values):
    result, seen = [], set()
    for value in values:
        key = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def combine_identities(identities):
    """Combine per-source projections, retaining global canonical IDs unchanged."""
    identities = [value for value in identities if value]
    if not identities:
        return None
    entities, by_id, source_map, record_map = [], {}, {}, {}
    for identity in identities:
        volume = identity.get('volume')
        for field, target in [('sourceToCanonical', source_map), ('recordToCanonical', record_map)]:
            for source, canonical in identity.get(field, {}).items():
                key = source if ':' in source or not volume else f'{volume}:{source}'
                if key in target and target[key] != canonical:
                    raise ValueError(f'Conflicting canonical artifact mapping: {key}')
                target[key] = canonical
        for entity in identity.get('entities', []):
            if entity['id'] not in by_id:
                current = deepcopy(entity)
                by_id[entity['id']] = current
                entities.append(current)
            else:
                current = by_id[entity['id']]
                current['members'] = _unique(current.get('members', []) + entity.get('members', []))
    redirects = {}
    for identity in identities:
        for old, targets in identity.get('redirects', {}).items():
            redirects[old] = sorted(set(redirects.get(old, []) + targets))
    return {
        'version': identities[0].get('version'),
        'volumes': _unique([i.get('volume') for i in identities if i.get('volume')]),
        'sourceToCanonical': source_map,
        'recordToCanonical': record_map,
        'entities': entities,
        'sourceIdentities': identities,
        **({'redirects': redirects} if redirects else {}),
    }


def _record_index(identity, volume):
    index, members = {}, {}

    def put(key, canonical, member=None):
        if not key:
            return
        if key in index and index[key] != canonical:
            raise ValueError(f'Ambiguous source record identity: {key}')
        index[key] = canonical
        if member:
            members[key] = member

    identity_volume = identity.get('volume') or volume
    for source, canonical in identity.get('recordToCanonical', {}).items():
        # A combined identity map intentionally has namespaced keys only.
        put(source, canonical)
        if ':' not in source and identity_volume:
            put(f'{identity_volume}:{source}', canonical)
    for entity in identity.get('entities', []):
        for member in entity.get('members', []):
            member_volume = member.get('volume') or identity_volume
            local = member.get('recordId')
            scoped = member.get('sourceRecordId') or (f'{member_volume}:{local}' if member_volume and local else local)
            put(scoped, entity['id'], member)
            if member_volume == identity_volume and identity_volume:
                put(local, entity['id'], member)
    return index, members


def apply_manifest_identity(manifest, identity, volume=None):
    """Apply identity decisions without dropping any source entry or statement.

    ``identity`` is the graph's artifactIdentity layer or combine_identities(...).
    The function mutates and returns ``manifest``.  No identity layer means the
    legacy representation is left intact.  Source metadata and image URLs are
    copied verbatim; callers perform any volume namespacing before this step.
    """
    if not identity:
        return manifest
    volume = volume or identity.get('volume')
    record_map, member_map = _record_index(identity, volume)
    entity_map = {entity['id']: entity for entity in identity.get('entities', [])}
    source_items = deepcopy(manifest.get('sourceItems', manifest.get('items', [])))
    source_rows = deepcopy(manifest.get('sourceRows', manifest.get('rows', [])))

    def match(item):
        candidates = [item.get('sourceRecordId'), item.get('recordId'), item.get('artifactId')]
        for candidate in candidates:
            if not candidate:
                continue
            if candidate in record_map:
                return record_map[candidate], member_map.get(candidate, {})
            if volume and ':' not in candidate:
                scoped = f'{volume}:{candidate}'
                if scoped in record_map:
                    return record_map[scoped], member_map.get(scoped, {})
        return None, {}

    artifact_map = {}
    by_canonical = defaultdict(list)
    for item in source_items:
        canonical, member = match(item)
        # Records without an artifact entity keep their separate source identity.
        canonical = canonical or item['artifactId']
        item['canonicalArtifactId'] = canonical
        item.setdefault('sourceRecordId', item.get('recordId') or item['artifactId'])
        if member.get('sourceEntityId'):
            item.setdefault('sourceEntityId', member['sourceEntityId'])
        artifact_map[item['artifactId']] = canonical
        artifact_map[item['sourceRecordId']] = canonical
        by_canonical[canonical].append(item)

    canonical_items = []
    for canonical, sources in by_canonical.items():
        entity = entity_map.get(canonical, {})
        item = deepcopy(sources[0])
        item.update({
            'artifactId': canonical,
            'artifact': entity.get('label') or item.get('artifact'),
            'sourceRecords': sources,
            'sourceRecordIds': [source['sourceRecordId'] for source in sources],
            'sourceRecordCount': len(sources),
            'identityDecision': entity.get('decision', 'source_record_only'),
            'identityRuleVersion': identity.get('version'),
        })
        canonical_items.append(item)

    row_groups = defaultdict(list)
    non_artifact_rows = []
    for row in source_rows:
        if not active_assertion(row):
            continue
        if not is_artifact_row(row):
            non_artifact_rows.append(deepcopy(row))
            continue
        canonical, _ = match(row)
        canonical = canonical or artifact_map.get(row.get('artifactId'))
        if canonical is None or canonical not in by_canonical:
            raise ValueError(f"Source statement has no catalog entry: {row.get('id')}")
        row['canonicalArtifactId'] = canonical
        row.setdefault('sourceRecordId', row.get('recordId') or row['artifactId'])
        # Different qualifiers may represent different semantic claims.
        key = (canonical, row['predicate'], normalize_name(str(row.get('object', ''))),
               json.dumps(row.get('qualifiers') or [], ensure_ascii=False, sort_keys=True))
        row_groups[key].append(row)

    evidence_by_id = {value['id']: value for value in manifest.get('evidence', [])}
    canonical_rows = []
    for key, sources in row_groups.items():
        canonical, predicate, label, _ = key
        row = deepcopy(sources[0])
        digest = hashlib.sha256(json.dumps(key, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:24]
        evidence_ids = _unique([value for source in sources
                                for value in ([source.get('evidenceId')] + source.get('evidenceIds', [])) if value])
        support = []
        for source in sources:
            for evidence in source.get('supportingEvidence', []):
                support.append({**evidence, 'sourceStatementId': source['id'],
                                'sourceRecordId': source['sourceRecordId']})
            if source.get('evidenceId') in evidence_by_id:
                support.append({**evidence_by_id[source['evidenceId']],
                                'sourceStatementId': source['id'], 'sourceRecordId': source['sourceRecordId']})
        row.update({
            'id': f'canonical-relation-{digest}',
            'artifactId': canonical,
            'subjectId': canonical,
            'subjectKind': 'artifact',
            'subjectKey': f'artifact:{canonical}',
            'artifact': entity_map.get(canonical, {}).get('label') or row.get('artifact'),
            'object': label,
            'sources': sources,
            'sourceStatementIds': [source['id'] for source in sources],
            'sourceRecordIds': _unique([source['sourceRecordId'] for source in sources]),
            'evidenceIds': evidence_ids,
            'supportingEvidence': _unique(support),
            'issues': _unique([issue for source in sources for issue in source.get('issues', [])]),
        })
        canonical_rows.append(row)
    canonical_rows.extend(non_artifact_rows)

    manifest.update({'artifactIdentity': deepcopy(identity), 'sourceItems': source_items,
                     'sourceRows': source_rows, 'items': canonical_items, 'rows': canonical_rows})
    summary = manifest.setdefault('summary', {})
    summary.update({
        'graphItems': len(canonical_items), 'graphEdges': len(canonical_rows),
        'displaySourceRecords': len(source_items), 'sourceGraphEdges': len(source_rows),
        'supersededSourceEdges': sum(not active_assertion(row) for row in source_rows),
        'displayDuplicateReduction': len(source_items) - len(canonical_items),
        'displayMergedArtifactGroups': sum(len(values) > 1 for values in by_canonical.values()),
        'artifactIdentityRuleVersion': identity.get('version'),
    })
    return manifest
