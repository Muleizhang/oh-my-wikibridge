"""Derive explicit carrier types from catalog names, never from nearby prose."""
from collections import Counter
import re

from .caption_fields import caption_fields
from .common import ident
from .records import local_evidence

VERSION = 'artifact-name-type-v1'
# Types describe carriers. They do not infer ritual use, symbolic meaning or date.
TOKENS = {
    **{name: name for name in ['画像石', '画像砖', '瓦当', '瓦筒', '壁画', '藻井', '碑刻', '石刻',
        '浮雕', '塑像', '织锦', '刺绣', '绣绢', '绫', '绸', '锦', '漆器', '陶器', '瓷器', '铜器',
        '带钩', '带扣', '冠饰', '耳饰', '佩饰', '饰件', '牌饰', '器盖', '壶盖', '剑柄', '陶拍',
        '纺轮', '博山炉', '灯', '枕', '钗', '簪', '梳', '笄', '钏', '镯',
        '盆', '壶', '瓶', '罐', '缸', '碗', '盘', '钵', '杯', '盏', '碟', '豆', '鬲', '鼎', '尊',
        '爵', '觚', '簋', '卣', '斝', '盉', '彝', '甗', '罍', '瓿', '匜', '盂', '觯', '觥',
        '奁', '盒', '匣', '函', '炉', '釜', '甑', '琮', '璧', '璜', '玦', '璋', '圭', '佩',
        '戈', '矛', '斧', '刀', '剑', '钺', '钟', '磬', '镜', '俑', '勺', '匕', '坠', '环']},
    '铜镜': '镜', '半瓦当': '瓦当', '圆瓦当': '瓦当', '陶俑': '俑', '瓷俑': '俑',
    '铜带钩': '带钩', '玉带钩': '带钩', '银带钩': '带钩', '玉佩': '佩',
}
TYPE_RE = re.compile('|'.join(re.escape(t) for t in sorted(TOKENS, key=len, reverse=True)))
PARENS = re.compile(r'\([^)]*\)|（[^）]*）')
DESCRIPTIVE_END = re.compile(r'纹|形|式|状|口|腹|肩|颈|足')
EXPLICIT_PREFIX = {'织锦', '刺绣', '绣绢', '画像石', '画像砖', '瓦当', '半瓦当', '圆瓦当',
                   '壁画', '藻井', '碑刻', '石刻', '漆器', '陶器', '瓷器', '铜器'}


def infer_type(record, document, motif_spans=()):
    """Return one name head with exact source offsets, or an unresolved reason."""
    a, b = record['titleSpan']
    text = document['text'][a:b]
    if re.search(r'\d+[.．、]', text):
        return None, 'multiple_captions_in_name'
    indices = [i for i, char in enumerate(text) if not char.isspace()]
    compact = ''.join(text[i] for i in indices)
    masked = list(compact)
    for match in PARENS.finditer(compact):
        masked[match.start():match.end()] = ' ' * len(match.group())
    clean = ''.join(masked)
    matches = []
    for match in TYPE_RE.finditer(clean):
        start, end = a+indices[match.start()], a+indices[match.end()-1]+1
        explicit_prefix = (match.group() in EXPLICIT_PREFIX and match.start() < 12
                           and '纹' not in clean[:match.start()])
        if not explicit_prefix and any(left <= start < right for left, right in motif_spans):
            continue
        # 盘口长颈壶 and 壶形纹 describe a shape, not an independent vessel.
        following = clean[match.end():]
        if DESCRIPTIVE_END.match(following):
            continue
        matches.append((match, start, end))
    if not matches:
        return None, 'no_explicit_carrier'
    last_motif = clean.rfind('纹')
    after = [row for row in matches if row[0].start() > last_motif]
    if last_motif >= 0 and after:
        matches = after
    # The final carrier head wins over preceding shape or decoration nouns.
    match, start, end = matches[-1]
    return {'label': TOKENS[match.group()], 'span': [start, end],
            'raw': document['text'][start:end], 'method': 'catalog_name_head'}, None


def enrich_types(graph, extraction_dir):
    import json
    entities = {e['id']: e for e in graph['entities']}
    seen = {s['recordId'] for s in graph['assertions'] if s['predicate'] == 'artifact_type'}
    added, skipped = [], []
    for page in graph['selection']:
        extraction = json.loads((extraction_dir/f'v1-p{page:04d}.json').read_text())
        doc = extraction['document']
        spans = {}
        for field in [*extraction.get('fields', []), *caption_fields(extraction)]:
            if field['kind'] == 'motif':
                spans.setdefault(field['recordId'], []).append(field['span'])
        for record in extraction['records']:
            subject = ident('entity', record['id'])
            if record['id'] in seen:
                continue
            if record['issues'] or subject not in entities:
                skipped.append({'recordId': record['id'], 'page': page, 'reason': 'record_unresolved'})
                continue
            inferred, reason = infer_type(record, doc, spans.get(record['id'], []))
            if inferred is None:
                skipped.append({'recordId': record['id'], 'page': page, 'label': record['label'], 'reason': reason})
                continue
            ev = local_evidence(doc, *inferred['span'])
            target = ident('entity', VERSION, record['id'], inferred['label'])
            entity = {'id': target, 'label': inferred['label'], 'kind': 'artifact_type',
                      'scope': 'source_mention', 'identityStatus': 'unresolved',
                      'aliases': list(dict.fromkeys([inferred['label'], inferred['raw']])),
                      'recordId': record['id'], 'description': record['text'], 'evidence': [ev]}
            graph['entities'].append(entity)
            entities[target] = entity
            statement = {'id': ident('statement', VERSION, record['id']), 'subject': subject,
                'recordId': record['id'], 'predicate': 'artifact_type', 'label': '器类',
                'object': {'kind': 'entity', 'id': target}, 'evidence': [ev],
                'origin': VERSION, 'status': 'candidate', 'reviewStatus': 'unreviewed',
                'qualifiers': [], 'issues': [],
                'binding': {'kind': 'catalog_name_head', 'recordId': record['id'],
                            'item': record['item'], 'raw': inferred['raw']}}
            graph['assertions'].append(statement)
            added.append(statement)
            seen.add(record['id'])
    report = {'version': VERSION, 'added': len(added), 'existing': len(seen)-len(added),
              'types': dict(Counter(entities[s['object']['id']]['label'] for s in added)),
              'skipped': skipped, 'ocrRerun': False, 'modelsRerun': False}
    graph['artifactTypeEnrichment'] = {k: v for k, v in report.items() if k != 'skipped'}
    graph['summary'].update(entities=len(graph['entities']), assertions=len(graph['assertions']))
    return report
