#!/usr/bin/env python3
"""Backfill explicit name materials from cached text, retaining canonical identity."""
import argparse
from collections import Counter
from copy import deepcopy
import json
import os
import subprocess
import sys

from apply_artifact_identity import (DATA, DATABASE, VOLUMES, backup_all, digest,
    payload_fingerprint, validate_manifest, write_site)
from kg_v2.common import ROOT, ident, load, save
from kg_v2.identity_manifest import apply_manifest_identity, combine_identities
from kg_v2.name_materials import VERSION, enrich_name_materials
from kg_v2_validate import validate


def update_manifest(manifest,graphs,volume=None):
    source_items=manifest.get('sourceItems',manifest['items'])
    source_rows=manifest.get('sourceRows',manifest['rows'])
    items={i.get('sourceRecordId',i['artifactId']):i for i in source_items}
    row_ids={r['id'] for r in source_rows}; evidence_ids={e['id'] for e in manifest['evidence']}
    page_map={(p.get('volume',''),p.get('volumePage',p['page'])):p for p in manifest['pages']}
    added=0
    for prefix,g in graphs.items():
        label=next((v['label'] for v in manifest.get('volumes',[]) if v['prefix']==prefix),'')
        entities={e['id']:e for e in g['entities']}; records={r['id']:r for r in g['records']}
        docs={(d['page'],d['engine']):d for d in g['documents']}
        for s in g['assertions']:
            if s.get('origin')!=VERSION:continue
            source_id=s['recordId'] if volume else prefix+':'+s['recordId']
            sid=s['id'] if volume else prefix+':'+s['id']
            item=items.get(source_id)
            if not item or sid in row_ids:continue
            r=records[s['recordId']];ev=s['evidence'][0];doc=docs[(ev['page'],ev['engine'])]
            page=page_map[(label,ev['page'])];eid=sid+':e0'
            locator=item['locator'];target=entities[s['object']['id']]
            def support(value):
                box=value.get('bbox'); size=doc['imageSize']
                return {**value,'previewUrl':page['previewUrl'],
                    'normalizedBbox':[x/y for x,y in zip(box,size*2)] if box else None,
                    'sourceRecordId':source_id,'sourceStatementId':sid,
                    'volume':label,'volumePage':value['page'],'page':page['page']}
            if eid not in evidence_ids:
                manifest['evidence'].append({'id':eid,'sourceId':g['runId'],'sourceName':item.get('sourceName',''),
                    'kind':'page','page':page['page'],'ordinal':page['page'],'volume':label,'volumePage':ev['page'],
                    'locator':locator,'text':ev['text'],'previewUrl':page['previewUrl'],
                    'captionUrl':'','bbox':support(ev)['normalizedBbox'],'status':'机器候选 · 尚未人工确认'})
                evidence_ids.add(eid)
            source_rows.append({'id':sid,'artifactId':item['artifactId'],'sourceRecordId':source_id,
                'artifact':item['artifact'],'item':r['item'],'page':item['page'],'volume':label,
                'volumePage':r['page'],'sourceName':item.get('sourceName',''),'locator':locator,'proofLocator':locator,
                'predicate':'made_of','object':target['label'],'objectId':'merged:material:'+target['label'],
                'evidenceId':eid,'quote':r['text'],'origin':VERSION,'binding':deepcopy(s['binding']),
                'extractionMethod':'source_name_rule','ruleVersion':VERSION,'qualifiers':[],
                'supportingEvidence':[support(value) for value in s['evidence']],
                'issues':[],'status':'机器候选 · 尚未人工确认'})
            row_ids.add(sid);added+=1
    manifest['sourceItems'],manifest['sourceRows']=source_items,source_rows
    identity=graphs[volume]['artifactIdentity'] if volume else combine_identities([g['artifactIdentity'] for g in graphs.values()])
    apply_manifest_identity(manifest,identity,volume)
    manifest['summary']['predicateCounts']=dict(Counter(r['predicate'] for r in manifest['rows']))
    manifest['nameMaterialEnrichment']={'version':VERSION,'newSourceEdges':added,'llmCalls':0,'ocrRerun':False}
    return added


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    graphs,reports,hashes={},{},{}
    original_maps={}
    for v,root,_ in VOLUMES:
        path=root/'graph.json';hashes[path]=digest(path);g=load(path)
        original_maps[v]=deepcopy(g.get('artifactIdentity',{}).get('sourceToCanonical',{}))
        reports[v]=enrich_name_materials(g)
        if reports[v]['added'] and g.get('artifactIdentity'):
            g['artifactIdentity']['sourcePayloadSha256']=payload_fingerprint(g)
        validate(g);graphs[v]=g
        if original_maps[v]!=g.get('artifactIdentity',{}).get('sourceToCanonical',{}):
            raise ValueError('Material backfill changed artifact identities')
    brief={v:{k:r[k] for k in ['added','materials']} for v,r in reports.items()}
    if not args.apply or not any(r['added'] for r in reports.values()):
        print(json.dumps({'applied':args.apply,'volumes':brief,'changed':any(r['added'] for r in reports.values())},ensure_ascii=False));return
    sites=[(site,v) for v,_,site in VOLUMES]+[(DATA/'merged/site',None)]
    paths=list(hashes)
    for site,_ in sites:
        path=site/'manifest.json';hashes[path]=digest(path);paths += [path,site/'index.html',site/'atlas_viewer.html']
    for _,root,_ in VOLUMES:paths += [root/'summary.json',root/'database-import.json']
    backup=backup_all(paths,DATABASE)
    print('Backup: '+str(backup),flush=True)
    for path,sha in hashes.items():
        if digest(path)!=sha:raise ValueError('Concurrent source update: '+str(path))
    stage=backup/'material-staging';stage.mkdir()
    for v,root,_ in VOLUMES:
        if not reports[v]['added']:continue
        path=stage/(v+'.json');out=stage/(v+'-database.json');save(path,graphs[v])
        code=('import sys;from pathlib import Path;from kg_v2.common import load,save;from kg_v2_store import persist;'
              'g=load(sys.argv[1]);r=persist(g,Path(sys.argv[2]));save(sys.argv[1],g);save(sys.argv[3],r)')
        subprocess.run([sys.executable,'-c',code,str(path),str(DATABASE.parent),str(out)],check=True,cwd=ROOT,
            env={**os.environ,'WIKIBRIDGE_KG_DATA':str(root),'PYTHONPATH':str(ROOT/'scripts')})
        graphs[v]=load(path);reports[v]['database']=load(out)
    for path,sha in hashes.items():
        if digest(path)!=sha:raise ValueError('Concurrent update during staging: '+str(path))
    outputs={}
    for site,volume in sites:
        m=load(site/'manifest.json');added=update_manifest(m,graphs if not volume else {volume:graphs[volume]},volume)
        outputs[str(site.relative_to(ROOT))]={'addedSourceRelations':added,**validate_manifest(m,site)}
        if volume:m['runId']=graphs[volume]['runId']
        else:
            for v in m['volumes']:v['runId']=graphs[v['prefix']]['runId']
        m['identityRunId']=ident('identity-projection',[g['runId'] for g in graphs.values()],m['artifactIdentity']['recordToCanonical'])
        write_site(site,m)
    for v,root,_ in VOLUMES:
        save(root/'graph.json',graphs[v]);save(root/'summary.json',graphs[v]['summary'])
        if reports[v].get('database'):save(root/'database-import.json',reports[v]['database'])
    report={'version':VERSION,'applied':True,'backup':str(backup),'volumes':reports,'display':outputs,
        'sourceArtifactsUnchanged':True,'canonicalIdentityMappingsUnchanged':True,'ocrRerun':False,'llmCalls':0}
    save(DATA/'report/name-material-enrichment.json',report)
    print(json.dumps({'applied':True,'volumes':brief,'display':outputs},ensure_ascii=False))


if __name__=='__main__':main()
