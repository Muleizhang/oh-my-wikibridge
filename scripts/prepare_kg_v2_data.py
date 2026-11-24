#!/usr/bin/env python3
"""Prepare local page images/OCR for the pinned 20-page development slice."""
import argparse
import csv
import io
import json
import os
import re
import subprocess
from pathlib import Path

from kg_v2.common import OUT, DEVELOPMENT_PAGES, save


def page_record(source, page, width):
    import fitz
    from PIL import Image, ImageOps
    source = Path(source); signature = [source.stat().st_size, source.stat().st_mtime_ns]
    image_path = OUT / 'images' / f'v1-p{page:04d}.png'; record_path = OUT / 'pages' / f'v1-p{page:04d}.json'
    if record_path.exists() and image_path.exists():
        cached = json.loads(record_path.read_text())
        if cached.get('source_signature') == signature and cached.get('render_width') == width: return
    with fitz.open(source) as document:
        page_obj = document[page - 1]; scale = width / page_obj.rect.width
        pixmap = page_obj.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csGRAY, alpha=False)
    image = ImageOps.autocontrast(Image.frombytes('L', [pixmap.width, pixmap.height], pixmap.samples), cutoff=0.5)
    image_path.parent.mkdir(parents=True, exist_ok=True); image.save(image_path)
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
        'source_signature': signature, 'render_width': width, 'image_size': [image.width, image.height],
        'ocr_engine': 'tesseract', 'ocr_languages': 'chi_sim+eng', 'ocr_psm': 3,
        'text': '\n'.join(line['text'] for line in lines), 'lines': lines})


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--width', type=int, default=2600); parser.add_argument('--pages', type=int, nargs='+', default=DEVELOPMENT_PAGES)
    args = parser.parse_args()
    if not args.source.is_file(): raise SystemExit(f'Missing PDF: {args.source}')
    OUT.mkdir(parents=True, exist_ok=True); save(OUT / 'source.json', {'path': str(args.source), 'name': args.source.name})
    save(OUT / 'selection.json', {'development_pages': args.pages, 'source': args.source.name, 'note': 'Page numbers are PDF page numbers.'})
    for index, page in enumerate(args.pages, 1): page_record(args.source, page, args.width); print(f'OCR {index}/{len(args.pages)} page {page}', flush=True)


if __name__ == '__main__': main()
