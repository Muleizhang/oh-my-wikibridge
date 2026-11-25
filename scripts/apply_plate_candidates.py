#!/usr/bin/env python3
"""Display local automatic crop candidates in an existing merged atlas."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil

from PIL import Image
from kg_v2.common import ROOT, save
from kg_v2.identity import normalize_name


def local_image(base, url):
    path = (base / url).resolve()
    if not path.is_relative_to(base.resolve()) or not path.is_file():
        raise ValueError(f'Missing or external candidate image: {url}')
    return path


def group_image(paths, destination):
    """Assemble a caption group without resizing its individual subimages."""
    columns = math.ceil(math.sqrt(len(paths)))
    images = []
    try:
        for path in paths:
            with Image.open(path) as image:
                images.append(image.convert('RGB'))
        widths = [max(im.width for i, im in enumerate(images) if i % columns == col)
                  for col in range(columns)]
        rows = math.ceil(len(images)/columns)
        heights = [max(im.height for im in images[row*columns:(row+1)*columns]) for row in range(rows)]
        canvas = Image.new('RGB', (sum(widths)+16*(columns+1), sum(heights)+16*(rows+1)), 'white')
        try:
            for i, image in enumerate(images):
                row, col = divmod(i, columns)
                x = sum(widths[:col])+16*(col+1)+(widths[col]-image.width)//2
                y = sum(heights[:row])+16*(row+1)+(heights[row]-image.height)//2
                canvas.paste(image, (x, y))
            canvas.save(destination, quality=90)
        finally:
            canvas.close()
    finally:
        for image in images:
            image.close()


def attach_candidates(manifest, annotations, site):
    site, annotations = Path(site).resolve(), Path(annotations).resolve()
    if not annotations.is_relative_to(site):
        raise ValueError('Annotations must be stored inside the atlas site')
    items = {item['artifactId']: item for item in manifest['items']}
    rows_by_artifact = defaultdict(list)
    for row in manifest['rows']:
        rows_by_artifact[row['artifactId']].append(row)
    counts = Counter()
    skipped = []
    for volume in manifest['volumes']:
        match = re.fullmatch(r'v(\d+)', volume['prefix'])
        if not match:
            continue
        directory = annotations / f'vol{match[1]}'
        for file in sorted(directory.glob('p*/candidate-annotations.json')):
            data = json.loads(file.read_text())
            base = file.parent
            if data.get('schema') != 'plate-region-candidates/v1':
                raise ValueError(f'Unknown annotation schema: {file}')
            region_index = {region['id']: region for region in data['regions']}
            source_verified = False
            for caption in data['captions']:
                key = f"{volume['prefix']}:{caption['recordId']}"
                item = items.get(key)
                if not item or not caption['regionIds']:
                    continue
                if item.get('imageKind') == 'artifact':
                    counts['preservedExplicitCrops'] += 1
                    continue
                if (int(item.get('volumePage') or item['page']) != int(data['page']) or
                        Path(item.get('sourceName', '')).name != Path(data['source']).name or
                        normalize_name(item['artifact']) != normalize_name(caption['label'])):
                    skipped.append({'artifactId': key, 'reason': 'source_record_mismatch'})
                    continue
                if not source_verified:
                    source = local_image(base, data['imageUrl'])
                    with source.open('rb') as stream:
                        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                    if digest != data['imageSha256']:
                        raise ValueError(f'Source image changed: {file}')
                    source_verified = True
                regions = [region_index[rid] for rid in caption['regionIds']]
                if any(region['item'] != caption['item'] for region in regions):
                    raise ValueError(f'Inconsistent region group: {file}, {key}')
                paths = [local_image(base, region['cropUrl']) for region in regions]
                gallery = [{'imageUrl': path.relative_to(site).as_posix(),
                            'regionId': region['id'], 'bbox': region['normalizedBbox']}
                           for path, region in zip(paths, regions)]
                group_dir = base/'groups'
                group_dir.mkdir(exist_ok=True)
                stem = hashlib.sha256(key.encode()).hexdigest()[:20]
                if len(paths) == 1:
                    plate = paths[0]
                else:
                    plate = group_dir/f'{stem}.jpg'
                    group_image(paths, plate)
                thumb = group_dir/f'{stem}-thumb.jpg'
                with Image.open(plate) as image:
                    image.thumbnail((480, 480), Image.Resampling.LANCZOS)
                    image.convert('RGB').save(thumb, quality=76, optimize=True)
                media = {'imageUrl': plate.relative_to(site).as_posix(),
                         'detailUrl': thumb.relative_to(site).as_posix(),
                         'imageKind': 'artifact_candidate', 'imageReviewStatus': 'candidate',
                         'detailLabel': '自动裁图候选', 'cropSourceSha256': data['imageSha256']}
                item.update(media, item=caption['item'], imageCandidates=gallery,
                            imageAnnotation={'method': data['method']['regions'],
                                             'regionCount': len(gallery),
                                             'pageIssues': data['issues']})
                for row in rows_by_artifact[key]:
                    row.update(media)
                counts['candidateItems'] += 1
                counts['candidateSubimages'] += len(gallery)
                counts[f"{volume['prefix']}Items"] += 1
    manifest['summary']['candidateImageItems'] = counts['candidateItems']
    manifest['summary']['artifactCrops'] = sum(
        item.get('imageKind') in {'artifact', 'artifact_candidate'} for item in manifest['items'])
    report = {'status': 'candidate', **dict(counts), 'skipped': skipped}
    manifest['candidatePlateImages'] = report
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, default=ROOT/'data/local-kg/merged/site')
    parser.add_argument('--annotations', type=Path)
    parser.add_argument('--reset-candidates', action='store_true',
                        help='Replace previous automatic crops; retain explicit crops and original pages')
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    site = args.site.resolve()
    manifest_path = site/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    original_items = [item['artifactId'] for item in manifest['items']]
    original_rows = [(row['id'], row['artifactId'], row['predicate'], row['object']) for row in manifest['rows']]
    backup = ROOT/'data/local-kg/archive'/('before-candidate-images-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    backup.mkdir(parents=True)
    shutil.copyfile(manifest_path, backup/'manifest.json')
    if args.reset_candidates:
        reset = set()
        for item in manifest['items']:
            if item.get('imageKind') != 'artifact_candidate':
                continue
            reset.add(item['artifactId'])
            item.update(imageUrl=item['pageUrl'],detailUrl=item['pageUrl'],imageKind='page',detailLabel='原书整页')
            for key in ['imageCandidates','imageAnnotation','imageReviewStatus','cropSourceSha256']:
                item.pop(key,None)
        for row in manifest['rows']:
            if row['artifactId'] in reset:
                row.update(imageUrl=row.get('pageUrl',''),detailUrl=row.get('pageUrl',''),imageKind='page',detailLabel='原书整页')
                row.pop('imageReviewStatus',None)
                row.pop('cropSourceSha256',None)
    parts = []
    for volume in manifest['volumes']:
        prefix = volume['prefix']+':'
        parts.append({'volumes':[volume], 'items':[item for item in manifest['items'] if item['artifactId'].startswith(prefix)],
                      'rows':[row for row in manifest['rows'] if row['artifactId'].startswith(prefix)], 'summary':{}})
    def attach_part(part):
        return attach_candidates(part,args.annotations or site/'annotations',site)
    with ThreadPoolExecutor(max_workers=max(1,args.workers)) as pool:
        reports = list(pool.map(attach_part,parts))
    counts = Counter()
    skipped = []
    for part_report in reports:
        counts.update({key:value for key,value in part_report.items() if isinstance(value,int)})
        skipped.extend(part_report['skipped'])
    report = {'status':'candidate',**dict(counts),'skipped':skipped}
    manifest['candidatePlateImages'] = report
    manifest['summary']['candidateImageItems'] = counts['candidateItems']
    manifest['summary']['artifactCrops'] = sum(item.get('imageKind') in {'artifact','artifact_candidate'} for item in manifest['items'])
    assert original_items == [item['artifactId'] for item in manifest['items']]
    assert original_rows == [(row['id'], row['artifactId'], row['predicate'], row['object']) for row in manifest['rows']]
    save(manifest_path, manifest)
    template = (ROOT/'scripts/atlas_viewer.html').read_text()
    reasoner = re.sub(r'(?m)^export\s+', '', (ROOT/'src/kg-reasoner.js').read_text())
    embedded = json.dumps(manifest, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    (site/'index.html').write_text(template.replace('__REASONER_JS__', reasoner, 1).replace('__MANIFEST_JSON__', embedded, 1))
    print(json.dumps({'backup': str(backup), **report}, ensure_ascii=False))


if __name__ == '__main__':
    main()
