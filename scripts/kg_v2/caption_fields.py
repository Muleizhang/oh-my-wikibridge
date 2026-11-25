"""Supplement UIE with source-bound caption structure and same-page headings.

These are unreviewed candidates. No cross-page era propagation, inferred historical
transmission, or material guessed from the depicted object is allowed here.
"""
import re

from .common import ident
from .records import local_evidence

VERSION = 'caption-context-v1'
PERIOD = re.compile(
    r'新石器时代(?:早期|中期|晚期)?|旧石器时代|原始社会|'
    r'(?:仰韶|马家窑|半坡|庙底沟|龙山|大汶口|良渚|红山|河姆渡|齐家|二里头)文化|'
    r'(?:商代|殷代|西周|东周|周代|春秋|战国|秦代|西汉|东汉|汉代|唐代|隋代|五代)'
    r'(?:二里岗期|早期|中期|晚期|后期|初期|末期)?'
)
# Longest terms first. Matching an explicit material + carrier protects against
# treating "石斧" depicted in "鹳鸟衔鱼石斧纹彩陶缸" as the vessel's material.
MATERIALS = {
    '青铜': '青铜', '象牙': '象牙', '彩陶': '陶', '红陶': '陶', '白陶': '陶',
    '黑陶': '陶', '灰陶': '陶', '印纹陶': '陶', '釉陶': '陶', '青瓷': '瓷',
    '陶': '陶', '瓷': '瓷', '铜': '铜', '玉': '玉', '石': '石', '骨': '骨',
    '牙': '牙', '角': '角', '木': '木', '竹': '竹', '金': '金', '银': '银',
    '铁': '铁', '丝': '丝', '麻': '麻', '棉': '棉',
}
FORM = (r'器|盆|壶|瓶|罐|缸|碗|盘|钵|杯|豆|鬲|鼎|尊|爵|角|觚|簋|卣|斝|盉|彝|甗|罍|瓿|匜|盂|'
        r'觯|镜|筒|梳|璜|璧|琮|玦|环|佩|饰|戈|矛|斧|刀|剑|钺|钟|磬|'
        r'勺|匕|人头壶|人头|龙|鸟|虎|鱼')
CARRIER = re.compile(r'(?P<material>' + '|'.join(sorted(MATERIALS, key=len, reverse=True))
                     + r')(?:雕|塑|质|制|绘|高足|双耳|三足|四足|方|圆|扁|大|小|冠状){0,3}'
                     + r'(?P<form>' + FORM + r')')
MOTIF = re.compile(r'[\u3400-\u9fffA-Za-z]{1,28}纹(?:样)?')
TECHNIQUE = re.compile(r'彩绘|刻划|镂空|透雕|浮雕|圆雕|阴刻|阳刻|铸造|模印|压印|印花|刻花|刺绣|织造|镶嵌|鎏金')
SHAPE_PREFIX = re.compile(r'^(?:葫芦形|葫芦型|球形|球型|圆形|方形|罐形|壶形)')
PART_PREFIX = re.compile(r'鼎耳|器耳|器身|器腹|器颈|器口|器底|剑柄|刀柄|镜背|器盖|壶盖|鼎足|尊腹|罐肩|盘心|盆内|瓶腹')
STOP_LINE = re.compile(r'出土|收藏|采集|发现|厘米|毫米|千克|公斤|口径|底径|腹径')
LABELS = {'motif': ('decorated_with', '饰有纹样'), 'material': ('made_of', '材质'),
          'period': ('period', '所属时代'), 'technique': ('uses_technique', '采用工艺')}


def name_lines(record):
    """Include wrapped names, stopping before dimensions, locations or commentary."""
    for index, match in enumerate(re.finditer(r'[^\n]+', record['text'])):
        if index > 2 or STOP_LINE.search(match.group()):
            break
        text = match.group()
        prefix = re.match(r'\s*\d{1,2}\s*[.．、]\s*', text) if index == 0 else None
        start = match.start() + (prefix.end() if prefix else 0)
        yield record['span'][0] + start, text[(prefix.end() if prefix else 0):]


def page_period_heading(document, records):
    if not records or document.get('pageKind') != 'plate':
        return None
    first_caption = min(r['span'][0] for r in records)
    candidates = []
    for block in document['blocks']:
        text = block['text'].strip()
        if block['end'] > first_caption or not PERIOD.fullmatch(text):
            continue
        box = block.get('bbox')
        if box and box[1] > document['imageSize'][1] * .22:
            continue
        offset = block['text'].find(text)
        candidates.append((text, block['start'] + offset, block['start'] + offset + len(text)))
    # A mixed-era page heading cannot assign a single era to all captions.
    return candidates[0] if len({x[0] for x in candidates}) == 1 else None


