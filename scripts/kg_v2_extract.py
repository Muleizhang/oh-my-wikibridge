#!/usr/bin/env python3
"""Extract caption fields and open prose candidates from structured OCR locally."""
import hashlib
import json
import os
import time

from kg_v2.common import OUT, ROOT, load, save, selected_pages
from kg_v2.documents import caption_records, document_from_structure, document_from_tesseract


def main():
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1')
    import torch
    from kg_v2.uie import UIE
    from kg_v2.text import token_windows
    from kg_v2.ltp import LocalLTP
    from kg_v2.templates import TemplateExtractor
    from kg_v2.text import windows
    torch.set_num_threads(4)
    uie = ltp = None
    code_hash = hashlib.sha256(b''.join((ROOT / 'scripts' / name).read_bytes() for name in
        ['kg_v2_extract.py', 'kg_v2/documents.py', 'kg_v2/text.py', 'kg_v2/uie.py', 'kg_v2/ltp.py', 'kg_v2/templates.py'])).hexdigest()
    started = time.perf_counter(); stats = []
    prompts = ['纹样', '时代', '出土地点', '收藏单位', '材质', '制作工艺']
    types = ['motif', 'period', 'place', 'organization', 'material', 'technique']
    pages = selected_pages()
    for page in pages:
        old = load(OUT / f'pages/v1-p{page:04d}.json')
        structure = load(OUT / f'layout/v1-p{page:04d}.json')
        document = document_from_structure(structure, old)
        baseline = document_from_tesseract(old); baseline['pageKind'] = document['pageKind']
        records = caption_records(document)
        signature = hashlib.sha256((document['text'] + code_hash + json.dumps(old['source_signature']) + old['source']).encode()).hexdigest()
        target = OUT / f'extractions/v1-p{page:04d}.json'
        previous = load(target) if target.exists() else None
        if previous and previous['signature'] == signature:
            result = previous
        else:
            tick = time.perf_counter(); fields = []; prose = []
            if records and uie is None:
                uie = UIE()
            for record in records:
                # No NER gate: the layout record itself supplies the subject scope.
                for win in token_windows(record['text'], uie.tokenizer, 192, 32):
                    answers = uie.query(win['text'], prompts)
                    for prompt, kind, values in zip(prompts, types, answers):
                        for value in values:
                            fields.append({'recordId': record['id'], 'field': prompt, 'kind': kind,
                                'text': value['text'], 'span': [record['span'][0] + win['start'] + value['start'],
                                                              record['span'][0] + win['start'] + value['end']],
                                'modelScore': value['score']})
            if document['pageKind'] == 'prose':
                if ltp is None:
                    ltp = LocalLTP()
                for block in document['blocks']:
                    if block['kind'] not in {'text', 'paragraph_title', 'reference_content'} or len(block['text']) < 6:
                        continue
                    for start, end in windows(block['text']):
                        text = block['text'][start:end]
                        if len(text.strip()) < 4:
                            continue
                        parsed = ltp.predict(text)
                        templates = TemplateExtractor(text, parsed['raw']).run()
                        prose.append({'blockId': block['id'], 'start': block['start'] + start,
                            'end': block['start'] + end, 'text': text,
                            'paragraphContext': block['text'], 'facts': templates['facts'],
                            'frames': parsed['events'] + templates['events'], 'parse': parsed['raw']})
            result = {'page': page, 'signature': signature, 'document': document, 'baselineDocument': baseline,
                'records': records, 'baselineRecords': caption_records(baseline), 'fields': fields,
                'prose': prose, 'seconds': round(time.perf_counter() - tick, 3),
                'models': {'uie': 'Casually/uie-base', 'ltp': 'LTP/small'},
                'domainFinetuned': False, 'semanticValidation': 'pending_independent_annotation'}
            save(target, result)
        stats.append({'page': page, 'records': len(result['records']), 'fields': len(result['fields']),
                      'proseWindows': len(result['prose']), 'seconds': result['seconds'], 'cached': previous is result})
        print(f'Typed extraction {len(stats)}/{len(pages)}: page {page}, {len(result["records"])} records', flush=True)
    save(OUT / 'extraction-run.json', {'pages': stats, 'wallSeconds': round(time.perf_counter() - started, 3),
        'codeSha256': code_hash, 'network': 'unshare -n', 'domainFinetuned': False})


if __name__ == '__main__':
    main()
