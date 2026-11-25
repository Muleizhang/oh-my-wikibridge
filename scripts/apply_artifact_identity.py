#!/usr/bin/env python3
"""Apply/revoke strict artifact identities from cached graphs, retaining sources."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from itertools import combinations
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

from kg_v2.artifact_identity import VERSION, compare, plan, profiles, project_identity
from kg_v2.common import ROOT, ident, load, save
from kg_v2.identity_manifest import apply_manifest_identity, combine_identities
from kg_v2_validate import validate
from kg_v2.projection import active_assertion

DATA = ROOT / 'data/local-kg'
VOLUMES = [('v1', DATA, DATA/'atlas-vol1'), ('v2', DATA/'vol2', DATA/'vol2/star-atlas'),
           ('v3', DATA/'vol3', DATA/'vol3/star-atlas')]
DATABASE = Path.home()/'.local/share/cn.wikibridge.desktop/knowledge.sqlite3'
REGISTRY = DATA/'artifact-identity/registry.json'
REPORT = DATA/'report/artifact-identity-applied.json'


def digest(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def payload_fingerprint(graph):
    # Exclude derived identity/review/run counters, keeping all source facts and images.
    source = {k:v for k,v in graph.items() if k not in {'artifactIdentity', 'identityReview', 'runId', 'summary'}}
    return hashlib.sha256(json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def registry_with_holds(path=REGISTRY):
    registry = load(path) if path.exists() else {'version': VERSION, 'holds': [], 'rejectedPairs': [], 'history': []}
    audit_path = DATA/'report/artifact-identity-reliability-audit.json'
    audit = load(audit_path)
    # Persist known unresolved problems separately; do not silently clear an OCR flag.
    for group_id, reason in [('G005', 'ocr_numeric_review_pending'), ('G036', 'image_caption_correspondence_pending'),
                             ('G071', 'catalog_record_segmentation_pending')]:
        group = next(g for g in audit['groups'] if g['groupId'] == group_id)
        for member in group['members']:
            sid = f"{member['volume']}:{member['recordId']}"
            if any(h['sourceRecordId'] == sid and h['reason'] == reason for h in registry['holds']): continue
            registry['holds'].append({'sourceRecordId': sid, 'name': group['name'], 'reason': reason,
                'active': True, 'basis': {'report': str(audit_path.relative_to(ROOT)),
                    'sha256': digest(audit_path), 'group': group_id, 'note': group['audit']['note']},
                'status': 'unresolved', 'humanIdentityVerified': False})
    return registry


def rejected_reviews(graphs, database):
    """Read historical rejections as well as the latest run; never move/delete reviews."""
    rejected = []
    reject_values = {'reject', 'rejected', 'different', 'not_same', 'different_entity', 'not_same_as'}
    for volume, graph in graphs.items():
        proposals = {p['id']: p for p in graph.get('identityProposals', [])}
        for decision in graph.get('identityDecisions', []):
            if decision.get('decision') in reject_values:
                pair = decision if decision.get('left') and decision.get('right') else proposals.get(decision.get('proposalId'))
                if pair: rejected.append({'members': [f"{volume}:{pair['left']}", f"{volume}:{pair['right']}"],
                    'active': True, 'reason': 'existing_explicit_rejection', 'source': decision})
    if not database.exists(): return rejected, 0
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as conn:
        rows = conn.execute('SELECT r.id,r.target_kind,r.target_id,r.decision,r.note,k.source_id,k.graph_json '
                            'FROM kg_reviews r JOIN kg_runs k ON k.id=r.run_id').fetchall()
        for rid, kind, target, decision, note, source, text in rows:
            if decision not in reject_values: continue
            old = json.loads(text)
            old_source = next((d.get('source') for d in old.get('documents', []) if d.get('source')), None)
            volume = next((v for v,g in graphs.items() if any(d.get('source') == old_source for d in g['documents'])), None)
            if not volume: continue
            proposal = next((p for p in old.get('identityProposals', []) if p['id'] == target), None)
            members = []
            if proposal: members = [f"{volume}:{proposal['left']}", f"{volume}:{proposal['right']}"]
            else:
                canonical = next((e for e in old.get('artifactIdentity', {}).get('entities', []) if e['id'] == target), None)
                if canonical: members = [m['sourceEntityId'] for m in canonical['members']]
            if not members:
                # An unresolvable identity rejection must block, not quietly disappear.
                if kind in {'identity', 'identity_pair', 'artifact_identity', 'canonical_artifact'}:
                    raise ValueError(f'Cannot resolve historical identity rejection {rid}; retain for review')
                continue
            for pair in combinations(members, 2):
                rejected.append({'members': sorted(pair), 'active': True, 'reason': 'human_rejected',
                                 'reviewId': rid, 'sourceId': source, 'note': note})
    return rejected, len(rows)


def audit_versions(graphs):
    result = {}
    for filename in ['artifact-identity-candidate-audit.json', 'artifact-identity-reliability-audit.json']:
        report = load(DATA/'report'/filename)
        result[filename] = [{'volume': x['volume'], 'reportedRunId': x['runId'],
            'reportedSha256': x['sha256'], 'currentRunId': graphs[x['volume']]['runId'],
            'currentSha256': digest(ROOT/x['path']), 'unchanged': digest(ROOT/x['path']) == x['sha256']}
            for x in report['inputs']]
    return result


def apply_revocations(registry, args):
    current = {g['id']: g for g in registry.get('groups', [])}
    targets = list(current) if args.revoke_all else args.revoke
    changed = []
    for target in targets:
        if target not in current:
            if any(x.get('groupId') == target and x.get('active', True) for x in registry['rejectedPairs']):
                continue  # Repeating a completed revocation is a no-op.
            raise ValueError('Unknown active merge group: ' + target)
        changed.append(target)
        for pair in combinations([m['sourceEntityId'] for m in current[target]['members']], 2):
            if any(set(x['members']) == set(pair) and x.get('active', True) for x in registry['rejectedPairs']): continue
            registry['rejectedPairs'].append({'members': sorted(pair), 'active': True,
                'reason': 'explicit_revocation', 'groupId': target, 'note': args.note or 'User-directed revocation'})
    return changed


def assert_sources_unchanged(graph, original):
    for field in set(original) - {'artifactIdentity', 'identityReview', 'summary', 'runId'}:
        if graph.get(field) != original[field]: raise ValueError('Source data changed: ' + field)


def validate_manifest(manifest, site):
    items, rows = manifest['items'], manifest['rows']
    source_items, source_rows = manifest['sourceItems'], manifest['sourceRows']
    ids = {i['artifactId'] for i in items}
    if len(ids) != len(items): raise ValueError('Duplicate canonical item')
    sources = {i['sourceRecordId']: i for i in source_items}
    if len(sources) != len(source_items): raise ValueError('Source catalog namespace collision')
    ev = {e['id'] for e in manifest['evidence']}
    for row in rows:
        if row.get('subjectKind') not in (None, '', 'artifact'): continue
        if row['artifactId'] not in ids or not set(row.get('evidenceIds', [row['evidenceId']])) <= ev:
            raise ValueError('Dangling canonical edge/evidence')
    if {r['id'] for r in source_rows if active_assertion(r)} != {s['id'] for r in rows for s in r.get('sources', [r])}:
        raise ValueError('Source statements lost during relation aggregation')
    for source in source_items:
        for key in ['imageUrl', 'detailUrl', 'pageUrl', 'captionUrl']:
            url = source.get(key)
            if url and not url.startswith(('http:', 'https:', 'data:', '/api/')) and not (site/url).is_file():
                raise ValueError('Missing source image: ' + url)
        for image in source.get('imageCandidates', []):
            if not (site/image['imageUrl']).is_file(): raise ValueError('Missing subimage')
    return {'canonicalArtifacts': len(items), 'sourceCatalogItems': len(source_items),
            'canonicalRelations': len(rows), 'sourceRelations': len(source_rows),
            'evidence': len(ev), 'danglingReferences': 0}


def write_site(site, manifest):
    # Reuse current assets verbatim, including the newer automatic crops.
    serialized = json.dumps(manifest, ensure_ascii=False, separators=(',', ':'))
    path = site/'manifest.json'; temp = path.with_suffix('.json.identity.tmp')
    temp.write_text(serialized); temp.replace(path)
    template = (ROOT/'scripts/atlas_viewer.html').read_text()
    reasoner = (ROOT/'src/kg-reasoner.js').read_text().replace('export ', '')
    html = template.replace('__MANIFEST_JSON__', serialized.replace('<', '\\u003c'), 1).replace('__REASONER_JS__', reasoner, 1)
    for name in ['atlas_viewer.html', 'index.html']:
        if name == 'index.html' and not (site/name).exists(): continue
        temp = site/(name+'.identity.tmp'); temp.write_text(html); temp.replace(site/name)


def backup_all(paths, database):
    target = DATA/'archive'/('before-artifact-identity-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    target.mkdir(parents=True)
    files = []
    for path in paths:
        if not path.exists(): continue
        relative = path.relative_to(ROOT)
        dest = target/relative; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest); files.append({'path': str(relative), 'sha256': digest(path)})
    if database.exists():
        with sqlite3.connect(database, timeout=30) as src, sqlite3.connect(target/'knowledge.sqlite3') as dst:
            src.backup(dst)
    save(target/'backup.json', {'createdAt': datetime.now(timezone.utc).isoformat(), 'files': files,
         'database': str(database), 'sqliteBackupAPI': True,
         'undo': 'Prefer --revoke GROUP_ID --apply to preserve later unrelated source/enrichment changes'})
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--revoke', action='append', default=[], metavar='GROUP_ID')
    parser.add_argument('--revoke-all', action='store_true')
    parser.add_argument('--note', default='')
    parser.add_argument('--database', type=Path, default=DATABASE)
    args = parser.parse_args()
    if args.database.name != 'knowledge.sqlite3':
        parser.error('--database must point to a knowledge.sqlite3 file (the importer uses this filename)')
    graphs, originals, file_hashes = {}, {}, {}
    for volume, directory, _ in VOLUMES:
        path = directory/'graph.json'; graph = load(path)
        graphs[volume], originals[volume], file_hashes[path] = graph, deepcopy(graph), digest(path)
    registry = registry_with_holds()
    revoked = apply_revocations(registry, args)
    rejections, reviews = rejected_reviews(graphs, args.database)
    for row in rejections:
        if not any(set(row['members']) == set(old['members']) for old in registry['rejectedPairs']):
            registry['rejectedPairs'].append(row)
    all_profiles = [p for v,g in graphs.items() for p in profiles(g, v, registry['holds'])]
    identity = plan(all_profiles, registry)
    layers = {}
    for v,g in graphs.items():
        layers[v] = project_identity(identity, v)
        layers[v]['sourcePayloadSha256'] = payload_fingerprint(g)
        g['artifactIdentity'] = layers[v]
        g['summary']['automaticIdentityMerges'] = layers[v]['summary']['automaticIdentityMerges']
        validate(g)
    by_id = {p['id']: p for p in all_profiles}
    historical = []
    for group in load(DATA/'report/artifact-identity-reliability-audit.json')['groups']:
        members = [by_id.get(f"{m['volume']}:{m['entityId']}") for m in group['members']]
        pairs = [compare(a,b,{frozenset(x['members']) for x in registry['rejectedPairs'] if x.get('active', True)})
                 for a,b in combinations([m for m in members if m],2)]
        historical.append({'groupId': group['groupId'], 'name': group['name'], 'location': group['location'],
                           'pairs': pairs, 'missingSourceMembers': sum(m is None for m in members)})
    report = {'version': VERSION, 'applied': False, 'inputVersionChecks': audit_versions(originals),
        'inputs': [{'volume': v, 'path': str((d/'graph.json').relative_to(ROOT)), 'runId': originals[v]['runId'],
                    'sha256': file_hashes[d/'graph.json'], 'sourcePayloadSha256': payload_fingerprint(originals[v])}
                   for v,d,_ in VOLUMES],
        'summary': identity['summary'], 'groups': identity['groups'], 'pairDecisions': identity['pairDecisions'],
        'historical106BucketsRechecked': historical, 'profiles': all_profiles,
        'reviewsCheckedAcrossHistoricalRuns': reviews, 'revokedGroups': revoked,
        'humanIdentityVerified': False, 'independentHistoricalIdentityVerified': False,
        'method': 'Exact name/site/full Decimal measurements + conflict and unresolved-issue checks; complete-link groups',
        'perVolume': {v: layers[v]['summary'] for v in graphs}}
    sites = [(site, layers[v], v) for v,_,site in VOLUMES] + [(DATA/'merged/site', combine_identities(layers.values()), None)]
    manifests = []
    for site, layer, volume in sites:
        path = site/'manifest.json'
        if not path.is_file(): continue
        file_hashes[path] = digest(path); original = load(path)
        manifest = deepcopy(original)
        apply_manifest_identity(manifest, layer, volume)
        report.setdefault('display', {})[str(site.relative_to(ROOT))] = validate_manifest(manifest, site)
        # Every original source image, caption, status, statement and evidence survives exactly.
        old_items = original.get('sourceItems', original['items'])
        old_rows = original.get('sourceRows', original['rows'])
        for before, after in zip(old_items, manifest['sourceItems']):
            for key, value in before.items():
                if key != 'canonicalArtifactId' and after.get(key) != value: raise ValueError('Source item mutated: '+key)
        for before, after in zip(old_rows, manifest['sourceRows']):
            for key, value in before.items():
                if key != 'canonicalArtifactId' and after.get(key) != value: raise ValueError('Source statement mutated: '+key)
        if original['evidence'] != manifest['evidence']: raise ValueError('Evidence changed')
        manifests.append((site, manifest, original))
    if not args.apply:
        save(DATA/'report/artifact-identity-dry-run.json', report)
        print(json.dumps({'applied': False, 'summary': report['summary'], 'display': report['display']}, ensure_ascii=False))
        return
    if all(originals[v].get('artifactIdentity') == layers[v] for v in graphs) and all(m == old for _,m,old in manifests) and not revoked:
        print(json.dumps({'applied': True, 'changed': False, 'idempotent': True, 'summary': identity['summary']}, ensure_ascii=False)); return
    backup_paths = list(file_hashes) + [REGISTRY, REPORT]
    for _,directory,site in VOLUMES:
        backup_paths += [directory/'summary.json', directory/'database-import.json', site/'index.html', site/'atlas_viewer.html']
    backup_paths += [DATA/'merged/site/index.html', DATA/'merged/site/atlas_viewer.html']
    backup = backup_all(backup_paths, args.database)
    print('Backup: '+str(backup), flush=True)
    for path, original_hash in file_hashes.items():
        if digest(path) != original_hash: raise ValueError('Concurrent source update; rerun from latest cache: '+str(path))
    database_reports = {}
    staging = backup/'staging'; staging.mkdir()
    for volume,directory,_ in VOLUMES:
        stage = staging/(volume+'.json'); save(stage, graphs[volume])
        env = {**os.environ, 'WIKIBRIDGE_KG_DATA': str(directory), 'PYTHONPATH': str(ROOT/'scripts')}
        code = ('import sys;from pathlib import Path;from kg_v2.common import load,save;'
                'from kg_v2_store import persist;g=load(sys.argv[1]);'
                'r=persist(g,Path(sys.argv[2]));save(sys.argv[1],g);save(sys.argv[3],r)')
        output = staging/(volume+'-database.json')
        subprocess.run([sys.executable, '-c', code, str(stage), str(args.database.parent), str(output)],
                       cwd=ROOT, env=env, check=True)
        graphs[volume] = load(stage); database_reports[volume] = load(output)
        assert_sources_unchanged(graphs[volume], originals[volume])
    for path, original_hash in file_hashes.items():
        if digest(path) != original_hash: raise ValueError('Concurrent update during staging; no source files overwritten: '+str(path))
    for volume,directory,_ in VOLUMES:
        save(directory/'graph.json', graphs[volume]); save(directory/'summary.json', graphs[volume]['summary'])
        save(directory/'database-import.json', database_reports[volume])
    for site,manifest,_ in manifests:
        if manifest.get('volumes'):
            for vol in manifest['volumes']:
                if vol.get('prefix') in graphs: vol['runId'] = graphs[vol['prefix']]['runId']
        else:
            volume = next(v for v,_,p in VOLUMES if p == site); manifest['runId'] = graphs[volume]['runId']
        manifest['identityRunId'] = ident('identity-projection', [graphs[v]['runId'] for v in sorted(graphs)], identity['recordToCanonical'])
        write_site(site, manifest)
    operation = {'id': ident('artifact-identity-operation', VERSION, registry.get('canonicalBySource', {}),
                            identity['sourceToCanonical'], revoked, [payload_fingerprint(g) for g in graphs.values()]),
        'action': 'revoke' if revoked else 'apply', 'createdAt': datetime.now(timezone.utc).isoformat(),
        'ruleVersion': VERSION, 'backup': str(backup), 'revokedGroups': revoked,
        'beforeMapping': registry.get('canonicalBySource', {}), 'afterMapping': identity['sourceToCanonical'],
        'sourceRuns': {v:g['runId'] for v,g in graphs.items()}}
    registry.update({'canonicalBySource': identity['sourceToCanonical'], 'groups': identity['groups']})
    if not any(x['id'] == operation['id'] for x in registry['history']): registry['history'].append(operation)
    with sqlite3.connect(args.database) as conn:
        conn.execute('INSERT OR IGNORE INTO kg_artifact_identity_operations(id,action,rule_version,data) VALUES (?,?,?,?)',
                     (operation['id'], operation['action'], VERSION, json.dumps(operation, ensure_ascii=False)))
        if conn.execute('PRAGMA foreign_key_check').fetchall(): raise ValueError('SQLite foreign key violation')
    save(REGISTRY, registry)
    report.update({'applied': True, 'backup': str(backup), 'operationId': operation['id'], 'database': database_reports,
                   'outputRuns': {v:g['runId'] for v,g in graphs.items()}, 'sourcesPreserved': True, 'danglingReferences': 0})
    save(REPORT, report)
    print(json.dumps({'applied': True, 'backup': str(backup), 'report': str(REPORT),
                      'summary': report['summary'], 'display': report['display']}, ensure_ascii=False))


if __name__ == '__main__': main()
