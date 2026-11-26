"""Pinned offline UIE + GLiNER batch extraction. Every output is a neural span."""
import gc
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from .common import ident, save
from .models import model_spec

os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', TOKENIZERS_PARALLELISM='false')
UIE_FIELDS = {'出土地点': 'excavated_at', '收藏单位': 'held_by',
              '文化名称': 'belongs_to_culture', '装饰部位': 'decorated_part'}
GLINER_FIELDS = {'manufacturing technique': 'uses_technique', 'archaeological culture': 'belongs_to_culture',
                 'pattern composition': 'has_composition', 'decorated part': 'decorated_part',
                 'decorative role': 'decoration_role', 'excavation site': 'excavated_at', 'museum': 'held_by'}


def extract(jobs, directory, batch_size=16):
    import torch
    torch.set_num_threads(4)
    cache_file = directory/'model-spans-v2.jsonl'
    cache = {}
    if cache_file.exists():
        for line in cache_file.read_text().splitlines():
            row = json.loads(line)
            cache[row['key']] = row['predictions']
    texts = sorted({job['text'] for _, job in jobs}, key=len)
    for role in ['uie', 'gliner']:
        spec = model_spec(role)
        fields = UIE_FIELDS if role == 'uie' else GLINER_FIELDS
        key_for = lambda text: ident('neural-dimensions', role, spec['revision'], list(fields), text)
        pending = [text for text in texts if key_for(text) not in cache]
        if pending:
            if role == 'uie':
                from .uie import UIE
                model = UIE()
            else:
                from gliner import GLiNER
                from gliner.data_processing.tokenizer import WordsSplitter
                # GLiNER otherwise looks up its tokenizer and encoder config by Hub name.
                weights = Path(spec['path'])
                config = json.loads((weights/'gliner_config.json').read_text())
                config['model_name'] = model_spec('gliner_encoder')['path']
                with TemporaryDirectory() as model_directory:
                    local = Path(model_directory)
                    (local/'gliner_config.json').write_text(json.dumps(config))
                    (local/'model.safetensors').symlink_to(weights/'model.safetensors')
                    model = GLiNER.from_pretrained(str(local), local_files_only=True)
                model = model.to('cuda' if torch.cuda.is_available() else 'cpu').eval()
                model.data_processor.words_splitter = WordsSplitter('jieba')
            print(json.dumps({'model': spec['model'], 'uncachedRecords': len(pending)}, ensure_ascii=False), flush=True)
            with cache_file.open('a') as output:
                for offset in range(0, len(pending), batch_size):
                    batch = pending[offset:offset+batch_size]
                    if role == 'uie':
                        pairs = [(text, prompt) for text in batch for prompt in fields]
                        answers = model.query_pairs(pairs, batch_size)
                        groups = [[] for _ in batch]
                        for index, spans in enumerate(answers):
                            field = list(fields)[index % len(fields)]
                            threshold = .3 if field == '文化名称' else .4
                            for span in spans:
                                if span['score'] >= threshold:
                                    groups[index // len(fields)].append({**span, 'predicate': fields[field]})
                    else:
                        with torch.inference_mode():
                            answers = model.batch_predict_entities(batch, list(fields), threshold=.55,
                                                                   flat_ner=False, multi_label=False)
                        groups = [[{**span, 'predicate': fields[span['label']]} for span in spans] for spans in answers]
                    for text, spans in zip(batch, groups):
                        predictions = [{**span, 'method': 'local_'+role, 'model': spec['model'],
                                        'revision': spec['revision']} for span in spans]
                        key = key_for(text)
                        cache[key] = predictions
                        output.write(json.dumps({'key': key, 'predictions': predictions}, ensure_ascii=False)+'\n')
                    output.flush()
                    if offset % (batch_size*20) == 0:
                        status = {'state': 'extracting', 'model': role, 'completed': min(offset+len(batch), len(pending)),
                                  'total': len(pending)}
                        save(directory/'status.json', status)
                        print(json.dumps(status), flush=True)
            del model
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
    # Consolidate nested model mentions before writing; keep distinct source spans.
    specs = {role: model_spec(role) for role in ['uie', 'gliner']}
    for enricher, job in jobs:
        predictions = []
        for role, fields in [('uie', UIE_FIELDS), ('gliner', GLINER_FIELDS)]:
            key = ident('neural-dimensions', role, specs[role]['revision'], list(fields), job['text'])
            predictions.extend(cache[key])
        for index, prediction in enumerate(predictions):
            if any(other['predicate'] == prediction['predicate']
                   and other['start'] <= prediction['start'] and prediction['end'] <= other['end']
                   and (other['end']-other['start'] > prediction['end']-prediction['start']
                        or (other['start'] == prediction['start'] and other['end'] == prediction['end'] and j < index))
                   for j, other in enumerate(predictions)):
                continue
            enricher.add_prediction(job, prediction)
