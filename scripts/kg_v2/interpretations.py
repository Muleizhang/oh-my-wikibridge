"""Local UIE extraction of short symbolic labels with exact textual provenance."""
from collections import Counter
import json
import re

from .common import ident, save
from .identity import normalize_name
from .records import local_evidence
from .text import token_windows
from .uie import UIE, MODEL_ID, REVISION

VERSION = 'uie-interpretations-v1'
SEEDS = {'象征意义': 'symbolism', '寓意': 'symbolism', '宗教': 'belief', '礼仪活动': 'ritual'}
RELATION_PROMPTS = {'symbolism': ['象征意义', '寓意'], 'belief': ['宗教背景'], 'ritual': ['礼仪活动']}
LABELS = {'symbolism': '象征意义', 'belief': '信仰语境', 'ritual': '礼仪语境'}
GENERIC = {'象征', '象征意义', '寓意', '含义', '纹样', '花纹', '装饰', '宗教', '宗教含义', '思想', '艺术', '精神'}


def short_label(text):
    value = normalize_name(text).strip('“”‘’「」《》"\'，。；：:（）() ')
    value = re.sub(r'(?:之意|之含义|的含义|的象征)$', '', value)
    if '的' in value:
        tail = value.rsplit('的', 1)[1]
        if 1 < len(tail) <= 8:
            value = tail
    if value in GENERIC or not 1 < len(value) <= 12 or re.search(r'[\d，。；：、]|代表性|象征性', value):
        return None
    return value


def sentence_context(doc, start, end):
    text = doc['text']
    containing = next((i for i, block in enumerate(doc['blocks']) if block['start'] <= start < block['end']), None)
    block_start, block_end = 0, len(text)
    if containing is not None:
        block = doc['blocks'][containing]
        block_start, block_end = block['start'], block['end']
        if block['kind'] == 'ocr_line':
            cursor = containing
            while cursor > 0:
                previous = doc['blocks'][cursor-1]
                if previous['kind'] != 'ocr_line' or re.search(r'出土|收藏|厘米|^\s*\d+[.．、]', previous['text']):
                    break
                block_start = previous['start']; cursor -= 1
                if '。' in previous['text']:
                    break
            cursor = containing
            while cursor+1 < len(doc['blocks']) and doc['blocks'][cursor+1]['kind'] == 'ocr_line':
                block_end = doc['blocks'][cursor+1]['end']; cursor += 1
                if '。' in doc['blocks'][cursor]['text']:
                    break
    left = max(text.rfind('。', 0, start), text.rfind('！', 0, start), text.rfind('？', 0, start))+1
    left = max(left, block_start)
    stops = [text.find(mark, end) for mark in ['。', '！', '？']]
    right = min(block_end, min((p+1 for p in stops if p >= 0), default=len(text)))
    # One previous sentence can contain the explicit subject/cultural context.
    previous = max(text.rfind('。', 0, max(0, left-1)), text.rfind('！', 0, max(0, left-1)),
                   text.rfind('？', 0, max(0, left-1)))+1
    previous = max(previous, start-190, block_start)
    right = min(right, previous+360)
    if not previous <= start < end <= right:
        previous, right = max(0, start-130), min(len(text), end+110)
    return previous, right, left


