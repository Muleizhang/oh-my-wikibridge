#!/usr/bin/env python3
"""Resume offline plate pre-annotation across the three cached volumes."""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time

from kg_v2.common import ROOT, save
from kg_v2_annotate_plates import generate, weight_digest


def now():
    return datetime.now(timezone.utc).isoformat()


def run_page(task):
    import cv2
    cv2.setNumThreads(1)
    root = Path(task['root'])
    page = task['page']
    stem = f'v1-p{page:04d}'
    output = Path(task['output'])
    result_path = output / 'candidate-annotations.json'
    image = next((root/'images'/f'{stem}.source{s}' for s in ('.jpg', '.png', '.jpeg')
                  if (root/'images'/f'{stem}.source{s}').is_file()), None)
    if image is None:
        raise FileNotFoundError(f'Missing original page image: {root}/{stem}')
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    input_signature = hashlib.sha256(task['signature'].encode()
        + (root/'layout'/f'{stem}.json').read_bytes()
        + (root/'extractions'/f'{stem}.json').read_bytes()).hexdigest()
    if result_path.exists():
        previous = json.loads(result_path.read_text())
        if previous.get('inputSignature') == input_signature and previous.get('imageSha256') == digest:
            return {'volume': task['volume'], 'page': page, **previous['summary'],
                    'issues': previous['issues'], 'cached': True}
    result = generate(image, root/'layout'/f'{stem}.json', root/'extractions'/f'{stem}.json',
                      output, task['model'])
    result['inputSignature'] = input_signature
    save(result_path, result)
    return {'volume': task['volume'], 'page': page, **result['summary'],
            'issues': result['issues'], 'cached': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'data/local-kg/merged/site/annotations')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--pages', type=int, nargs='+')
    parser.add_argument('--model-dir', type=Path, default=Path.home()/'.paddlex/official_models/PP-OCRv5_server_rec')
    args = parser.parse_args()
    if args.workers < 1:
        parser.error('--workers must be positive')
    if not (args.model_dir/'inference.pdiparams').is_file():
        parser.error('Local OCR model is missing')
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ.update(PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True', HF_HUB_OFFLINE='1',
                      HF_HUB_DISABLE_IMPLICIT_TOKEN='1', TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS='4')
    # Changes to detection, OCR, grouping or preview invalidate resumable outputs.
    signature = hashlib.sha256(Path(__file__).with_name('kg_v2_annotate_plates.py').read_bytes()
                               + Path(__file__).with_name('kg_v2').joinpath('plate_regions.py').read_bytes()
                               + Path(__file__).with_name('plate_annotation_review.html').read_bytes()
                               + weight_digest(str(args.model_dir/'inference.pdiparams')).encode()).hexdigest()
    tasks = []
    for volume, root in [(1, ROOT/'data/local-kg'), (2, ROOT/'data/local-kg/vol2'),
                         (3, ROOT/'data/local-kg/vol3')]:
        for extraction in sorted((root/'extractions').glob('v1-p*.json')):
            page = int(extraction.stem.split('-p')[1])
            if args.pages is not None and page not in args.pages:
                continue
            tasks.append({'volume': volume, 'root': str(root), 'page': page,
                          'output': str(args.output/f'vol{volume}'/f'p{page:04d}'),
                          'model': str(args.model_dir.resolve()), 'signature': signature})
    tasks.sort(key=lambda task: (task['page'], task['volume']))
    (args.output/'index.html').write_text(Path(__file__).with_name('plate_annotation_batch.html').read_text())
    state = {'status': 'running', 'startedAt': now(), 'updatedAt': now(), 'total': len(tasks),
             'completed': 0, 'failed': 0, 'workers': args.workers, 'regions': 0, 'boundRegions': 0,
             'pagesWithIssues': 0, 'llmUsed': False, 'graphModified': False, 'pages': []}
    save(args.output/'status.json', state)
    print(f'Starting {len(tasks)} pages with {args.workers} workers; local OCR only', flush=True)
    tick = time.perf_counter()
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers,
                mp_context=multiprocessing.get_context('spawn')) as pool:
            futures = {pool.submit(run_page, task): task for task in tasks}
            for future in concurrent.futures.as_completed(futures):
                task = futures[future]
                try:
                    row = future.result()
                    row['status'] = 'needs_review' if row['issues'] else 'candidate'
                    row['url'] = f'vol{row["volume"]}/p{row["page"]:04d}/index.html'
                    state['completed'] += 1
                    state['regions'] += row['regions']
                    state['boundRegions'] += row['boundRegions']
                    state['pagesWithIssues'] += bool(row['issues'])
                except Exception as exc:
                    row = {'volume': task['volume'], 'page': task['page'], 'status': 'error', 'error': str(exc)}
                    state['failed'] += 1
                state['pages'].append(row)
                state['updatedAt'] = now()
                state['elapsedSeconds'] = round(time.perf_counter()-tick, 1)
                save(args.output/'status.json', state)
                print(f'{state["completed"]+state["failed"]}/{state["total"]}: '
                      f'volume {row["volume"]} page {row["page"]} {row["status"]}', flush=True)
        state['status'] = 'complete_with_errors' if state['failed'] else 'complete'
    except BaseException as exc:
        state['status'] = 'interrupted'
        state['error'] = str(exc)
        raise
    finally:
        state['updatedAt'] = now()
        state['elapsedSeconds'] = round(time.perf_counter()-tick, 1)
        save(args.output/'status.json', state)


if __name__ == '__main__':
    main()
