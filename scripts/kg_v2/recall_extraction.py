"""Full-text, evidence-preserving UIE recall pass; no training or remote calls.

Document-wide value extraction and subject-conditioned extraction contribute a
union of candidates.  Model scores are screening scores, not measured accuracy.
Every decision (including unbound values) is retained in an audit file.
"""
from collections import Counter, defaultdict
import json
import re

from .common import ident, save
from .identity import normalize_name
from .records import local_evidence
from .text import token_windows
from .uie import UIE, MODEL_ID, REVISION

VERSION = 'uie-fulltext-recall-v1'
ENDPOINT_THRESHOLD = .35
FIELDS = {
    'technique': ('uses_technique', '工艺', ['工艺', '制作工艺', '装饰技法']),
    'composition': ('has_composition', '构图形式', ['构成形式', '构图形式', '排列方式']),
    'symbolism': ('interpreted_as', '象征意义', ['象征意义', '寓意', '涵义']),
    'belief': ('religious_context', '信仰语境', ['宗教']),
    'ritual': ('ritual_context', '礼仪语境', ['礼仪活动']),
}
GENERIC = {'纹样', '图案', '花纹', '装饰', '工艺', '技法', '构图', '构图形式', '形式',
           '象征', '象征意义', '寓意', '涵义', '宗教', '精神', '艺术', '思想', '这一时期', '当时',
           '非常明显', '明显', '浓重', '更加浓重', '有关', '多样', '较少', '较少见', '盛行',
           '精美', '精湛', '精细', '独特', '简洁', '熟练', '精良', '巧合', '新颖', '严工',
           '这方面', '该方面', '这些', '如此', '图案骨式', '骨式', '连续'}
NEGATIVE = re.compile(r'并非|不象征|不代表|不是[^。]*象征|与[^。]*无关')


def labels(kind, raw):
    """Normalize only a model-predicted span, after extracting its full wording."""
    text = normalize_name(raw).strip('“”‘’「」《》"\'，。；：:（）() \n')
    if not text or len(text) > 100 or text in GENERIC or re.search(r'\d|厘米|毫米|出土|收藏', text):
        return []
    if kind == 'technique':
        text = re.sub(r'(?:工艺|技法|技术|方法|手法|装饰)$', '', text) or text
        if (len(text) > 18 or '纹' in text or re.search(r'人形|裸体|菱形|几何形|花卉|佛像|菩萨|二方|四方|连续|对称|构图|组织|俯视|侧视', text)
                or text.endswith(('器', '壶', '盆', '镜', '盒', '罐', '钵', '碗', '瓮', '瓶', '豆', '杯', '铃', '哨', '盘', '饰', '物', '图', '车'))):
            return []
        if text in {'铜', '青铜', '金', '银', '玉', '陶', '彩陶', '瓷', '丝', '漆', '金丝'}:
            return []
        # A model's whole artifact name or stylistic adjective is not a process.
        # These are type checks on neural spans, never a source-text lookup.
        if (not re.fullmatch(r'[\u3400-\u9fff]+', text)
                or not re.search(r'绘|绣|织|刻|雕|印|染|缬|塑|制|髹|磨|刺|镂|描|涂|脱|筑|镶|嵌|剔|铸|贴|鎏|捻|夯|缂|错|錾|锤|揲|锻|焊|烧|釉|钉|轧|缝|缀', text)
                or not re.search(r'(?:绘|绣|织|锦|绮|刻|雕|印|染|缬|塑|制|漆|磨|光|刺|镂|空|孔|花|描|涂|脱|筑|金|银|嵌|剔|铸|法|画|绒|针|丝|错|錾|锤|揲|锻|焊|烧|釉|钉|轧|缝|缀)$', text)):
            return []
        tail = re.search(r'(?:[石玉骨木砖]雕|[石铜砖木]刻)$', text)
        if tail:
            text = tail.group()
    if kind == 'composition':
        text = re.sub(r'(?:纹样|纹)$', '', text)
        if not re.search(r'连续|对称|散点|放射|排列|构图|满地|适合|式|环形|组织|构成|交错|相错|相对|平行|单独|旋转|旋涡|旋卷|波状', text):
            return []
    if kind in {'symbolism', 'belief', 'ritual'}:
        text = re.sub(r'(?:之意|之含义|的含义|的象征)$', '', text)
        # Short labels are an output representation, never an extraction gate.
        if '的' in text and 1 < len(text.rsplit('的', 1)[1]) <= 10:
            text = text.rsplit('的', 1)[1]
        if text in GENERIC or text.endswith(('纹', '纹样', '图案')):
            return []
    result = []
    for part in re.split(r'[、，；]', text):
        part = part.strip('“”‘’"\' ，。；：')
        if 1 < len(part) <= 24 and part not in GENERIC:
            result.append(part)
    return list(dict.fromkeys(result))


