"""Read explicit material+carrier phrases in names, keeping exact source spans."""
from collections import Counter
import re

from .common import ident
from .records import local_evidence

VERSION = 'catalog-name-material-v1'


def name_material(record, document):
    # Lazy imports avoid changing the existing caption/type module dependency order.
    from .caption_fields import FORM, MATERIALS
    from .artifact_types import TOKENS
    materials = {**MATERIALS, '玻璃': '玻璃', '水晶': '水晶', '玛瑙': '玛瑙',
                 '琥珀': '琥珀', '贝': '贝', '铅': '铅', '锡': '锡'}
    heads = (set(FORM.split('|')) | set(TOKENS) | {
        '鉴', '鑑', '匝', '钫', '铎', '铙', '鼓', '棺', '棺椁', '佛像', '造像', '像',
        '织物', '绢', '绫', '绮', '绸', '锦', '褐', '帽', '袍', '衣', '裙', '鞋', '袜',
        '带', '席', '缎', '砖', '瓦', '刻', '刻板', '片', '残片', '钉', '铆钉', '贮贝器'})
    # Fish/dragon names can describe living subjects; a carrier must be explicit.
    heads -= {'龙', '鸟', '虎', '鱼', '人头'}
    heads = {h for h in heads if not any(h.startswith(m) and len(h)>len(m) for m in materials)}
    pattern = re.compile('(?P<material>' + '|'.join(sorted(materials, key=len, reverse=True)) + ')'
        r'(?:雕|塑|质|制|绘|釉|高足|双耳|三足|四足|方|圆|扁|大|小|冠状){0,3}'
        '(?P<carrier>' + '|'.join(re.escape(x) for x in sorted(heads, key=len, reverse=True)) + ')')
    a,b = record['titleSpan']; title = document['text'][a:b]
    if re.search(r'\d+[.．、]', title): return None, 'multiple_captions_in_title'
    if '仿' in title: return None, 'imitation_material_uncertain'
    indices = [i for i,c in enumerate(title) if not c.isspace()]
    compact = ''.join(title[i] for i in indices)
    masked = re.sub(r'\([^)]*\)|（[^）]*）', lambda m:' '*len(m[0]), compact)
    candidates = []
    for match in pattern.finditer(masked):
        start,end = match.span('material')
        if start and masked[start-1] in '鎏镀错嵌包贴描涂泥洒': continue
        coating = re.search(r'(?:鎏金|镀金|错金银|包金|嵌金)$', masked[:start])
        if start and masked[start-1] in '金银铜铁铅锡' and not coating: continue
        if start and masked[start-1] == '贮': continue  # 贝 in 贮贝器 names its contents
        if re.match(r'(?:纹|图案|形|状|式)', masked[match.end():]): continue
        candidates.append(match)
    # Depicted axes/mirrors before the motif belong to the decoration, not the carrier.
    after_motif = [m for m in candidates if m.start() > masked.rfind('纹')]
    if after_motif: candidates = after_motif
    if not candidates:
        from .name_structure import parse_name
        parsed = parse_name(record, document).get('material', [])
        if parsed:
            value = parsed[0]
            return {**value, 'phraseSpan': value['span'], 'carrier': 'structured_name'}, None
        return None, 'no_explicit_material_carrier'
    labels = {materials[m['material']] for m in candidates}
    if len(labels) != 1: return None, 'multiple_material_carriers_need_review'
    match = candidates[-1]
    start,end = match.span('material')
    lo,hi = a+indices[start],a+indices[end-1]+1
    return {'label': materials[match['material']], 'span': [lo,hi],
        'phraseSpan': [a+indices[match.start()],a+indices[match.end()-1]+1],
        'raw': document['text'][lo:hi], 'carrier': match['carrier']}, None


def enrich_name_materials(graph):
    """Only fill absent material bindings; never overwrite a model/manual decision."""
    documents = {(d['page'],d['engine']):d for d in graph['documents']}
    records = {r['id']:r for r in graph['records']}
    existing = {s.get('subject') for s in graph['assertions'] if s['predicate'] == 'made_of'}
    added, skipped = [], []
    for entity in list(graph['entities']):
        if entity['kind'] != 'artifact': continue
        record = records[entity['recordId']]
        if entity['id'] in existing: continue
        if record.get('issues'):
            skipped.append({'recordId':record['id'],'reason':'record_unresolved'}); continue
        field,reason = name_material(record,documents[(record['page'],record.get('engine','ppstructure'))])
        if not field:
            skipped.append({'recordId':record['id'],'reason':reason}); continue
        doc = documents[(record['page'],record.get('engine','ppstructure'))]
        ev = local_evidence(doc,*field['span'])
        phrase = local_evidence(doc,*field['phraseSpan'])
        target = ident('entity',VERSION,record['id'],field['label'])
        graph['entities'].append({'id':target,'label':field['label'],'kind':'material',
            'recordId':record['id'],'scope':'source_mention','identityStatus':'unresolved',
            'aliases':list(dict.fromkeys([field['label'],field['raw']])),
            'evidence':[ev],'description':record['text']})
        statement = {'id':ident('statement',VERSION,record['id'],field['label']),
            'subject':entity['id'],'recordId':record['id'],'predicate':'made_of','label':'材质',
            'object':{'kind':'entity','id':target},'qualifiers':[], 'evidence':[ev,phrase],
            'origin':VERSION,'extractionVersion':VERSION,'issues':[],
            'status':'candidate','reviewStatus':'unreviewed',
            'binding':{'kind':'catalog_name_material','recordId':record['id'],'item':record['item'],
                'raw':field['raw'],'carrier':field['carrier'],'ruleVersion':VERSION}}
        graph['assertions'].append(statement); added.append(statement); existing.add(entity['id'])
    report = {'version':VERSION,'added':len(added),'materials':dict(Counter(
        s['binding']['raw'] for s in added)),'statementIds':[s['id'] for s in added],
        'skipped':skipped,'ocrRerun':False,'modelsRerun':False,'llmCalls':0}
    if added:
        graph['nameMaterialEnrichment'] = {k:v for k,v in report.items() if k!='skipped'}
        graph['summary'].update(entities=len(graph['entities']),assertions=len(graph['assertions']))
    return report