def caption_fields(extraction):
    doc, records = extraction['document'], extraction['records']
    heading = page_period_heading(doc, records)
    fields = []
    explicit_periods = {f['recordId'] for f in extraction.get('fields', []) if f['kind'] == 'period'}

    def add(record, kind, label, start, end, origin, context=None):
        field = {'recordId': record['id'], 'kind': kind, 'label': label,
                 'span': [start, end], 'origin': origin}
        if context:
            field['context'] = context
        fields.append(field)

    for record in records:
        if record.get('issues'):
            continue
        has_period = record['id'] in explicit_periods
        for base, line in name_lines(record):
            # Era strings must occur in the name prefix, never in excavation lines.
            period = PERIOD.match(line)
            if period:
                has_period = True
                add(record, 'period', period.group(), base + period.start(), base + period.end(), 'caption_name_field')
            motif_spans = []
            for match in MOTIF.finditer(line):
                start, end = match.span()
                value = match.group()
                # Strip recognized era/carrier prefixes without manufacturing text.
                dating = PERIOD.match(value)
                if dating:
                    start += dating.end(); value = value[dating.end():]
                carriers = list(CARRIER.finditer(value))
                if carriers:
                    offset = carriers[-1].end()
                    start += offset; value = value[offset:]
                else:
                    material = re.match(r'^(?:青铜器?|铜器|陶器|玉器|骨器)', value)
                    if material:
                        start += material.end(); value = value[material.end():]
                # A later carrier means earlier carrier-shaped words may belong
                # to the depicted motif (e.g. 石斧纹彩陶缸).
                if CARRIER.search(line[end:]) and carriers:
                    start = match.start() + (dating.end() if dating else 0)
                    value = line[start:end]
                parts = list(PART_PREFIX.finditer(value))
                if parts:
                    offset = parts[-1].end()
                    start += offset; value = value[offset:]
                shape = SHAPE_PREFIX.match(value)
                if shape:
                    start += shape.end(); value = value[shape.end():]
                if len(value) < 2 or value in {'花纹', '纹样'}:
                    continue
                motif_spans.append((start, end))
                add(record, 'motif', value, base + start, base + end, 'caption_name_field')
            for match in CARRIER.finditer(line):
                a, b = match.span('material')
                if any(start <= a < end for start, end in motif_spans):
                    continue
                add(record, 'material', MATERIALS[match['material']], base + a, base + b, 'caption_carrier_material')
            for match in TECHNIQUE.finditer(line):
                if not any(a <= match.start() < b for a, b in motif_spans):
                    add(record, 'technique', match.group(), base + match.start(), base + match.end(), 'caption_name_field')
        if heading and not has_period:
            label, start, end = heading
            add(record, 'period', label, *record['titleSpan'], 'page_heading_inheritance',
                {'label': label, 'span': [start, end], 'scope': 'same_page_only'})
    return fields


def supplement_relations(extraction, existing_entities, existing_assertions):
    """Build source-linked candidates, preserving prior UIE results and identities."""
    doc = extraction['document']
    records = {r['id']: r for r in extraction['records']}
    entities = dict(existing_entities)
    seen = {(s.get('subject'), s['predicate'], entities.get(s['object'].get('id'), {}).get('label'))
            for s in existing_assertions if s['object']['kind'] == 'entity'}
    new_entities, statements = [], []
    for field in caption_fields(extraction):
        record = records[field['recordId']]
        subject = ident('entity', record['id'])
        if subject not in entities:
            continue
        pred, label = LABELS[field['kind']]
        key = (subject, pred, field['label'])
        if key in seen:
            continue
        seen.add(key)
        start, end = field['span']
        ev = local_evidence(doc, start, end)
        evidence = [ev]
        binding = {'kind': 'caption_scope', 'recordId': record['id'], 'item': record['item']}
        if field.get('context'):
            evidence.append(local_evidence(doc, *field['context']['span']))
            binding.update(kind='same_page_heading', context=field['context'])
        target = ident('entity', record['id'], field['kind'], VERSION, start, end, field['label'])
        entity = {'id': target, 'label': field['label'], 'kind': field['kind'], 'recordId': record['id'],
                  'scope': 'source_mention', 'identityStatus': 'unresolved',
                  'aliases': [field['label']] if field.get('context') else list(dict.fromkeys([field['label'], ev['text']])),
                  'evidence': evidence, 'description': record['text']}
        new_entities.append(entity); entities[target] = entity
        statements.append({'id': ident('statement', VERSION, record['id'], pred, start, end, field['label']),
            'subject': subject, 'recordId': record['id'], 'predicate': pred, 'label': label,
            'object': {'kind': 'entity', 'id': target}, 'qualifiers': [], 'evidence': evidence,
            'origin': field['origin'], 'extractionVersion': VERSION,
            'issues': ['contextual_period_assignment_pending'] if field.get('context') else [], 'binding': binding,
            'status': 'candidate', 'reviewStatus': 'unreviewed'})
    return new_entities, statements
