#!/usr/bin/env python3
"""Run PP-StructureV3 locally with explicitly cached model directories."""
import argparse
import concurrent.futures
import hashlib
import importlib.metadata
import multiprocessing
import os
import time
from pathlib import Path

from kg_v2.common import OUT, load, save, selected_pages, source_path
from kg_v2.images import layout_input_signature, ocr_image_file

MODELS = {'layout_detection': 'PP-DocLayout_plus-L', 'region_detection': 'PP-DocBlockLayout',
          'text_detection': 'PP-OCRv5_server_det', 'text_recognition': 'PP-OCRv5_server_rec'}
_PIPELINE = None
_MODEL_SIGNATURE = None


def init_worker(config, signature):
    global _PIPELINE, _MODEL_SIGNATURE
    os.environ.update(PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True', HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
                      HF_HUB_OFFLINE='1', TOKENIZERS_PARALLELISM='false')
    from paddleocr import PPStructureV3
    from paddlex.inference.pipelines.layout_parsing.pipeline_v2 import _LayoutParsingPipelineV2
    original_create = _LayoutParsingPipelineV2.create_model
    def create_enabled(instance, model_config, *positional, **kwargs):
        if model_config.get('module_name') == 'chart_recognition' and not instance.use_chart_recognition:
            return None
        return original_create(instance, model_config, *positional, **kwargs)
    _LayoutParsingPipelineV2.create_model = create_enabled
    _PIPELINE = PPStructureV3(**config)
    _MODEL_SIGNATURE = signature


def process_page(page):
    record = load(OUT / 'pages' / f'v1-p{page:04d}.json')
    input_signature = layout_input_signature(record)
    target = OUT / 'layout' / f'v1-p{page:04d}.json'
    previous = load(target) if target.exists() else None
    if previous and previous.get('inputSignature') == input_signature and previous['modelSignature'] == _MODEL_SIGNATURE:
        result = previous; cached = True
    else:
        tick = time.perf_counter()
        with ocr_image_file(source_path(), page, record['render_width']) as (image, _):
            image_hash = hashlib.sha256(image.read_bytes()).hexdigest()
            values = list(_PIPELINE.predict(str(image)))
        if len(values) != 1: raise ValueError('Expected exactly one page result')
        result = {'page': page, 'imageSha256': image_hash, 'inputSignature': input_signature, 'modelSignature': _MODEL_SIGNATURE,
                  'seconds': round(time.perf_counter() - tick, 3), 'raw': values[0].json['res']}
        save(target, result); cached = False
    return {'page': page, 'blocks': len(result['raw']['parsing_res_list']),
            'seconds': result.get('seconds', 0), 'cached': cached}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pages', type=int, nargs='+', default=selected_pages())
    parser.add_argument('--workers', type=int, default=2)
    args = parser.parse_args()
    if args.workers < 1: raise SystemExit('--workers must be at least 1')
    # Fail before loading four large models or starting page workers.
    import fitz
    from PIL import Image
    os.environ.update(PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True', HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
                      HF_HUB_OFFLINE='1', TOKENIZERS_PARALLELISM='false')
    models, hashes = {}, {}
    for role, name in MODELS.items():
        path = Path.home() / '.paddlex/official_models' / name
        if not (path / 'inference.pdiparams').exists():
            raise RuntimeError(f'Missing local model: {path}; prepare public model weights first')
        models[role + '_model_dir'] = str(path)
        hashes[name] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in path.iterdir()
                       if p.is_file() and p.suffix in {'.pdiparams', '.json', '.yml'}}
    config = {**models, 'device': 'cpu', 'use_doc_orientation_classify': False,
        'use_doc_unwarping': False, 'use_textline_orientation': False,
        'use_table_recognition': False, 'use_formula_recognition': False,
        'use_chart_recognition': False, 'use_seal_recognition': False,
        'text_det_limit_side_len': 1600, 'text_det_limit_type': 'max',
        'text_recognition_batch_size': 8, 'enable_mkldnn': True, 'cpu_threads': 4}
    signature = hashlib.sha256(repr((hashes, config)).encode()).hexdigest()
    started = time.perf_counter(); stats = []
    pending = []
    for page in args.pages:
        record = load(OUT / 'pages' / f'v1-p{page:04d}.json')
        input_signature = layout_input_signature(record)
        target = OUT / 'layout' / f'v1-p{page:04d}.json'
        previous = load(target) if target.exists() else None
        if previous and previous.get('inputSignature') == input_signature and previous['modelSignature'] == signature:
            stats.append({'page': page, 'blocks': len(previous['raw']['parsing_res_list']),
                          'seconds': previous.get('seconds', 0), 'cached': True})
        else:
            pending.append(page)
    if pending:
        if args.workers == 1:
            init_worker(config, signature)
            iterator = map(process_page, pending)
            for row in iterator:
                stats.append(row)
                print(f'PP-Structure {len(stats)}/{len(args.pages)}: page {row["page"]}, {row["blocks"]} blocks', flush=True)
        else:
            with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers,
                    mp_context=multiprocessing.get_context('spawn'), initializer=init_worker,
                    initargs=(config, signature)) as pool:
                futures = {pool.submit(process_page, page): page for page in pending}
                for future in concurrent.futures.as_completed(futures):
                    row = future.result(); stats.append(row)
                    print(f'PP-Structure {len(stats)}/{len(args.pages)}: page {row["page"]}, {row["blocks"]} blocks', flush=True)
    stats.sort(key=lambda row: args.pages.index(row['page']))
    save(OUT / 'layout-run.json', {'engine': 'PP-StructureV3', 'versions': {
        x: importlib.metadata.version(x) for x in ['paddleocr', 'paddlex', 'paddlepaddle']},
        'modelsSha256': hashes, 'settings': config, 'workers': args.workers, 'pages': stats,
        'wallSeconds': round(time.perf_counter() - started, 3), 'network': 'unshare -n',
        'compatibility': 'Skip eager Chart2Table initialization when use_chart_recognition=False in PaddleX 3.3.13',
        'disabledModules': ['table recognition', 'formula recognition', 'chart recognition', 'seal recognition']})


if __name__ == '__main__':
    main()
