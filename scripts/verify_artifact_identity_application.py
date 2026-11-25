#!/usr/bin/env python3
"""Verify the applied identities and exercise revocation on real-data copies."""
from argparse import Namespace
from copy import deepcopy
from itertools import combinations
import json
import sqlite3

from apply_artifact_identity import (DATA, DATABASE, REGISTRY, REPORT, VOLUMES,
    apply_revocations, validate_manifest)
from kg_v2.artifact_identity import plan, profiles, project_identity
from kg_v2.common import load, save
from kg_v2.identity_manifest import apply_manifest_identity, combine_identities


def main():
    report, registry = load(REPORT), load(REGISTRY)
    graphs = {v:load(root/'graph.json') for v,root,_ in VOLUMES}
    pp = [p for v,g in graphs.items() for p in profiles(g,v,registry['holds'])]
    current = plan(pp,registry)
    first = graphs['v1']['artifactIdentity']['recordToCanonical']
    a,b,c,d = [first[r] for r in ['record-9315e865fd143f64e069','record-e0d8edba4442862ff77d',
                                  'record-ab5ba9084304f8f98f38','record-b12aadaf56a42d33cb29']]
    assert a == b and len({a,c,d}) == 3
    assert current['summary']['mergedGroups'] == 12
    assert current['sourceToCanonical'] == registry['canonicalBySource']
    for v,g in graphs.items():
        assert project_identity(current,v)['sourceToCanonical'] == g['artifactIdentity']['sourceToCanonical']
    # Revoke the actual A/B group in a copy; do not disturb the user's applied graph.
    undone_registry = deepcopy(registry)
    apply_revocations(undone_registry,Namespace(revoke=[a],revoke_all=False,note='verification copy'))
    undone = plan(pp,undone_registry)
    assert undone['summary']['mergedGroups'] == 11 and undone['summary']['canonicalArtifacts'] == 4087
    assert len(undone['redirects'][a]) == 2
    assert plan(pp,undone_registry) == undone
    assert all(undone['sourceToCanonical'][source] == cid for source,cid in current['sourceToCanonical'].items()
               if source not in {m['sourceEntityId'] for g in current['groups'] if g['id'] == a for m in g['members']})
    site = DATA/'merged/site'; manifest = load(site/'manifest.json')
    source_images = [{k:v for k,v in s.items() if k != 'canonicalArtifactId'} for s in manifest['sourceItems']]
    source_statements = [{k:v for k,v in s.items() if k != 'canonicalArtifactId'} for s in manifest['sourceRows']]
    layer = combine_identities([project_identity(undone,v) for v in graphs])
    apply_manifest_identity(manifest,layer)
    undone_validation = validate_manifest(manifest,site)
    assert len(manifest['items']) == 4064
    assert source_images == [{k:v for k,v in s.items() if k != 'canonicalArtifactId'} for s in manifest['sourceItems']]
    assert source_statements == [{k:v for k,v in s.items() if k != 'canonicalArtifactId'} for s in manifest['sourceRows']]
    restored = combine_identities([g['artifactIdentity'] for g in graphs.values()])
    apply_manifest_identity(manifest,restored)
    assert len(manifest['items']) == 4063
    assert {i['artifactId'] for i in manifest['items']} == {i['artifactId'] for i in load(site/'manifest.json')['items']}
    with sqlite3.connect(f'file:{DATABASE}?mode=ro',uri=True) as conn:
        runs = [graphs[v]['runId'] for v in sorted(graphs)]
        placeholders = ','.join('?' for _ in runs)
        canonical = conn.execute(f'SELECT COUNT(DISTINCT id) FROM kg_canonical_artifacts WHERE run_id IN ({placeholders})',runs).fetchone()[0]
        mappings = conn.execute(f'SELECT COUNT(*) FROM kg_artifact_identity_map WHERE run_id IN ({placeholders})',runs).fetchone()[0]
        assert (canonical,mappings) == (4086,4098)
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()
        sql_example = conn.execute('SELECT predicate,source_count FROM kg_canonical_assertions '
                                  'WHERE run_id=? AND canonical_id=?',(runs[0],a)).fetchall()
        assert dict(sql_example)['height'] == 2 and dict(sql_example)['made_of'] == 2
        for v,g in graphs.items():
            stored = json.loads(conn.execute('SELECT graph_json FROM kg_runs WHERE id=?',(g['runId'],)).fetchone()[0])
            assert stored == g
    result = {'passed':True,'realABCanonicalId':a,'CAndDRemainSeparate':True,
        'sourceArtifacts':4098,'canonicalArtifacts':4086,'sourceMappings':4098,
        'productionRerunIdempotent':True,'allSourcePayloadsAndImagesPreserved':True,
        'sqliteGraphPayloadsEqualJSON':True,'foreignKeyViolations':0,
        'revocation':{'scope':'real-data copy; production merges retained','mergedGroupsAfterUndo':11,
            'displayArtifactsAfterUndo':4064,'sourceImagesAndStatementsUnchanged':True,
            'unaffectedCanonicalIDsStable':True,'persistentRejectionPreventsRemerge':True,
            'oldGroupIDResolvesToSplitReplacements':undone['redirects'][a],
            'manifestChecks':undone_validation},
        'sourceTotals': {field:sum(len(g[field]) for g in graphs.values())
                         for field in ['records','entities','assertions','events','mentions','interpretations']}}
    save(DATA/'report/artifact-identity-validation.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__': main()
