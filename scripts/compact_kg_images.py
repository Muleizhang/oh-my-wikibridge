#!/usr/bin/env python3
"""Migrate existing results to original PDF scans without rerunning inference."""
import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from kg_v2.common import OUT, load, save, source_path
from kg_v2.images import extract_page_image, install_previews, layout_input_signature


def main():
    import fitz
    from PIL import Image
    parser = argparse.ArgumentParser()
    parser.add_argument('--prune', action='store_true', help='Remove reproducible PNG rasters after preview verification')
    parser.add_argument('--database-root', type=Path, default=Path.home()/'.local/share/cn.wikibridge.desktop')
    args = parser.parse_args()
    graph = load(OUT/'graph.json'); source = source_path(); assets = {}; changed_caches = 0
    before_graph = {key: value for key, value in graph.items() if key != 'pageImages'}
    with fitz.open(source) as document:
        for page in graph['selection']:
            record = load(OUT/f'pages/v1-p{page:04d}.json')
            asset = extract_page_image(document, page, record['render_width'], OUT/'images')
            with Image.open(OUT/'images'/asset['file']) as image:
                if image.size != (asset['width'], asset['height']): raise ValueError('Image size mismatch')
                image.verify()
            assets[str(page)] = asset
            layout_path = OUT/f'layout/v1-p{page:04d}.json'
            legacy_path = OUT/f'images/v1-p{page:04d}.png'
            if layout_path.exists():
                layout = load(layout_path)
                if not layout.get('inputSignature'):
                    if not legacy_path.exists(): raise ValueError(f'Missing legacy raster for page {page}')
                    digest = hashlib.sha256(legacy_path.read_bytes()).hexdigest()
                    if layout['imageSha256'] != digest: raise ValueError(f'Layout/raster mismatch on page {page}')
                    layout['inputSignature'] = layout_input_signature(record)
                    save(layout_path, layout); changed_caches += 1
            if page % 100 == 0: print(f'Original scans ready: page {page}', flush=True)
    save(OUT/'page-images.json', {'source': source.name, 'pages': assets})
    install_previews(graph, args.database_root)
    if {k: v for k, v in graph.items() if k != 'pageImages'} != before_graph:
        raise ValueError('Migration unexpectedly changed knowledge data')
    with sqlite3.connect(args.database_root/'knowledge.sqlite3', timeout=30) as connection:
        rows = connection.execute("SELECT id,graph_json FROM kg_runs WHERE json_extract(graph_json,'$.version')='typed-kg-v2'").fetchall()
        for run_id, payload in rows:
            saved = json.loads(payload)
            if saved['documents'][0]['source'] != source.name: continue
            saved['pageImages'] = {str(p): assets[str(p)] for p in saved['selection'] if str(p) in assets}
            connection.execute('UPDATE kg_runs SET graph_json=? WHERE id=?', (json.dumps(saved,ensure_ascii=False),run_id))
    save(OUT/'graph.json', graph)
    removed_bytes = 0; removed_files = 0
    if args.prune:
        for page in graph['selection']:
            asset = assets[str(page)]; original = OUT/'images'/asset['file']
            if hashlib.sha256(original.read_bytes()).hexdigest() != asset['sha256']: raise ValueError('Preview changed')
            desktop_dir = args.database_root/'pipeline-pages'/graph['runId']
            desktop = desktop_dir/asset['file']
            if not desktop.exists(): raise ValueError('Desktop preview is missing')
            for directory in [OUT/'images', args.database_root/'pipeline-pages']:
                old = directory/f'v1-p{page:04d}.png'
                if old.exists():
                    removed_bytes += old.stat().st_size; removed_files += 1; old.unlink()
    report = {'sourceBytes': source.stat().st_size, 'previewBytes': sum(a['bytes'] for a in assets.values()),
              'pages': len(assets), 'originalJPEGs': sum(a['storage']=='original_jpeg_stream' for a in assets.values()),
              'losslessOriginalResolutionImages': sum(a['storage']=='original_resolution_lossless' for a in assets.values()),
              'layoutCachesMigrated': changed_caches, 'removedRasterFiles': removed_files, 'removedRasterBytes': removed_bytes,
              'desktopHardlinks': sum(os.path.samefile(OUT/'images'/a['file'], args.database_root/'pipeline-pages'/graph['runId']/a['file']) for a in assets.values()),
              'knowledgeUnchanged': True, 'runId': graph['runId'], 'coordinateSystem': 'Original OCR spans and boxes retained; preview overlay uses the PDF image-to-OCR viewBox.'}
    save(OUT/'image-storage.json', report); print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__ == '__main__': main()
