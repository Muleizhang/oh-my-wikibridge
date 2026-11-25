"""Source-preserving catalog corrections, name slots and bounded section context."""
from collections import Counter, defaultdict
from copy import deepcopy
import re

from .common import ident
from .name_structure import VERSION, parse_name
from .projection import active_assertion
from .records import local_evidence

FIELDS = {'material':('made_of','材质'),'artifact_type':('artifact_type','器类'),
          'motif':('decorated_with','纹样'),
          'technique':('uses_technique','工艺'),'shape':('has_shape','造型'),
          'decoration_material':('decorated_with_material','装饰材料'),
          'culture':('belongs_to_culture','文化归属'),'composition':('has_composition','构图形式'),
          'decoration_part':('decorated_part','装饰部位'),'period':('period','所属时代')}
CULTURE = re.compile(r'(?:仰韶|马家窑|半坡|庙底沟|龙山|大汶口|良渚|红山|河姆渡|齐家|二里头|大溪|屈家岭|马家浜|崧泽|卡若|昂昂溪|凤鼻头|新开流|夏家店下层)文化')
CONTEXT_ORIGINS={'catalog_section_context','same_page_culture_context'}


def section_scopes(graph):
    """Read only explicit plate dividers; prose, TOC and mixed headings are barriers."""
    docs=sorted((d for d in graph['documents'] if d['engine']=='ppstructure'),key=lambda d:d['page'])
    headings=[]
    for d in docs:
        for b in d['blocks']:
            text=re.sub(r'\s+','',b['text'])
            if text=='新石器时代' or re.fullmatch(r'商[、·・]西周[、·・]春秋',text):
                box=b.get('bbox')
                if box and box[2]-box[0] < box[3]-box[1]:continue  # vertical map label
                has_records=any(r['page']==d['page'] for r in graph['records'])
                if has_records:
                    if d.get('pageKind')!='plate' or (box and box[1]>d['imageSize'][1]*.22):continue
                elif len(re.sub(r'[\s\d]','',d['text']))>65:
                    continue  # prose/map mentions do not start a plate section
                offset=b['text'].find('新石器时代') if text=='新石器时代' else 0
                ev=local_evidence(d,b['start']+max(0,offset),b['end'])
                headings.append({'page':d['page'],'label':'新石器时代' if text=='新石器时代' else None,
                                 'heading':b['text'],'evidence':ev})
    scopes=[]
    for i,h in enumerate(headings):
        if h['label']:
            stop=headings[i+1]['page'] if i+1<len(headings) else max(graph['selection'])+1
            scopes.append({**h,'endPageExclusive':stop})
    return scopes


def interpretation_context(record,documents):
    ev=record['evidence'][0];doc=documents[(ev['page'],ev['engine'])]
    a,b=ev['span'];text=doc['text'][a:b]
    value_at=record['valueEvidence']['span'][0]-a
    certainty_matches=list(re.finditer(r'可能|似乎|或许|推测|据说|大概|或可',text))
    cultures=list(CULTURE.finditer(text))
    period_matches=list(re.finditer(r'先秦|封建社会|新石器时代|商代|殷代|西周|东周|春秋|战国|西汉|东汉|汉代|两宋|宋代|唐代|北魏|南北朝',text))
    preceding=[m for m in period_matches if m.start()<=value_at]
    selected=preceding[-1:] if preceding else period_matches if len(period_matches)==1 else []
    contexts={'cultures':list(dict.fromkeys(m[0] for m in cultures)),
        'periods':[m[0] for m in selected],
        'usages':list(dict.fromkeys(m[0] for m in re.finditer(r'随葬|祭祀|丧葬|佛教|礼仪|宗教',text))),
        'certainty':'hypothesis' if certainty_matches else 'reported_claim',
        'certaintyMarkers':list(dict.fromkeys(m[0] for m in certainty_matches)),
        'attribution':'reported_view' if re.search(r'认为|说法|指出|推测',text) else 'source_text',
        'scopeStatus':'source_context_candidate','ruleVersion':VERSION,
        'evidence':[local_evidence(doc,a+m.start(),a+m.end()) for m in [*cultures,*selected,*certainty_matches]]}
    return contexts


