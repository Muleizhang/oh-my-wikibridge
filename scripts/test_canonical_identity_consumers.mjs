import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {createKGReasoner, normalizeKG} from '../src/kg-reasoner.js';

function graphFixture() {
  const records=['a','b','c'].map((id,index)=>({id,label:'人面鱼纹彩陶盆',page:index+1,item:1,text:`图录 ${id}`}));
  const entities=[...records.map(rec=>({id:`entity-${rec.id}`,kind:'artifact',label:rec.label,recordId:rec.id})),
    {id:'motif',kind:'motif',label:'鸟纹'},{id:'new',kind:'period',label:'新石器时代'},
    {id:'shang',kind:'period',label:'商代'}];
  const assertions=[['a','period','new'],['b','period','new'],['a','decorated_with','motif'],
    ['b','decorated_with','motif'],['c','period','shang']].map(([owner,predicate,target],i)=>({
      id:`statement-${i}`,subject:`entity-${owner}`,recordId:owner,predicate,
      object:{kind:'entity',id:target},status:'candidate',reviewStatus:'unreviewed',
      evidence:[{page:records.find(rec=>rec.id===owner).page,text:`出处 ${i}`}]}));
  return {records,entities,assertions,events:[],documents:[],artifactIdentity:{version:'strict-v1',volume:'v1',
    recordToCanonical:{a:'canonical-ab',b:'canonical-ab',c:'canonical-c'},
    sourceToCanonical:{'entity-a':'canonical-ab','entity-b':'canonical-ab','entity-c':'canonical-c'},
    entities:[{id:'canonical-ab',label:'人面鱼纹彩陶盆',decision:'automatic_rule_supported',members:[
      {volume:'v1',recordId:'a',sourceRecordId:'v1:a',sourceEntityId:'v1:entity-a'},
      {volume:'v1',recordId:'b',sourceRecordId:'v1:b',sourceEntityId:'v1:entity-b'}]},
      {id:'canonical-c',label:'人面鱼纹彩陶盆',decision:'source_record_only',members:[]}]}};
}
function manifestFixture() {
  const graph=graphFixture();
  const sourceItems=['a','b','c'].map((id,index)=>({artifactId:`v1:${id}`,sourceRecordId:`v1:${id}`,
    canonicalArtifactId:id==='c'?'canonical-c':'canonical-ab',artifact:'人面鱼纹彩陶盆',
    page:index+1,locator:`第一册 · PDF 第 ${index+1} 页`,imageUrl:`${id}.jpg`,pageUrl:`p${index+1}.jpg`,evidenceId:`ev-${id}`}));
  const sources=['a','b'].map(id=>({id:`row-${id}`,artifactId:`v1:${id}`,sourceRecordId:`v1:${id}`,
    predicate:'decorated_with',object:'鸟纹',evidenceId:`ev-${id}`,page:id==='a'?1:2,
    supportingEvidence:[{page:id==='a'?1:2,text:`出处 ${id}`}]}));
  const row={...sources[0],id:'canonical-edge-ab',artifactId:'canonical-ab',sources,
    evidenceIds:['ev-a','ev-b'],supportingEvidence:sources.flatMap(source=>source.supportingEvidence)};
  return {artifactIdentity:{...graph.artifactIdentity,recordToCanonical:{}},sourceItems,sourceRows:sources,
    items:[{...sourceItems[0],artifactId:'canonical-ab',sourceRecords:sourceItems.slice(0,2)},
      {...sourceItems[2],artifactId:'canonical-c',sourceRecords:sourceItems.slice(2)}],rows:[row],
    evidence:sourceItems.map(source=>({id:source.evidenceId,page:source.page,text:`出处 ${source.sourceRecordId}`}))};
}

test('typed graph uses canonical identities and retains all records and relationship evidence',()=>{
  const graph=graphFixture(),reasoner=createKGReasoner(graph),kg=reasoner.kg;
  assert.equal(kg.artifacts.size,2);
  assert.equal(kg.artifacts.get('canonical-ab').sourceRecords.length,2);
  assert.equal(kg.triples.length,3);
  assert.equal(kg.triples.find(t=>t.predicate==='decorated_with').sources.length,2);
  assert.equal(kg.triples.find(t=>t.predicate==='decorated_with').supportingEvidence.length,2);
  assert.equal(reasoner.queryArtifacts({motif:'鸟纹',useOntology:false}).count,1);
  assert.equal(reasoner.inspectEvidence('v1:b').artifact.id,'canonical-ab');
  assert.equal(reasoner.inspectEvidence('entity-b').artifact.id,'canonical-ab');
  assert.equal(reasoner.getCatalogSummary().counts.sourceRecords,3);
  assert.equal(graph.entities.length,6,'source graph is not mutated');
});

