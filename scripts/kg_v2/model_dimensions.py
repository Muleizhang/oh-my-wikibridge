"""Model-first caption dimensions. Rules validate/normalize existing neural spans."""
from collections import Counter
import re
from .common import ident
from .identity import normalize_name
from .records import local_evidence

VERSION = 'model-dimensions-v2'
DIMENSIONS = {
    'uses_technique': ('technique', '工艺', 'techniques'),
    'belongs_to_culture': ('culture', '文化归属', 'cultures'),
    'has_composition': ('composition', '构图形式', 'compositions'),
    'decorated_part': ('decoration_part', '装饰部位', 'decorationParts'),
    'decoration_role': ('decoration_role', '装饰角色', 'decorationRoles'),
    'excavated_at': ('place', '出土地点', 'excavationPlaces'),
    'discovered_at': ('place', '发现地点', 'discoveryPlaces'),
    'collected_at': ('place', '采集地点', 'collectionPlaces'),
    'held_by': ('organization', '收藏单位', 'holders'),
}
ALIASES = {'镂雕': '镂空', '划刻': '刻划', '二方连续纹': '二方连续', '四方连续纹': '四方连续',
           '衬地': '地纹', '边纹': '边饰', '颈': '颈部', '肩': '肩部', '腹': '腹部', '足': '足部',
           '器腹': '腹部', '壶腹': '腹部', '罐腹': '腹部', '罐肩': '肩部', '器颈': '颈部', '口沿部分': '口沿'}
NEGATION = re.compile(r'(?:不是|并非|不作|不用|未用|没有|不采用|未采用|非)\s*$')


def model_value(predicate, raw, context):
    value = normalize_name(raw).strip('“”「」《》、，。；：: ')
    if not value or len(value) > 40 or re.search(r'\d|厘米|毫米|口径|底径|、|，|；', value):
        return None
    if predicate == 'belongs_to_culture':
        if not value.endswith('文化') or any(v in value for v in ['博物', '艺术中心', '传统文化', '中国文化']):
            return None
    elif predicate == 'uses_technique':
        if len(value) < 2 or value in {'彩陶', '青铜', '铜', '金', '银', '玉', '金丝', '陶', '丝', '漆', '纹样'}:
            return None
        if value.endswith(('纹', '器', '壶', '盆', '镜', '盒', '戈')) or len(value) > 16:
            return None
    elif predicate == 'held_by':
        if '窖藏' in context or not any(v in context for v in ['藏', '收藏']):
            return None
        if not any(v in value for v in ['馆', '院', '学会', '文管', '中心', '寺', '宫', '研究所']):
            return None
    elif predicate == 'decorated_part':
        if any(v in context for v in ['出土', '收藏', '采集', '发现', '厘米', '毫米', '藏']):
            return None
        if not any(v in context for v in ['纹', '饰', '图案', '彩绘', '浮雕']):
            return None
        parts = ['口沿', '内壁', '外壁', '颈部', '肩部', '腹部', '腰部', '底部', '足部', '边缘',
                 '器盖', '壶盖', '鼎耳', '剑柄', '刀柄', '镜背', '盘心', '盆内', '碑首', '底座', '甬道', '天井', '地面', '顶面', '志盖边']
        # Only narrow the already predicted span; never create a new field match.
        value = ALIASES.get(value, value)
        if value not in parts:
            suffix = next((part for part in parts if value.endswith(part)), None)
            if suffix is None:
                return None
            value = suffix
    elif predicate == 'has_composition':
        if not any(v in value for v in ['连续', '对称', '散点', '放射', '排列', '构图', '满地', '适合', '式', '环形', '组织']):
            return None
    elif predicate == 'decoration_role' and value not in {'主纹', '地纹', '边饰', '边纹', '辅助纹样', '衬地'}:
        return None
    return ALIASES.get(value, value)


def model_records(extraction):
    doc = extraction['document']
    for record in extraction['records']:
        if record['issues'] or len(record['text']) > 350 or len(record['label']) > 80:
            continue
        if re.search(r'\d+[.．、]', record['label']):
            continue
        a, b = record['span']
        yield {'record': record, 'document': doc, 'base': a, 'text': doc['text'][a:b]}