def enrich_catalog(graph):
    entities={e['id']:e for e in graph['entities']}
    documents={(d['page'],d['engine']):d for d in graph['documents']}
    records={r['id']:r for r in graph['records']}
    by_subject=defaultdict(list)
    for s in graph['assertions']:by_subject[s.get('subject')].append(s)
    added,corrected=[],[]
    def add(owner,kind,value,*,origin=VERSION,extra_evidence=(),binding=None,qualifiers=None):
        pred,label=FIELDS[kind];r=records[owner['recordId']]
        same=[s for s in by_subject[owner['id']] if active_assertion(s) and s['predicate']==pred
              and entities.get(s['object'].get('id'),{}).get('label')==value['label']]
        if same:return same[0]
        doc=documents[(r['page'],r.get('engine','ppstructure'))]
        proof=local_evidence(doc,*value['span'])
        target=ident('entity',VERSION,r['id'],kind,value['label'])
        if target not in entities:
            ent={'id':target,'kind':kind,'label':value['label'],'recordId':r['id'],'scope':'source_mention',
                 'identityStatus':'unresolved','aliases':list(dict.fromkeys([value['label'],proof['text']])),
                 'evidence':[proof],'description':r['text']}
            graph['entities'].append(ent);entities[target]=ent
        s={'id':ident('statement',VERSION,r['id'],pred,value['label'],origin),
            'subject':owner['id'],'recordId':r['id'],'predicate':pred,'label':label,
            'object':{'kind':'entity','id':target},'evidence':[proof,*deepcopy(extra_evidence)],
            'origin':origin,'extractionVersion':VERSION,'extractionMethod':'source_structure_rule',
            'binding':{'kind':'catalog_structure','recordId':r['id'],'item':r['item'],
                       'raw':proof['text'],**(binding or {})},'qualifiers':qualifiers or [],
            'issues':[('contextual_period_assignment_pending' if kind=='period' else 'contextual_culture_assignment_pending')]
                      if origin in CONTEXT_ORIGINS else [],
            'status':'candidate','reviewStatus':'unreviewed'}
        graph['assertions'].append(s);by_subject[owner['id']].append(s);added.append(s)
        return s
    def supersede(s,new,reason):
        s['projectionStatus']='superseded';s['supersededBy']=list(dict.fromkeys(x['id'] for x in new))
        s['correction']={'ruleVersion':VERSION,'reason':reason,'decision':'automatic_source_reclassification',
                         'humanVerified':False}
        corrected.append({'statementId':s['id'],'replacementIds':s['supersededBy'],'reason':reason})
    scopes=section_scopes(graph)
    artifacts=[e for e in graph['entities'] if e['kind']=='artifact']
    for owner in artifacts:
        r=records[owner['recordId']]
        if r.get('issues'):continue
        doc=documents[(r['page'],r.get('engine','ppstructure'))]
        slots=parse_name(r,doc)
        active=lambda pred:[s for s in by_subject[owner['id']] if s['predicate']==pred and active_assertion(s)]
        # Correct only explicit role/type errors. Keep the original statement and status.
        for s in list(by_subject[owner['id']]):
            if not active_assertion(s):continue
            target=entities.get(s['object'].get('id'),{});value=target.get('label','')
            if s['predicate']=='decorated_with' and value=='刻纹':
                ev=next((e for e in s['evidence'] if '刻纹' in e['text']),None)
                if ev:
                    start=ev['span'][0]+ev['text'].index('刻纹')
                    new=add(owner,'technique',{'label':'刻纹','span':[start,start+2]})
                    supersede(s,[new],'engraving_is_a_process_not_a_motif')
            elif s['predicate']=='made_of' and value in {'玉管','石板','黑泥质'}:
                material='玉' if value=='玉管' else '石' if value=='石板' else '陶'
                match=next((f for f in slots.get('material',[]) if f['label']==material),None)
                if match:
                    new=add(owner,'material',match)
                    supersede(s,[new],'separate_material_from_carrier_or_material_description')
            elif s['predicate']=='made_of' and value in {'金箔','银箔'}:
                match=next((f for f in slots.get('decoration_material',[]) if f['label']==value),None)
                if match:
                    new=add(owner,'decoration_material',match)
                    supersede(s,[new],'foil_describes_decoration_not_the_substrate')
            elif s['predicate']=='period' and CULTURE.fullmatch(value):
                ev=next((e for e in s['evidence'] if value in e['text']),None)
                if ev and ev['page']==r['page'] and r['span'][0]<=ev['span'][0]<ev['span'][1]<=r['span'][1]:
                    start=ev['span'][0]+ev['text'].index(value)
                    new=add(owner,'culture',{'label':value,'span':[start,start+len(value)]})
                    supersede(s,[new],'archaeological_culture_has_a_separate_field')
        for kind in ['material','artifact_type','technique','shape','decoration_material','culture','composition','decoration_part']:
            if kind in {'material','artifact_type'} and active(FIELDS[kind][0]):continue
            for value in slots.get(kind,[]):add(owner,kind,value)
        if not active('period') and not re.search(r'或|可能|约早商',r['label']):
            scope=next((s for s in scopes if s['page']<=r['page']<s['endPageExclusive']),None)
            if scope and doc.get('pageKind')=='plate':
                add(owner,'period',{'label':scope['label'],'span':r['titleSpan']},origin='catalog_section_context',
                    extra_evidence=[scope['evidence']],binding={'kind':'bounded_section_heading',
                    'scope':{'startPage':scope['page'],'endPageExclusive':scope['endPageExclusive'],
                             'headingPage':scope['page'],'heading':scope['heading']},'contextual':True})
        # A page can contain different cultures in separate columns. Do not spread either.
        page_records=[x for x in graph['records'] if x['page']==r['page']]
        first=min((x['span'][0] for x in page_records),default=0)
        header_text=doc['text'][:first]
        culture_headers=list(CULTURE.finditer(header_text))
        labels={m[0] for m in culture_headers}
        if len(labels)==1 and not active('belongs_to_culture'):
            match=culture_headers[0]
            ev=local_evidence(doc,*match.span())
            add(owner,'culture',{'label':match[0],'span':r['titleSpan']},origin='same_page_culture_context',
                extra_evidence=[ev],binding={'kind':'same_page_culture_heading','contextual':True})
    contexts_changed=0
    for record in graph.get('interpretations',[]):
        context=interpretation_context(record,documents)
        if record.get('context')!=context:record['context']=context;contexts_changed+=1
    report={'version':VERSION,'added':len(added),'byPredicate':dict(Counter(s['predicate'] for s in added)),
        'byOrigin':dict(Counter(s['origin'] for s in added)),'statementIds':[s['id'] for s in added],
        'corrections':corrected,'interpretationsContextUpdated':contexts_changed,'sectionScopes':scopes,
        'ocrRerun':False,'llmCalls':0}
    if added or corrected or contexts_changed:
        graph['catalogStructureEnrichment']=deepcopy(report)
        graph['summary'].update(entities=len(graph['entities']),assertions=len(graph['assertions']),
            activeAssertions=sum(active_assertion(s) for s in graph['assertions']),
            supersededAssertions=sum(not active_assertion(s) for s in graph['assertions']))
    return report
