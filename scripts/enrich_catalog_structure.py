#!/usr/bin/env python3
"""Apply explicit catalog slots and bounded heading context from local caches."""
import argparse
from collections import Counter,defaultdict
from copy import deepcopy
import json
import os
import subprocess
import sys

from apply_artifact_identity import (DATA,DATABASE,VOLUMES,backup_all,digest,payload_fingerprint,
                                     validate_manifest,write_site)
from kg_v2.catalog_enrichment import VERSION,enrich_catalog,FIELDS
from kg_v2.common import ROOT,ident,load,save
from kg_v2.identity_manifest import apply_manifest_identity,combine_identities
from kg_v2.projection import active_assertion
from kg_v2_validate import validate


def update_manifest(manifest,graphs,volume=None):
    source_items=manifest.get('sourceItems',manifest['items'])
    source_rows=manifest.get('sourceRows',manifest['rows'])
    items={i.get('sourceRecordId',i['artifactId']):i for i in source_items}
    rows={r['id']:r for r in source_rows}
    evidences={e['id']:e for e in manifest['evidence']}
    pages={(p.get('volume',''),p.get('volumePage',p['page'])):p for p in manifest['pages']}
    added,corrected,context_updated=0,0,0
    for prefix,g in graphs.items():
        label=next((v['label'] for v in manifest.get('volumes',[]) if v['prefix']==prefix),'')
        entities={e['id']:e for e in g['entities']};records={r['id']:r for r in g['records']}
        docs={(d['page'],d['engine']):d for d in g['documents']}
        def namespaced(sid):return sid if volume else prefix+':'+sid
        def support(ev,rid,sid):
            page=pages[(label,ev['page'])];doc=docs[(ev['page'],ev['engine'])];box=ev.get('bbox')
            return {**ev,'page':page['page'],'volumePage':ev['page'],'volume':label,
                'sourceName':doc.get('source',''),'sourceRecordId':rid,'sourceStatementId':sid,
                'previewUrl':page['previewUrl'],
                'normalizedBbox':[x/y for x,y in zip(box,doc['imageSize']*2)] if box else None}
        for s in g['assertions']:
            sid=namespaced(s['id'])
            if s.get('projectionStatus')=='superseded' and sid in rows:
                row=rows[sid];replacement=[namespaced(x) for x in s['supersededBy']]
                if row.get('projectionStatus')!='superseded' or row.get('supersededBy')!=replacement:corrected+=1
                row.update(projectionStatus='superseded',supersededBy=replacement,correction=deepcopy(s['correction']))
            if s.get('origin')!=VERSION and s.get('extractionVersion')!=VERSION:continue
            if sid in rows:continue
            rid=namespaced(s['recordId']);item=items.get(rid)
            if not item:continue
            r=records[s['recordId']];target=entities[s['object']['id']];ev=s['evidence'][0]
            proof=support(ev,rid,sid);eid=sid+':e0';loc=item['locator']
            if eid not in evidences:
                e={'id':eid,'sourceId':g['runId'],'sourceName':item.get('sourceName',''),
                   'kind':'page','page':proof['page'],'ordinal':proof['page'],'volume':label,'volumePage':ev['page'],
                   'locator':loc,'text':ev['text'],'previewUrl':proof['previewUrl'],'captionUrl':'',
                   'bbox':proof['normalizedBbox'],'status':'机器候选 · 尚未人工确认'}
                manifest['evidence'].append(e);evidences[eid]=e
            row={'id':sid,'artifactId':item['artifactId'],'sourceRecordId':rid,'artifact':item['artifact'],
                'item':r['item'],'page':item['page'],'volume':label,'volumePage':r['page'],
                'sourceName':item.get('sourceName',''),'locator':loc,'proofLocator':loc,
                'predicate':s['predicate'],'object':target['label'],'objectId':f"merged:{target['kind']}:{target['label']}",
                'evidenceId':eid,'quote':r['text'],'origin':s['origin'],'extractionVersion':VERSION,
                'binding':deepcopy(s['binding']),'extractionMethod':s['extractionMethod'],
                'qualifiers':deepcopy(s['qualifiers']),'issues':s['issues'],
                'supportingEvidence':[support(value,rid,sid) for value in s['evidence']],
                'status':'机器候选 · 尚未人工确认','reviewStatus':'unreviewed'}
            rows[sid]=row;source_rows.append(row);added+=1
        interp_map={namespaced(x['id']):x for x in g.get('interpretations',[])}
        for record in manifest.get('interpretations',[]):
            original=interp_map.get(record['id'])
            if original and record.get('context')!=original.get('context'):
                record['context']=deepcopy(original.get('context'));context_updated+=1
    # Source images/quotes/IDs stay intact. Only rebuild derived type caches.
    active_types=defaultdict(list)
    for row in source_rows:
        if active_assertion(row) and row['predicate']=='artifact_type':
            key=row.get('sourceRecordId',row.get('artifactId'))
            if row['object'] not in active_types[key]:active_types[key].append(row['object'])
    for item in source_items:
        item['artifactTypes']=active_types[item.get('sourceRecordId',item['artifactId'])]
    manifest['sourceItems'],manifest['sourceRows']=source_items,source_rows
    identity=graphs[volume]['artifactIdentity'] if volume else combine_identities([g['artifactIdentity'] for g in graphs.values()])
    apply_manifest_identity(manifest,identity,volume)
    manifest['summary'].update(predicateCounts=dict(Counter(r['predicate'] for r in manifest['rows'])),
        graphEdges=len(manifest['rows'])+2*len(manifest.get('interpretations',[])))
    return {'addedSourceRelations':added,'correctedSourceRelations':corrected,'interpretationContexts':context_updated}