def view(doc, start, end):
    """Rejoin Chinese OCR line wraps while retaining exact source offsets."""
    chars, offsets = [], []
    for index in range(start, end):
        char = doc['text'][index]
        if char.isspace() and index > start and index+1 < end:
            if re.match(r'[\u3400-\u9fff]', doc['text'][index-1]) and re.match(r'[\u3400-\u9fff]', doc['text'][index+1]):
                continue
        chars.append(char); offsets.append(index)
    return {'text': ''.join(chars), 'offsets': offsets, 'start': start, 'end': end, 'doc': doc}


def source_span(unit, span):
    return unit['offsets'][span['start']], unit['offsets'][span['end']-1]+1


class RecallExtractor:
    def __init__(self, directory, batch_size=32):
        import torch
        torch.set_num_threads(4)
        self.model = UIE(threshold=ENDPOINT_THRESHOLD)
        self.directory, self.batch_size = directory, batch_size
        directory.mkdir(parents=True, exist_ok=True)
        self.cache_path = directory/'model-cache.jsonl'
        self.cache = {}
        if self.cache_path.exists():
            for line in self.cache_path.read_text().splitlines():
                row = json.loads(line); self.cache[row['key']] = row['spans']
        self.audit, self.coverage = [], []

    def query(self, pairs, stage):
        keys = [ident(VERSION, REVISION, ENDPOINT_THRESHOLD, text, prompt) for text, prompt in pairs]
        pending = {key: pair for key, pair in zip(keys, pairs) if key not in self.cache}
        jobs = sorted(pending.items(), key=lambda item: len(item[1][0])+len(item[1][1]))
        with self.cache_path.open('a') as output:
            for offset in range(0, len(jobs), self.batch_size):
                batch = jobs[offset:offset+self.batch_size]
                answers = self.model.query_pairs([pair for _, pair in batch], self.batch_size)
                for (key, _), spans in zip(batch, answers):
                    self.cache[key] = spans
                    output.write(json.dumps({'key': key, 'spans': spans}, ensure_ascii=False)+'\n')
                output.flush()
                if offset % (self.batch_size*20) == 0 or offset+len(batch) == len(jobs):
                    status = {'state': 'extracting', 'stage': stage, 'completed': offset+len(batch), 'total': len(jobs)}
                    save(self.directory/'status.json', status); print(json.dumps(status), flush=True)
        return [self.cache[key] for key in keys]

    def context(self, volume, doc, a, b):
        records = [r for r in self.records[(volume, doc['page'])]
                   if r['span'][0] <= a < b <= r['span'][1]]
        # An actual artifact entity is required for record-level ownership.
        if len(records) == 1 and records[0]['id'] in self.artifacts[volume]:
            record = records[0]
            if len(self.model.tokenizer(record['text'], add_special_tokens=False)['input_ids']) < 220:
                return {**view(doc, *record['span']), 'volume': volume, 'record': record, 'scope': 'caption'}
        block = next((x for x in doc['blocks'] if x['start'] <= a and b <= x['end']), None)
        lo, hi = (block['start'], block['end']) if block else (0, len(doc['text']))
        text = doc['text']
        left = max([lo]+[text.rfind(mark, lo, a)+1 for mark in '。！？'])
        ends = [text.find(mark, b, hi) for mark in '。！？']
        right = min([hi]+[p+1 for p in ends if p >= 0])
        # Cross-sentence pronouns can refer to the immediately preceding sentence.
        previous = max([lo]+[text.rfind(mark, lo, max(lo, left-1))+1 for mark in '。！？'])
        if left-previous <= 95 and right-previous <= 240:
            left = previous
        # Long OCR blocks still get local, bounded contexts, never a silent drop.
        if right-left > 260:
            left, right = max(left, a-120), min(right, b+100)
        return {**view(doc, left, right), 'volume': volume, 'record': None, 'scope': 'prose'}

    def add_seed(self, seeds, unit, kind, span, prompt, route, subject=None):
        a, b = source_span(unit, span)
        kind_labels = labels(kind, span['text'])
        score_floor = .14 if kind in {'technique', 'composition'} else .18
        reason = 'candidate' if kind_labels and span['score'] >= score_floor else 'value_filter'
        self.audit.append({'volume': unit['volume'], 'page': unit['doc']['page'], 'kind': kind,
            'prompt': prompt, 'route': route, 'raw': span['text'], 'span': [a, b],
            'score': span['score'], 'decision': reason})
        if reason != 'candidate':
            return
        context = ({**unit, 'record': None, 'scope': 'prose'} if subject or route == 'sentence_first'
                   else self.context(unit['volume'], unit['doc'], a, b))
        for label in kind_labels:
            key = (unit['volume'], unit['doc']['page'], kind, label, a, b, context['start'], context['end'],
                   subject['label'] if subject else None)
            seed = {'unit': context, 'kind': kind, 'value': label, 'span': [a, b], 'score': span['score'],
                    'prompt': prompt, 'route': route, 'subject': subject}
            if key not in seeds or span['score'] > seeds[key]['score']:
                seeds[key] = seed

    def run(self, graphs):
        self.records, self.artifacts, self.known_motifs = defaultdict(list), {}, {}
        for volume, graph in enumerate(graphs, 1):
            self.artifacts[volume] = {e['recordId']: e for e in graph['entities'] if e['kind'] == 'artifact'}
            aliases = defaultdict(set)
            for entity in graph['entities']:
                label = normalize_name(entity['label'])
                if (entity['kind'] != 'motif' or not 1 < len(label) <= 12 or label in GENERIC
                        or re.search(r'[\d，。；的]|^少数|^一个|^这一', label)):
                    continue
                aliases[label].add(label)
                if label.endswith('纹') and len(label) > 2 and label[:-1] not in GENERIC:
                    aliases[label[:-1]].add(label)
            self.known_motifs[volume] = aliases
            for record in graph['records']:
                self.records[(volume, record['page'])].append(record)
        windows, subject_units, sentence_units = [], {}, {}
        for volume, graph in enumerate(graphs, 1):
            for doc in graph['documents']:
                if doc['engine'] != 'ppstructure':
                    continue
                views = token_windows(doc['text'], self.model.tokenizer, 200, 60)
                self.coverage.append({'volume': volume, 'page': doc['page'], 'characters': len(doc['text']),
                    'windows': len(views), 'state': 'queued' if views else 'empty_text'})
                for win in views:
                    windows.append({**view(doc, win['start'], win['end']), 'volume': volume})
                # Every prose paragraph supplies an independent subject-first path.
                for block in doc['blocks']:
                    if block['kind'] != 'text' or not re.search(r'[。！？]', block['text']):
                        continue
                    for win in token_windows(block['text'], self.model.tokenizer, 170, 45):
                        a, b = block['start']+win['start'], block['start']+win['end']
                        subject_units[(volume, doc['page'], a, b)] = {**view(doc, a, b), 'volume': volume}
                    for sentence in re.finditer(r'[^。！？]+[。！？]?', block['text']):
                        if not re.search(r'象征|寓意|涵义|含义|代表|取其|宗教|佛教|道教|构图|构成|排列|工艺|技法|制作|采用|雕|刻|绘|绣|织|印|染|缬|盘筑|磨', sentence.group()):
                            continue
                        for win in token_windows(sentence.group(), self.model.tokenizer, 180, 45):
                            a = block['start']+sentence.start()+win['start']
                            b = block['start']+sentence.start()+win['end']
                            sentence_units[(volume, doc['page'], a, b)] = {**view(doc, a, b), 'volume': volume}
                # Captions also get isolated views, keeping neighboring objects apart.
                for record in self.records[(volume, doc['page'])]:
                    for win in token_windows(record['text'], self.model.tokenizer, 200, 60):
                        a, b = record['span'][0]+win['start'], record['span'][0]+win['end']
                        windows.append({**view(doc, a, b), 'volume': volume})
        prompts = [(kind, prompt) for kind, (_, _, values) in FIELDS.items() for prompt in values]
        jobs = [(unit['text'], prompt) for unit in windows for _, prompt in prompts]
        answers = self.query(jobs, 'fulltext-values')
        seeds = {}
        for index, spans in enumerate(answers):
            unit, (kind, prompt) = windows[index//len(prompts)], prompts[index % len(prompts)]
            for span in spans:
                self.add_seed(seeds, unit, kind, span, prompt, 'value_first')
        # Isolated sentences recover rare terms diluted by longer page windows.
        # The complete page pass above still runs without a keyword gate.
        sentences = list(sentence_units.values())
        answers = self.query([(u['text'], p) for u in sentences for _, p in prompts], 'sentence-values')
        for index, spans in enumerate(answers):
            unit, (kind, prompt) = sentences[index//len(prompts)], prompts[index % len(prompts)]
            for span in spans:
                self.add_seed(seeds, unit, kind, span, prompt, 'sentence_first')
        # Independent subject route; a failed value-first query cannot gate it.
        units = list(subject_units.values())
        subjects = self.query([(u['text'], '纹样') for u in units], 'paragraph-subjects')
        direct_jobs, direct_owners = [], []
        for unit, spans in zip(units, subjects):
            for span in spans:
                subject = self.subject(unit, span)
                if subject is None or span['score'] < .3:
                    continue
                for kind, prompt in prompts:
                    direct_jobs.append((unit['text'], subject['label']+'的'+prompt))
                    direct_owners.append((unit, kind, prompt, subject))
        for owner, spans in zip(direct_owners, self.query(direct_jobs, 'subject-conditioned')):
            unit, kind, prompt, subject = owner
            for span in spans:
                self.add_seed(seeds, unit, kind, span, prompt, 'subject_first', subject)
        # Pair value-first results within their precise caption or sentence context.
        contexts = {}
        for seed in seeds.values():
            u = seed['unit']; key = u['volume'], u['doc']['page'], u['start'], u['end']
            contexts[key] = u
        context_list = list(contexts.values())
        symbolic_contexts = {(s['unit']['volume'], s['unit']['doc']['page'], s['unit']['start'], s['unit']['end'])
                             for s in seeds.values() if s['kind'] in {'symbolism', 'belief', 'ritual'}}
        meaning_contexts = {(s['unit']['volume'], s['unit']['doc']['page'], s['unit']['start'], s['unit']['end'])
                            for s in seeds.values() if s['kind'] == 'symbolism'}
        local_jobs = [(u, p) for u in context_list for p in
            (['纹样', '图案', '文物', '象征物', '植物'] if
             (u['volume'], u['doc']['page'], u['start'], u['end']) in symbolic_contexts else ['纹样', '图案', '文物'])]
        queries = [(u['text'], p) for u, p in local_jobs]
        answers = self.query(queries, 'local-subjects')
        subject_map = defaultdict(list)
        for index, spans in enumerate(answers):
            u, prompt = local_jobs[index]; key = u['volume'], u['doc']['page'], u['start'], u['end']
            for span in spans:
                subject = self.subject(u, span)
                if subject and span['score'] >= .25:
                    if prompt == '文物': subject['kind'] = 'concept'
                    subject_map[key].append(subject)
        # Reuse existing graph entities when the local NER query returned nothing.
        # Name alignment supplies only an anchor: the relation model must then
        # explicitly extract the value for that anchor before it can be accepted.
        for unit in context_list:
            key = unit['volume'], unit['doc']['page'], unit['start'], unit['end']
            if subject_map[key] or key not in meaning_contexts:
                continue
            aligned = []
            for alias, names in self.known_motifs[unit['volume']].items():
                for match in re.finditer(re.escape(alias), unit['text']):
                    span = source_span(unit, {'start': match.start(), 'end': match.end()})
                    aligned.append({'label': alias, 'kind': 'motif', 'span': span, 'score': 1.0,
                                    'anchorLabels': sorted(names), 'anchored': True})
            # A short name embedded in a longer aligned name is not another owner.
            subject_map[key] = [s for s in aligned if not any(t['span'][0] <= s['span'][0]
                and s['span'][1] <= t['span'][1] and len(t['label']) > len(s['label']) for t in aligned)]
        paired, check_jobs = [], []
        for seed in seeds.values():
            unit, kind = seed['unit'], seed['kind']
            if kind in {'technique', 'composition'} and unit['record']:
                subject = {'label': unit['record']['label'], 'kind': 'artifact',
                           'span': unit['record']['titleSpan'], 'score': 1.0}
                paired.append({**seed, 'subject': subject, 'binding': 'caption_scope', 'confirmed': True})
                check_jobs.append(None)
                continue
            key = unit['volume'], unit['doc']['page'], unit['start'], unit['end']
            candidates = [seed['subject']] if seed['subject'] else subject_map[key]
            if not candidates:
                self.audit.append({'volume': unit['volume'], 'page': unit['doc']['page'], 'kind': kind,
                    'value': seed['value'], 'span': seed['span'], 'decision': 'subject_unresolved'})
            seen = set()
            for subject in candidates:
                if subject.get('anchored') and kind != 'symbolism':
                    continue
                if subject['label'] == seed['value'] or subject['label'] in seen:
                    continue
                seen.add(subject['label'])
                paired.append({**seed, 'subject': subject, 'binding': 'source_concept',
                               'confirmed': seed['route'] == 'subject_first'})
                check_jobs.append((unit['text'], subject['label']+'的'+seed['prompt']))
        pending_checks = [job for job in check_jobs if job]
        confirmations = iter(self.query(pending_checks, 'relation-support'))
        records, assertions = {}, {}
        for pair, job in zip(paired, check_jobs):
            supported = pair['confirmed']
            if job:
                for span in next(confirmations):
                    a, b = source_span(pair['unit'], span)
                    if a < pair['span'][1] and b > pair['span'][0] and pair['value'] in labels(pair['kind'], span['text']):
                        supported = True
            decision = self.decide(pair, supported)
            self.audit.append({'volume': pair['unit']['volume'], 'page': pair['unit']['doc']['page'],
                'kind': pair['kind'], 'subject': pair['subject']['label'], 'value': pair['value'],
                'raw': pair['unit']['doc']['text'][slice(*pair['span'])], 'score': pair['score'],
                'route': pair['route'], 'relationSupported': supported, 'decision': decision})
            if decision != 'accepted':
                continue
            record = self.result(pair, supported)
            key = record['volumeNumber'], record['page'], record['kind'], normalize_name(record['subject']['label']), record['value']
            destination = assertions if pair['binding'] == 'caption_scope' else records
            if key not in destination or record['modelScore'] > destination[key]['modelScore']:
                destination[key] = record
        for page in self.coverage:
            if page['state'] == 'queued': page['state'] = 'processed'
        report = {'version': VERSION, 'pages': len(self.coverage), 'windows': len(windows),
            'proseWindows': len(units), 'sentenceWindows': len(sentences), 'valueCandidates': len(seeds), 'pairedCandidates': len(paired),
            'artifactRelations': len(assertions), 'conceptRelations': len(records),
            'artifactByKind': dict(Counter(r['kind'] for r in assertions.values())),
            'conceptByKind': dict(Counter(r['kind'] for r in records.values())),
            'decisions': dict(Counter(r['decision'] for r in self.audit)),
            'model': MODEL_ID, 'revision': REVISION, 'endpointThreshold': ENDPOINT_THRESHOLD,
            'fineTuning': False, 'ocrRerun': False, 'llmCalls': 0, 'semanticAccuracy': 'not_independently_measured'}
        save(self.directory/'coverage.json', self.coverage)
        save(self.directory/'decisions.json', self.audit)
        return list(assertions.values()), list(records.values()), report

    @staticmethod
    def subject(unit, span):
        label = normalize_name(span['text']).strip('“”‘’"\'，。；： ')
        if not 1 < len(label) <= 32 or label in GENERIC or re.search(r'[，。；\d]', label):
            return None
        return {'label': label, 'kind': 'motif', 'span': source_span(unit, span), 'score': span['score']}

    @staticmethod
    def decide(pair, supported):
        unit, subject = pair['unit'], pair['subject']
        text = unit['text']
        if NEGATIVE.search(text):
            return 'negated_context'
        if pair['binding'] == 'caption_scope':
            return 'accepted'
        if not RecallExtractor.local_binding(pair):
            return 'nonlocal_binding'
        if pair['kind'] == 'symbolism':
            a, b = pair['span']; doc = unit['doc']['text']
            sentence_start = max([unit['start']]+[doc.rfind(mark, unit['start'], a)+1 for mark in '。！？；'])
            ends = [doc.find(mark, b, unit['end']) for mark in '。！？；']
            sentence_end = min([unit['end']]+[p+1 for p in ends if p >= 0])
            local = doc[max(sentence_start, a-24):min(sentence_end, b+24)]
            if pair['value'] == pair['subject']['label'].removesuffix('纹'):
                return 'reflexive_meaning'
            if not re.search(r'象征(?!性)|寓意|涵[义意]|含义|取其|代表|隐喻|之意|意味', local):
                return 'symbolic_relation_not_explicit'
        if pair['subject']['label'].endswith(('墓', '墓群', '时期', '地区')):
            return 'subject_type'
        if subject.get('anchored') and not supported:
            return 'anchored_relation_unconfirmed'
        # Direct subject-specific model extraction supplies the binding itself.
        if supported:
            return 'accepted'
        # Strong local spans may survive without a second model success, provided
        # they occur in one clause with an explicit relational expression.
        a, b = sorted([subject['span'][0], pair['span'][0]])
        between = unit['doc']['text'][a:b]
        cues = {'symbolism': r'象征|寓意|涵[义意]|取其|代表|意味', 'belief': r'佛教|道教|宗教|信仰',
                'ritual': r'祭祀|祭礼|礼仪', 'technique': r'采用|运用|使用|制作|制成|技法|工艺',
                'composition': r'构[图成]|排列|组成|组织|布局'}
        if (pair['score'] >= .32 and subject['score'] >= .45 and not re.search(r'[。！？]', between)
                and re.search(cues[pair['kind']], text)):
            return 'accepted'
        return 'binding_unresolved'

    @staticmethod
    def local_binding(pair):
        """A subject-conditioned query must still have a local source binding."""
        unit, subject = pair['unit'], pair['subject']
        text = unit['doc']['text']; a, b = pair['span']
        start = max([unit['start']]+[text.rfind(mark, unit['start'], a)+1 for mark in '。！？；'])
        ends = [text.find(mark, b, unit['end']) for mark in '。！？；']
        stop = min([unit['end']]+[p+1 for p in ends if p >= 0])
        stem = subject['label'][:-1] if subject['label'].endswith('纹') else subject['label']
        sentence = normalize_name(text[start:stop])
        if normalize_name(stem) not in sentence:
            return bool(re.match(r'\s*(?:它|其|这种|这一|这些|该|其中|针法|构成)', text[start:stop]))
        # Comma-separated clauses may introduce a different explicit subject.
        clause = max([start]+[text.rfind(mark, start, a)+1 for mark in '，,'])
        clause_ends = [text.find(mark, b, stop) for mark in '，,']
        clause_stop = min([stop]+[p for p in clause_ends if p >= 0])
        tail = normalize_name(text[clause:clause_stop])
        if normalize_name(stem) in tail:
            return True
        return bool(re.match(r'\s*(?:(?:可能|大概|或许|也许|似乎|往往|通常|大多|一般|就是|就|则|也|常|乃|即|仍|更|可|应当))*'
            r'(?:象征|寓意|含义|涵义|取其|表示|代表|隐喻|具有|是|为|属于|受|与|多|采用|以|用|作|既|又|以及|和|及|这|其|它|均|都)', text[clause:stop]))

    @staticmethod
    def result(pair, supported):
        unit, subject, kind = pair['unit'], pair['subject'], pair['kind']
        record = unit['record'] if pair['binding'] == 'caption_scope' else None
        key = unit['volume'], unit['doc']['page'], kind, subject['label'], pair['value'], record['id'] if record else ''
        return {'id': ident('recall', VERSION, *key), 'kind': kind, 'relationLabel': FIELDS[kind][1],
            'predicate': FIELDS[kind][0], 'subject': {'label': subject['label'], 'kind': subject['kind']},
            'value': pair['value'], 'page': unit['doc']['page'], 'volumeNumber': unit['volume'],
            'sourceName': unit['doc']['source'], 'text': unit['doc']['text'][unit['start']:unit['end']],
            'evidence': [local_evidence(unit['doc'], unit['start'], unit['end'])],
            'subjectEvidence': local_evidence(unit['doc'], *subject['span']),
            'valueEvidence': local_evidence(unit['doc'], *pair['span']),
            'recordId': record['id'] if record else None, 'scope': pair['binding'],
            'model': MODEL_ID, 'revision': REVISION, 'modelScore': min(pair['score'], subject['score']),
            'extractionMethod': 'local_uie', 'route': pair['route'], 'relationSupported': supported,
            **({'subjectRecognition': {'method': 'existing_entity_anchor', 'labels': subject['anchorLabels']}}
               if subject.get('anchored') else {}),
            'origin': VERSION, 'status': 'candidate', 'reviewStatus': 'unreviewed'}
