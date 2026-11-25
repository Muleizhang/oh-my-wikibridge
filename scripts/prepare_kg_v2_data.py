#!/usr/bin/env python3
"""Prepare local page images/OCR for the pinned 20-page development slice."""
import argparse
import csv
import hashlib
import io
import json
import os
import re
import subprocess
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from kg_v2.common import OUT, DEVELOPMENT_PAGES, save
from kg_v2.images import extract_page_image, ocr_image_file


def page_record(source, page, width):
    source = Path(source); signature = [source.stat().st_size, source.stat().st_mtime_ns]
    record_path = OUT / 'pages' / f'v1-p{page:04d}.json'
    if record_path.exists():
        cached = json.loads(record_path.read_text())
        if cached.get('source_signature') == signature and cached.get('render_width') == width: return
    with ocr_image_file(source, page, width) as (image_path, image_size):
        image_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
        result = subprocess.run(['tesseract', str(image_path), 'stdout', '-l', 'chi_sim+eng', '--psm', '3', 'tsv'],
            check=True, capture_output=True, text=True, env={**os.environ, 'OMP_THREAD_LIMIT': '1'})
    blocks = {}
    for row in csv.DictReader(io.StringIO(result.stdout), delimiter='\t', quoting=csv.QUOTE_NONE):
        if row.get('level') != '5' or not row.get('text', '').strip(): continue
        blocks.setdefault((row['block_num'], row['par_num'], row['line_num']), []).append(row)
    lines = []
    for words in blocks.values():
        text = re.sub(r'(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])', '', ' '.join(w['text'].strip() for w in words))
        lines.append({'text': text, 'bbox': [min(int(w['left']) for w in words), min(int(w['top']) for w in words),
            max(int(w['left']) + int(w['width']) for w in words), max(int(w['top']) + int(w['height']) for w in words)]})
    save(record_path, {'page_id': f'v1-p{page:04d}', 'source': source.name, 'pdf_page': page,
        'source_signature': signature, 'render_width': width, 'image_size': list(image_size),
        'preprocessedImageSha256': image_hash,
        'ocr_engine': 'tesseract', 'ocr_languages': 'chi_sim+eng', 'ocr_psm': 3,
        'text': '\n'.join(line['text'] for line in lines), 'lines': lines})


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--source', type=Path, required=True)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--pages', type=int, nargs='+')
    selection.add_argument('--all-pages', action='store_true')
    parser.add_argument('--width', type=int, default=2600); parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    if not args.source.is_file(): raise SystemExit(f'Missing PDF: {args.source}')
    if args.workers < 1: raise SystemExit('--workers must be at least 1')
    import fitz
    with fitz.open(args.source) as document:
        pages = list(range(1, len(document) + 1)) if args.all_pages else args.pages or DEVELOPMENT_PAGES
        if any(p < 1 or p > len(document) for p in pages): raise SystemExit('Page outside PDF')
        assets = {str(p): extract_page_image(document, p, args.width, OUT / 'images') for p in pages}
    if len(set(pages)) != len(pages) or any(page < 1 for page in pages):
        raise SystemExit('PDF pages must be unique positive integers')
    OUT.mkdir(parents=True, exist_ok=True); save(OUT / 'source.json', {'path': str(args.source), 'name': args.source.name})
    save(OUT / 'page-images.json', {'source': args.source.name, 'pages': assets})
    save(OUT / 'selection.json', {'development_pages': pages, 'source': args.source.name,
        'ocrWorkers': args.workers, 'note': 'Page numbers are PDF page numbers.'})
    tasks = [(str(args.source.resolve()), page, args.width) for page in pages]
    if args.workers == 1:
        for index, task in enumerate(tasks, 1):
            page_record(*task); print(f'OCR {index}/{len(tasks)} page {task[1]}', flush=True)
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(page_record, *task): task[1] for task in tasks}
            for index, future in enumerate(as_completed(futures), 1):
                future.result(); print(f'OCR {index}/{len(tasks)} page {futures[future]}', flush=True)


if __name__ == '__main__': main()