def coverage(manifest):
    by=defaultdict(set)
    for row in manifest['rows']:
        if row.get('artifactId'):by[row['predicate']].add(row['artifactId'])
    return {pred:len(by[pred]) for pred in ['period','made_of','artifact_type','decorated_with','uses_technique',
        'has_shape','decorated_with_material','belongs_to_culture','has_composition','decorated_part']}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    hashes,graphs,reports,originals={},{},{},{}
    for v,root,_ in VOLUMES:
        p=root/'graph.json';hashes[p]=digest(p);g=load(p);originals[v]=deepcopy(g)
        reports[v]=enrich_catalog(g)
        if reports[v]['added'] or reports[v]['corrections'] or reports[v]['interpretationsContextUpdated']:
            g['artifactIdentity']['sourcePayloadSha256']=payload_fingerprint(g)
        validate(g);graphs[v]=g
        if g['artifactIdentity']['sourceToCanonical']!=originals[v]['artifactIdentity']['sourceToCanonical']:
            raise ValueError('Catalog supplementation must not change object identities')
    changed=any(r['added'] or r['corrections'] or r['interpretationsContextUpdated'] for r in reports.values())
    brief={v:{k:r[k] for k in ['added','byPredicate','byOrigin','interpretationsContextUpdated']}|
              {'corrected':len(r['corrections'])} for v,r in reports.items()}
    if not args.apply or not changed:
        if changed:save(DATA/'report/catalog-structure-dry-run.json',{'version':VERSION,'volumes':reports})
        print(json.dumps({'applied':args.apply,'changed':changed,'volumes':brief},ensure_ascii=False));return
    sites=[(site,v) for v,_,site in VOLUMES]+[(DATA/'merged/site',None)]
    paths=list(hashes)
    for site,_ in sites:
        p=site/'manifest.json';hashes[p]=digest(p);paths.extend([p,site/'index.html',site/'atlas_viewer.html'])
    for _,root,_ in VOLUMES:paths.extend([root/'summary.json',root/'database-import.json'])
    backup=backup_all(paths,DATABASE);print('Backup: '+str(backup),flush=True)
    for p,sha in hashes.items():
        if digest(p)!=sha:raise ValueError('Concurrent source update; rerun: '+str(p))
    stage=backup/'catalog-staging';stage.mkdir()
    for v,root,_ in VOLUMES:
        if not (reports[v]['added'] or reports[v]['corrections'] or reports[v]['interpretationsContextUpdated']):
            reports[v]['database']=load(root/'database-import.json')
            continue
        p=stage/(v+'.json');out=stage/(v+'-database.json');save(p,graphs[v])
        code=('import sys;from pathlib import Path;from kg_v2.common import load,save;from kg_v2_store import persist;'
              'g=load(sys.argv[1]);r=persist(g,Path(sys.argv[2]));save(sys.argv[1],g);save(sys.argv[3],r)')
        subprocess.run([sys.executable,'-c',code,str(p),str(DATABASE.parent),str(out)],check=True,cwd=ROOT,
            env={**os.environ,'WIKIBRIDGE_KG_DATA':str(root),'PYTHONPATH':str(ROOT/'scripts')})
        graphs[v]=load(p);reports[v]['database']=load(out)
    for p,sha in hashes.items():
        if digest(p)!=sha:raise ValueError('Concurrent update during staging; no source overwrite: '+str(p))
    outputs={}
    for site,volume in sites:
        manifest=load(site/'manifest.json');before=coverage(manifest)
        diff=update_manifest(manifest,graphs if not volume else {volume:graphs[volume]},volume)
        diff.update(before=before,after=coverage(manifest),validation=validate_manifest(manifest,site))
        outputs[str(site.relative_to(ROOT))]=diff
        if volume:manifest['runId']=graphs[volume]['runId']
        else:
            for v in manifest['volumes']:v['runId']=graphs[v['prefix']]['runId']
        manifest['identityRunId']=ident('identity-projection',[g['runId'] for g in graphs.values()],manifest['artifactIdentity']['recordToCanonical'])
        manifest['catalogStructureEnrichment']={'version':VERSION,'applied':True,'ocrRerun':False,'llmCalls':0}
        write_site(site,manifest)
    for v,root,_ in VOLUMES:
        g=graphs[v];before=originals[v]
        for field in ['records','events','mentions','identityProposals','identityDecisions']:
            if g[field]!=before[field]:raise ValueError('Unexpected source change: '+field)
        if g['entities'][:len(before['entities'])]!=before['entities']:
            raise ValueError('Original source entities changed')
        for old,new in zip(before['assertions'],g['assertions']):
            if any(new.get(k)!=value for k,value in old.items()):raise ValueError('Original assertion field changed')
        save(root/'graph.json',g);save(root/'summary.json',g['summary']);save(root/'database-import.json',reports[v]['database'])
    report={'version':VERSION,'applied':True,'backup':str(backup),'volumes':reports,'display':outputs,
        'canonicalIdentityMappingsUnchanged':True,'originalSourcePayloadPreserved':True,'ocrRerun':False,'llmCalls':0}
    save(DATA/'report/catalog-structure-applied.json',report)
    print(json.dumps({'applied':True,'volumes':brief,'display':outputs},ensure_ascii=False))


if __name__=='__main__':main()