test('SPARQL joins by canonical ID instead of joining different same-name objects',()=>{
  const reasoner=createKGReasoner(graphFixture());
  assert.equal(reasoner.runSparql('SELECT ?a WHERE { ?a :period "商代" . ?a :decorated_with "鸟纹" . }',{useOntology:false}).rows.length,0);
  const rows=reasoner.runSparql('SELECT DISTINCT ?a WHERE { ?a :label "人面鱼纹彩陶盆" . }',{useOntology:false}).rows;
  assert.deepEqual(new Set(rows.map(row=>row['?a'])),new Set(['canonical-ab','canonical-c']));
});

test('manifest consumer retains both source images and complete merged relation sources',()=>{
  const manifest=manifestFixture(),reasoner=createKGReasoner(manifest);
  assert.equal(reasoner.queryArtifacts({motif:'鸟纹'}).count,1);
  const result=reasoner.inspectEvidence('v1:b');
  assert.equal(result.artifact.sourceRecords.length,2);
  assert.deepEqual(result.artifact.sourceRecords.map(source=>source.imageUrl),['a.jpg','b.jpg']);
  assert.equal(result.evidence[0].sources.length,2);
  assert.deepEqual(result.evidence[0].evidenceIds,['ev-a','ev-b']);
  assert.equal(reasoner.getCatalogSummary().counts.artifacts,2);
  const legacy=structuredClone(manifest);delete legacy.artifactIdentity;
  assert.equal(normalizeKG(legacy).artifacts.size,2);
});

test('different relation qualifiers remain separately queryable after identity alignment',()=>{
  const graph=graphFixture();
  const motifFacts=graph.assertions.filter(fact=>fact.predicate==='decorated_with');
  motifFacts[0].qualifiers=[{part:'口沿'}];
  motifFacts[1].qualifiers=[{part:'腹部'}];
  const kg=normalizeKG(graph);
  assert.equal(kg.triples.filter(triple=>triple.predicate==='decorated_with').length,2);
});

test('atlas model keeps canonical nodes and separately addressable source pages',()=>{
  const text=readFileSync(new URL('./atlas_viewer.html',import.meta.url),'utf8');
  const start=text.indexOf('  function buildGraphModel('),end=text.indexOf('\n  /*',start);
  const sandbox={URL,EXTRA_DIMENSIONS:{},predToKind:()=>'',eraChronology:label=>({group:label,order:1}),hashStr:()=>1};
  vm.createContext(sandbox);vm.runInContext(text.slice(start,end)+'\nthis.build = buildGraphModel;',sandbox);
  const manifest=manifestFixture();
  const source=manifest.sourceItems[1];
  const cropDir='annotations-v2/vol1/p0002';
  Object.assign(source, { sourceEntityId:'v1:entity-b', imageKind:'artifact_candidate',
    detailUrl:`${cropDir}/groups/b-thumb.jpg`, imageUrl:`${cropDir}/crops/b.jpg`,
    imageCandidates:[{imageUrl:`${cropDir}/crops/part.jpg`}] });
  delete source.canonicalArtifactId;
  manifest.artifactIdentity.sourceToCanonical[source.sourceEntityId]='canonical-ab';
  manifest.pages=[{page:2,previewUrl:'assets/originals/v1/v1-p0002.source.jpg'}];
  const model=sandbox.build(manifest,'http://localhost:1423/kg/manifest.json');
  assert.equal(model.items.length,2);
  assert.equal(model.sourceItems.length,3);
  assert.equal(model.itemById.get('canonical-ab').sourceRecords.length,2);
  assert.equal(model.canonicalBySource.get('v1:b').id,'canonical-ab');
  assert.equal(model.canonicalBySource.get('v1:entity-b').id,'canonical-ab');
  const record=model.sourceById.get('v1:entity-b');
  assert.equal(record,model.sourceById.get('v1:b'));
  assert.equal(record.page,2);
  assert.equal(record.imageKind,'artifact_candidate');
  assert.equal(record.thumbUrl,`http://localhost:1423/kg/${cropDir}/groups/b-thumb.jpg`);
  assert.equal(record.plateUrl,`http://localhost:1423/kg/${cropDir}/crops/b.jpg`);
  assert.equal(record.imageCandidates[0].imageUrl,`http://localhost:1423/kg/${cropDir}/crops/part.jpg`);
  assert.equal(record.pageUrl,'http://localhost:1423/kg/p2.jpg');
  assert.equal(model.pages[0].previewUrl,'http://localhost:1423/kg/assets/originals/v1/v1-p0002.source.jpg');
});