class Extractor:
    def __init__(self, directory, batch_size=32):
        import torch
        torch.set_num_threads(4)
        self.model = UIE()
        self.directory, self.batch_size = directory, batch_size
        directory.mkdir(parents=True, exist_ok=True)
        self.cache_path = directory/'uie-cache.jsonl'
        self.cache = {}
        if self.cache_path.exists():
            for line in self.cache_path.read_text().splitlines():
                entry = json.loads(line)
                self.cache[entry['key']] = entry['spans']

    def query(self, pairs, stage):
        keys = [ident('uie-meaning', VERSION, REVISION, text, prompt) for text, prompt in pairs]
        pending = {key: pair for key, pair in zip(keys, pairs) if key not in self.cache}
        jobs = sorted(pending.items(), key=lambda item: len(item[1][0])+len(item[1][1]))
        with self.cache_path.open('a') as output:
            for offset in range(0, len(jobs), self.batch_size):
                batch = jobs[offset:offset+self.batch_size]
                results = self.model.query_pairs([pair for _, pair in batch], self.batch_size)
                for (key, _), spans in zip(batch, results):
                    self.cache[key] = spans
                    output.write(json.dumps({'key': key, 'spans': spans}, ensure_ascii=False)+'\n')
                output.flush()
                if offset % (self.batch_size*20) == 0:
                    status = {'state': 'extracting', 'stage': stage, 'completed': offset+len(batch), 'total': len(jobs)}
                    save(self.directory/'status.json', status)
                    print(json.dumps(status), flush=True)
        return [self.cache[key] for key in keys]

    def run(self, graphs):
        windows = []
        for volume, graph in enumerate(graphs, 1):
            for doc in graph['documents']:
                if doc['engine'] != 'ppstructure':
                    continue
                for win in token_windows(doc['text'], self.model.tokenizer, 200, 60):
                    windows.append({'volume': volume, 'doc': doc, **win})
        prompts = list(SEEDS)
        answers = self.query([(win['text'], prompt) for win in windows for prompt in prompts], 'meanings')
        seeds = {}
        for index, spans in enumerate(answers):
            win = windows[index//len(prompts)]
            kind = SEEDS[prompts[index % len(prompts)]]
            for span in spans:
                if span['score'] < (.35 if kind == 'belief' else .4):
                    continue
                value = short_label(span['text'])
                if value is None:
                    continue
                start, end = win['start']+span['start'], win['start']+span['end']
                key = (win['volume'], win['doc']['page'], kind, start, end)
                if key not in seeds or span['score'] > seeds[key]['score']:
                    left, right, sentence_start = sentence_context(win['doc'], start, end)
                    # A short heading may identify the subject of the next sentence.
                    focus_start = left if sentence_start-left <= 24 else sentence_start
                    seeds[key] = {'volume': win['volume'], 'doc': win['doc'], 'kind': kind,
                        'value': value, 'valueSpan': [start, end], 'score': span['score'],
                        'start': left, 'end': right, 'sentenceStart': sentence_start,
                        'focusStart': focus_start, 'focusText': win['doc']['text'][focus_start:right],
                        'text': win['doc']['text'][left:right]}
        seeds = list(seeds.values())
        print(json.dumps({'windows': len(windows), 'seedValues': len(seeds)}), flush=True)
        subject_prompts = ['纹样', '象征物', '图案']
        subjects = self.query([(seed['focusText'], prompt) for seed in seeds for prompt in subject_prompts], 'subjects')
        candidates = {}
        for index, spans in enumerate(subjects):
            seed = seeds[index//len(subject_prompts)]
            for span in spans:
                if span['score'] < .35:
                    continue
                value = normalize_name(span['text']).strip('“”‘’「」"\'，。；： ')
                if not 1 < len(value) <= 28 or value in GENERIC or value == seed['value']:
                    continue
                a, b = seed['focusStart']+span['start'], seed['focusStart']+span['end']
                key = seed['volume'], seed['doc']['page'], seed['kind'], value, seed['value'], *seed['valueSpan']
                candidate = {**seed, 'subject': value, 'subjectSpan': [a, b], 'subjectScore': span['score'],
                             'subjectKind': 'concept' if subject_prompts[index % 3] == '象征物' else 'motif'}
                if key not in candidates or span['score'] > candidates[key]['subjectScore']:
                    candidates[key] = candidate
        candidates = list(candidates.values())
        checks, owners = [], []
        for index, candidate in enumerate(candidates):
            for prompt in RELATION_PROMPTS[candidate['kind']]:
                checks.append((candidate['focusText'], candidate['subject']+'的'+prompt))
                owners.append(index)
        confirmations = self.query(checks, 'relations')
        accepted = {}
        for index, spans in enumerate(confirmations):
            candidate = candidates[owners[index]]
            for span in spans:
                if span['score'] < .35 or short_label(span['text']) != candidate['value']:
                    continue
                a, b = candidate['focusStart']+span['start'], candidate['focusStart']+span['end']
                if not (a < candidate['valueSpan'][1] and b > candidate['valueSpan'][0]):
                    continue
                doc = candidate['doc']
                if re.search(r'并非|不象征|不代表|不是[^。]*象征|与[^。]*无关', candidate['focusText']):
                    continue
                key = (candidate['volume'], doc['page'], candidate['kind'], candidate['subject'], candidate['value'])
                record_id = ident('interpretation', VERSION, *key)
                record = {'id': record_id, 'kind': candidate['kind'], 'relationLabel': LABELS[candidate['kind']],
                    'subject': {'label': candidate['subject'], 'kind': candidate['subjectKind']},
                    'value': candidate['value'], 'page': doc['page'], 'volumeNumber': candidate['volume'],
                    'sourceName': doc['source'], 'text': candidate['text'],
                    'evidence': [local_evidence(doc, candidate['start'], candidate['end'])],
                    'subjectEvidence': local_evidence(doc, *candidate['subjectSpan']),
                    'valueEvidence': local_evidence(doc, *candidate['valueSpan']),
                    'model': MODEL_ID, 'revision': REVISION, 'extractionMethod': 'local_uie',
                    'modelScore': min(candidate['score'], candidate['subjectScore'], span['score']),
                    'origin': VERSION, 'status': 'candidate', 'reviewStatus': 'unreviewed'}
                if key not in accepted or record['modelScore'] > accepted[key]['modelScore']:
                    accepted[key] = record
        records = list(accepted.values())
        report = {'version': VERSION, 'windows': len(windows), 'seedValues': len(seeds),
                  'relationCandidates': len(candidates), 'accepted': len(records),
                  'byKind': dict(Counter(record['kind'] for record in records)),
                  'byVolume': dict(Counter(record['volumeNumber'] for record in records)),
                  'model': MODEL_ID, 'revision': REVISION, 'ocrRerun': False, 'llmCalls': 0}
        return records, report
