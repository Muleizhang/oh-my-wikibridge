"""Bind source-verified, explicitly annotated plate crops to catalog records."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import shutil

from .common import ROOT
from .identity import normalize_name

MEDIA_FIELDS = ('imageUrl', 'detailUrl', 'captionUrl')


def source_pdf(graph_path):
    info = json.loads((Path(graph_path).parent / 'source.json').read_text())
    path = Path(info['path'])
    return path if path.is_absolute() else ROOT / path


def plate_index(manifest_path, pdf):
    """A page/item annotation is valid only for its exact source PDF."""
    manifest_path = Path(manifest_path)
    raw = json.loads(manifest_path.read_text())
    expected = raw.get('sha256', '')
    if not re.fullmatch(r'[a-f0-9]{64}', expected):
        raise ValueError('Plate manifest must identify its source PDF with SHA-256')
    with Path(pdf).open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
            raise ValueError('Plate crops belong to a different source PDF')
    base = manifest_path.parent.resolve()
    index = {}
    for row in sorted(raw.get('rows', []), key=lambda r: r.get('predicate') != 'decorated_with'):
        key = (int(row['page']), int(row['item']))
        if key in index:
            continue
        paths = {}
        for field in MEDIA_FIELDS:
            url = row.get(field)
            if not url:
                continue
            relative = Path(url)
            if relative.is_absolute() or '..' in relative.parts or '://' in url:
                raise ValueError('Plate assets must use local relative paths')
            path = (base / relative).resolve()
            # The original book-sample exporter prefixes URLs for the public/
            # web root, even when --output writes to a private data directory.
            if not path.is_file() and relative.parts[0] == 'book-sample':
                path = (base / Path(*relative.parts[1:])).resolve()
            if not path.is_relative_to(base) or not path.is_file():
                raise ValueError(f'Missing plate crop: {url}')
            if path.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp'}:
                raise ValueError('Unsupported plate image type')
            paths[field] = path
        if 'imageUrl' not in paths:
            continue
        index[key] = {**row, 'paths': paths, 'sourceSha256': expected}
    return index


def attach_plate_images(manifest, manifest_path, pdf, output):
    """Preserve original page evidence while attaching crops by page AND item.

    OCR text boxes are deliberately not used as artifact image regions.
    Missing annotations retain an explicitly labeled page-image fallback.
    """
    index = plate_index(manifest_path, pdf)
    rows_by_artifact = defaultdict(list)
    evidence_by_id = {ev['id']: ev for ev in manifest.get('evidence', [])}
    for row in manifest.get('rows', []):
        rows_by_artifact[row['artifactId']].append(row)
    items_by_position = defaultdict(list)
    for item in manifest.get('items', []):
        rows = rows_by_artifact[item['artifactId']]
        number = item.get('item', rows[0].get('item') if rows else None)
        if number is not None:
            items_by_position[(int(item.get('volumePage') or item['page']), int(number))].append(item)

    output = Path(output)
    count = 0
    skipped = []
    for position, annotation in index.items():
        candidates = items_by_position.get(position, [])
        if len(candidates) != 1:
            skipped.append({'page': position[0], 'item': position[1], 'reason': 'record_missing_or_ambiguous'})
            continue
        item = candidates[0]
        name = normalize_name(item['artifact'])
        annotated_name = normalize_name(annotation['artifact'])
        if name != annotated_name and not name.startswith(annotated_name + '('):
            skipped.append({'page': position[0], 'item': position[1], 'reason': 'artifact_name_mismatch'})
            continue
        media = {}
        key = hashlib.sha256(item['artifactId'].encode()).hexdigest()[:20]
        for field, source in annotation['paths'].items():
            relative = Path('crops') / f'{key}-{field}{source.suffix.lower()}'
            target = output / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source != target.resolve():
                shutil.copyfile(source, target)
            media[field] = relative.as_posix()
        media['detailUrl'] = media.get('detailUrl') or media['imageUrl']
        media.update(imageKind='artifact', detailLabel=annotation.get('detailLabel') or '纹样局部',
                     regionBoxes=annotation.get('regionBoxes'), cropSourceSha256=annotation['sourceSha256'])
        item.update(media)
        for row in rows_by_artifact[item['artifactId']]:
            row.update(media)
            ev = evidence_by_id.get(row.get('evidenceId'))
            if ev and int(ev.get('volumePage') or ev.get('page') or ev.get('ordinal') or 0) == position[0]:
                ev['captionUrl'] = media.get('captionUrl', '')
        count += 1
    manifest['plateImages'] = {'annotatedItems': count, 'availableAnnotations': len(index), 'skipped': skipped}
    manifest.setdefault('summary', {})['artifactCrops'] = count
    return manifest['plateImages']
