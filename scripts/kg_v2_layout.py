#!/usr/bin/env python3
"""Run PP-StructureV3 locally with explicitly cached model directories."""
import argparse
import hashlib
import importlib.metadata
import os
import time
from pathlib import Path

from kg_v2.common import OUT, load, save, selected_pages

MODELS = {'layout_detection': 'PP-DocLayout_plus-L', 'region_detection': 'PP-DocBlockLayout',
          'text_detection': 'PP-OCRv5_server_det', 'text_recognition': 'PP-OCRv5_server_rec'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pages', type=int, nargs='+', default=selected_pages())
    args = parser.parse_args()
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
    pipeline, stats, started = None, [], time.perf_counter()
    for page in args.pages:
        image = OUT / f'images/v1-p{page:04d}.png'
        image_hash = hashlib.sha256(image.read_bytes()).hexdigest()
        target = OUT / 'layout' / f'v1-p{page:04d}.json'
        previous = load(target) if target.exists() else None
        if previous and previous['imageSha256'] == image_hash and previous['modelSignature'] == signature:
            result = previous
        else:
            if pipeline is None:
                from paddleocr import PPStructureV3
                # PaddleX 3.3.13 eagerly loads Chart2Table even when disabled.
                # Honor the disabled flag locally; no weights or predictions change.
                from paddlex.inference.pipelines.layout_parsing.pipeline_v2 import _LayoutParsingPipelineV2
                original_create = _LayoutParsingPipelineV2.create_model
                def create_enabled(instance, model_config, *positional, **kwargs):
                    if model_config.get('module_name') == 'chart_recognition' and not instance.use_chart_recognition:
                        return None
                    return original_create(instance, model_config, *positional, **kwargs)
                _LayoutParsingPipelineV2.create_model = create_enabled
                pipeline = PPStructureV3(**config)
            tick = time.perf_counter()
            values = list(pipeline.predict(str(image)))
            if len(values) != 1:
                raise ValueError('Expected exactly one page result')
            raw = values[0].json['res']
            result = {'page': page, 'imageSha256': image_hash, 'modelSignature': signature,
                      'seconds': round(time.perf_counter() - tick, 3), 'raw': raw}
            save(target, result)
        stats.append({'page': page, 'blocks': len(result['raw']['parsing_res_list']),
                      'seconds': result['seconds'], 'cached': previous is result})
        print(f'PP-Structure {len(stats)}/{len(args.pages)}: page {page}, {stats[-1]["blocks"]} blocks', flush=True)
    save(OUT / 'layout-run.json', {'engine': 'PP-StructureV3', 'versions': {
        x: importlib.metadata.version(x) for x in ['paddleocr', 'paddlex', 'paddlepaddle']},
        'modelsSha256': hashes, 'settings': config, 'pages': stats,
        'wallSeconds': round(time.perf_counter() - started, 3), 'network': 'unshare -n',
        'compatibility': 'Skip eager Chart2Table initialization when use_chart_recognition=False in PaddleX 3.3.13',
        'disabledModules': ['table recognition', 'formula recognition', 'chart recognition', 'seal recognition']})


if __name__ == '__main__':
    main()