class Enricher:
    def __init__(self, graph):
        self.graph = graph
        self.entities = {e['id']: e for e in graph['entities']}
        self.seen = {(s['subject'], s['predicate'], normalize_name(self.entities[s['object']['id']]['label']))
                     for s in graph['assertions'] if s['object']['kind'] == 'entity' and s['object']['id'] in self.entities}
        self.added, self.methods, self.skipped = Counter(), Counter(), Counter()

    def add_prediction(self, job, prediction):
        record, doc = job['record'], job['document']
        pred, method = prediction['predicate'], prediction['method']
        if method not in {'local_uie', 'local_gliner'}:
            raise ValueError('A neural span prediction is required')
        a, b = job['base']+prediction['start'], job['base']+prediction['end']
        if not record['span'][0] <= a < b <= record['span'][1]:
            raise ValueError('Model span crosses record boundary')
        raw = doc['text'][a:b]
        if raw != prediction['text']:
            raise ValueError('Model output must be an exact source span')
        begin = max(doc['text'].rfind('\n', record['span'][0], a)+1, record['span'][0])
        stop = doc['text'].find('\n', b, record['span'][1])
        context = doc['text'][begin:stop if stop >= 0 else record['span'][1]]
        if pred in {'excavated_at', 'discovered_at', 'collected_at'}:
            if '、' in context:
                self.skipped['multiple_locations_unbound'] += 1
                return
            following = doc['text'][b:min(record['span'][1], b+16)]
            markers = [(following.find(marker), relation) for marker, relation in
                       [('出土', 'excavated_at'), ('发现', 'discovered_at'), ('采集', 'collected_at')]
                       if marker in following]
            if not markers:
                self.skipped['location_relation_not_explicit'] += 1
                return
            pred = min(markers)[1]
        if NEGATION.search(doc['text'][max(record['span'][0], a-8):a]):
            self.skipped['negated_field'] += 1
            return
        value = model_value(pred, raw, context)
        if value is None:
            self.skipped['field_contract'] += 1
            return
        if pred == 'uses_technique' and doc['text'][b:b+1] == '纹':
            self.skipped['technique_inside_motif_name'] += 1
            return
        subject = ident('entity', record['id'])
        key = subject, pred, normalize_name(value)
        if subject not in self.entities or key in self.seen:
            return
        kind, label, _ = DIMENSIONS[pred]
        ev = local_evidence(doc, a, b)
        target = ident('entity', VERSION, record['id'], pred, value)
        self.entities[target] = {'id': target, 'label': value, 'kind': kind, 'recordId': record['id'],
            'scope': 'source_mention', 'identityStatus': 'unresolved', 'aliases': list(dict.fromkeys([value, raw])),
            'description': record['text'], 'evidence': [ev]}
        self.graph['entities'].append(self.entities[target])
        self.graph['assertions'].append({'id': ident('statement', VERSION, record['id'], pred, value),
            'subject': subject, 'recordId': record['id'], 'predicate': pred, 'label': label,
            'object': {'kind': 'entity', 'id': target}, 'evidence': [ev], 'origin': VERSION,
            'extractionMethod': method, 'modelScore': prediction['score'],
            'binding': {'kind': method, 'recordId': record['id'], 'item': record['item'], 'scope': 'catalog_record',
                        'raw': raw, 'model': prediction['model'], 'revision': prediction['revision']},
            'qualifiers': [], 'issues': [], 'status': 'candidate', 'reviewStatus': 'unreviewed'})
        self.seen.add(key)
        self.added[pred] += 1
        self.methods[method] += 1

    def report(self):
        self.graph['summary'].update(entities=len(self.graph['entities']), assertions=len(self.graph['assertions']))
        report = {'version': VERSION, 'added': dict(self.added), 'totalAdded': sum(self.added.values()),
                  'methods': dict(self.methods), 'skipped': dict(self.skipped), 'ocrRerun': False,
                  'llmCalls': 0, 'modelRequired': True, 'scope': 'record-local model spans',
                  'semanticAccuracy': 'not_independently_measured'}
        self.graph['dimensionEnrichment'] = report
        return report
