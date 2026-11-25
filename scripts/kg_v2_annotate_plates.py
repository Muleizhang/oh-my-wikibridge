#!/usr/bin/env python3
"""Propose scan regions and numbered caption groups using OpenCV and local OCR.

This pilot targets plates with figure numbers at the lower right of a group.
It never calls an LLM, accepts facts, or modifies the graph/crop manifest.
"""
import argparse
import atexit
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time

import cv2
import numpy as np
from kg_v2.plate_regions import isolated_digits, deduplicate_labels, choose_regions, nearest_groups


@lru_cache(maxsize=1)
def local_recognizer(model_dir):
    os.environ.update(PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK='True', HF_HUB_OFFLINE='1',
                      HF_HUB_DISABLE_IMPLICIT_TOKEN='1', TOKENIZERS_PARALLELISM='false')
    from paddleocr import TextRecognition
    model = TextRecognition(model_dir=model_dir, device='cpu', cpu_threads=4, enable_mkldnn=True)
    atexit.register(model.close)
    return model


@lru_cache(maxsize=1)
def weight_digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def area(box):
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def overlap(a, b):
    return area([max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])])


def merge_strokes(boxes):
    """Join overlapping stroke bounds; slight overlap of curved figures is insufficient."""
    boxes = [list(b) for b in boxes]
    while True:
        pair = next(((i, j) for i, a in enumerate(boxes) for j, b in enumerate(boxes[i + 1:], i + 1)
                     if overlap(a, b) > .15 * min(area(a), area(b))), None)
        if pair is None:
            return sorted(boxes, key=lambda b: (b[1], b[0]))
        i, j = pair
        a, b = boxes[i], boxes.pop(j)
        boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def ocr_lines(layout, width, height):
    raw = layout['raw']
    ocr = raw['overall_ocr_res']
    scale = [width / raw['width'], height / raw['height']] * 2
    return [{'text': t.strip(), 'score': float(s),
             'bbox': [round(v * k) for v, k in zip(b, scale)]}
            for t, s, b in zip(ocr['rec_texts'], ocr['rec_scores'], ocr['rec_boxes'])]


def erase(mask, box, pad=0):
    h, w = mask.shape
    x1, y1, x2, y2 = box
    mask[max(0, y1-pad):min(h, y2+pad), max(0, x1-pad):min(w, x2+pad)] = 0


def foreground(gray, threshold):
    h, w = gray.shape
    mask = cv2.inRange(gray, 0, threshold)
    mask[:round(.04*h)] = 0
    mask[round(.96*h):] = 0
    mask[:, :round(.02*w)] = 0
    mask[:, round(.95*w):] = 0
    return mask


def detect_regions(gray, lines, threshold=160, close_ratio=.0116):
    h, w = gray.shape
    mask = foreground(gray, threshold)
    rule_length = max(20, round(min(h, w) * .0676))
    for shape in [(1, rule_length), (rule_length, 1)]:
        rules = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones(shape, np.uint8))
        mask[cv2.dilate(rules, np.ones((7, 7), np.uint8)) > 0] = 0
    for line in lines:
        # Empty/low-confidence OCR detections can actually cover illustrations.
        if line['text'] and line['score'] > .8:
            erase(mask, line['bbox'], 8)
    kernel = max(3, round(w * close_ratio)) | 1
    connected = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((kernel, kernel), np.uint8))
    _, _, stats, _ = cv2.connectedComponentsWithStats(connected)
    boxes = [[int(x), int(y), int(x+bw), int(y+bh)] for x, y, bw, bh, a in stats[1:]
             if a > h*w*.00019 and bw > w*.0319 and bh > h*.0239]
    return merge_strokes(boxes)


def digit_patches(image, gray, boxes, lines):
    h, w = gray.shape
    mask = foreground(gray, 195)
    for line in lines:
        if line['text'] and not line['text'].isdigit() and line['score'] > .8:
            erase(mask, line['bbox'], 8)
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    patches, positions = [], []
    for x, y, bw, bh, a in stats[1:]:
        if not (.0018*w <= bw <= .0245*w and .0056*h <= bh <= .0197*h
                and h*w*.000006 <= a <= h*w*.000201):
            continue
        box = [int(x), int(y), int(x+bw), int(y+bh)]
        # A label can overlap the rectangle of a curved drawing slightly.
        if any(overlap(box, b) > .5*area(box) for b in boxes):
            continue
        if not any((b[0]+b[2])/2 <= x <= b[2]+.15*w and -.02*h <= y+bh-b[3] < .08*h
                   for b in boxes):
            continue
        positions.append(box)
        patches.append(image[max(0, y-6):min(h, y+bh+6), max(0, x-6):min(w, x+bw+6)])
    return patches, positions


def recognize_labels(image, gray, boxes, lines, expected, model_dir):
    # Explicit local weights: missing weights fail instead of downloading a model.
    model_dir = Path(model_dir).expanduser().resolve()
    weights = model_dir / 'inference.pdiparams'
    if not weights.is_file():
        raise FileNotFoundError(f'Local OCR weights are required: {weights}')
    patches, positions = isolated_digits(image, gray, lines) if expected else ([], [])
    labels = []
    rejected = []
    if patches:
        model = local_recognizer(str(model_dir))
        for box, prediction in zip(positions, model.predict(patches, batch_size=8)):
            result = prediction.json['res']
            text, score = result['rec_text'].strip(), float(result['rec_score'])
            row = {'text': text, 'score': score, 'bbox': box, 'method': 'local_digit_ocr'}
            if re.fullmatch(r'[0-9]+', text) and 1 <= int(text) <= max(expected) and score >= .9:
                labels.append({**row, 'item': int(text)})
            else:
                rejected.append(row)
    for line in lines:
        text = line['text']
        if text.isascii() and text.isdigit() and expected and 1 <= int(text) <= max(expected) and line['score'] >= .9:
            if not any(row['item'] == int(text) and overlap(row['bbox'], line['bbox']) > 0 for row in labels):
                labels.append({**line, 'item': int(text), 'method': 'cached_page_ocr'})
    labels = deduplicate_labels(labels, image.shape[1], image.shape[0])
    return labels, rejected, {'name': 'PP-OCRv5_server_rec', 'weightsSha256': weight_digest(str(weights))}


def group_regions(boxes, labels, width, height):
    """Infer candidate groups for plates whose numbers close each group at lower right.

    Keep duplicate labels and unassigned regions unresolved. Groups are caption
    associations only; they do not establish physical object identity.
    """
    duplicates = {r['item'] for r in labels if sum(s['item'] == r['item'] for s in labels) > 1}
    usable = sorted((r for r in labels if r['item'] not in duplicates), key=lambda r: r['bbox'][2])
    if not usable:
        return {}, list(range(len(boxes))), sorted(duplicates), []
    columns = [[]]
    for row in usable:
        if columns[-1] and row['bbox'][2] - columns[-1][-1]['bbox'][2] > .25*width:
            columns.append([])
        columns[-1].append(row)
    ends = [float(np.median([r['bbox'][2] for r in c])) for c in columns]
    column_for = [min(range(len(ends)), key=lambda k: abs(box[2]-ends[k])) for box in boxes]
    remaining = set(range(len(boxes)))
    groups = {}
    for column, anchors in enumerate(columns):
        for label in sorted(anchors, key=lambda r: r['bbox'][3]):
            x1, y1, x2, y2 = label['bbox']
            eligible = [i for i in remaining if column_for[i] == column and
                        boxes[i][3] <= y2+.02*height and (boxes[i][1]+boxes[i][3])/2 <= y2 and
                        boxes[i][2] <= x2+.04*width]
            groups[label['item']] = sorted(eligible, key=lambda i: (boxes[i][1], boxes[i][0]))
            remaining.difference_update(eligible)
    return groups, sorted(remaining), sorted(duplicates), ends


def generate(image_path, layout_path, extraction_path, output, model_dir, threshold=160, close_ratio=.0116,
             label_cache=None):
    started = time.perf_counter()
    image_path, output = Path(image_path), Path(output)
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f'Cannot read image: {image_path}')
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    layout = json.loads(Path(layout_path).read_text())
    extraction = json.loads(Path(extraction_path).read_text())
    if layout['page'] != extraction['page']:
        raise ValueError('Layout and caption pages differ')
    lines = ocr_lines(layout, w, h)
    records = extraction['records']
    expected = {int(r['item']) for r in records}
    boxes = detect_regions(gray, lines, threshold, close_ratio)
    if label_cache is None:
        labels, rejected, model = recognize_labels(image, gray, boxes, lines, expected, model_dir)
    else:
        if hashlib.sha256(image_path.read_bytes()).hexdigest() != label_cache['imageSha256']:
            raise ValueError('Label cache belongs to a different source image')
        model = label_cache['method']['labels']
        weights = Path(model_dir).expanduser()/'inference.pdiparams'
        if model['weightsSha256'] != weight_digest(str(weights)):
            raise ValueError('Label cache uses different OCR weights')
        rejected = label_cache['rejectedLabels']
        labels = list(label_cache['figureNumbers'])
        for row in rejected+lines:
            text = row['text'].strip()
            if text.isascii() and text.isdigit() and expected and 1 <= int(text) <= max(expected) and row['score'] >= .9:
                labels.append({**row,'item':int(text),'method':row.get('method','cached_page_ocr')})
        labels = deduplicate_labels(labels,w,h)
    boxes, region_method = choose_regions(image, gray, lines, labels, layout, boxes)
    groups, unassigned, duplicates, columns = nearest_groups(boxes, labels, w, h)
    # A printed figure number is a boundary even if its caption was not parsed.
    for number in list(groups):
        if number not in expected:
            unassigned.extend(groups.pop(number))
    missing = sorted(expected - {r['item'] for r in labels})
    issues = []
    if not records:
        issues.append({'kind': 'no_numbered_captions'})
    if missing:
        issues.append({'kind': 'missing_figure_numbers', 'items': missing})
    if duplicates:
        issues.append({'kind': 'ambiguous_figure_numbers', 'items': duplicates})
    if unassigned:
        issues.append({'kind': 'unassigned_regions', 'regions': [f'r{i+1:02d}' for i in unassigned]})
    empty = sorted(c['item'] for c in records if not groups.get(c['item']))
    if empty:
        issues.append({'kind': 'captions_without_regions', 'items': empty})
    unmatched = sorted({r['item'] for r in labels}-expected)
    if unmatched:
        issues.append({'kind': 'figure_numbers_without_captions', 'items': unmatched})
    output.mkdir(parents=True, exist_ok=True)
    (output / 'crops').mkdir(exist_ok=True)
    source_name = 'page' + image_path.suffix.lower()
    page_target = output / source_name
    if page_target.exists():
        if not os.path.samefile(image_path, page_target):
            page_target.unlink()
    if not page_target.exists():
        try:
            os.link(image_path, page_target)
        except OSError:
            shutil.copyfile(image_path, page_target)
    bindings = {i: item for item, indexes in groups.items() for i in indexes}
    regions = []
    for i, box in enumerate(boxes):
        x1, y1, x2, y2 = box
        crop_box = [max(0, x1-18), max(0, y1-18), min(w, x2+18), min(h, y2+18)]
        a, b, c, d = crop_box
        url = f'crops/r{i+1:02d}.jpg'
        cv2.imwrite(str(output / url), image[b:d, a:c], [cv2.IMWRITE_JPEG_QUALITY, 92])
        regions.append({'id': f'r{i+1:02d}', 'bbox': box,
                        'normalizedBbox': [v / k for v, k in zip(box, [w, h, w, h])],
                        'cropBbox': crop_box, 'cropUrl': url, 'item': bindings.get(i),
                        'status': 'candidate', 'reviewed': False})
    captions = []
    for record in records:
        item = int(record['item'])
        captions.append({'recordId': record['id'], 'item': item, 'label': record['label'],
                         'text': record['text'], 'ocrBbox': record['bbox'],
                         'regionIds': [f'r{i+1:02d}' for i in groups.get(item, [])],
                         'status': 'needs_review' if missing or duplicates else 'candidate',
                         'physicalIdentity': 'undetermined'})
    result = {'schema': 'plate-region-candidates/v1', 'page': extraction['page'],
              'source': extraction['document']['source'], 'imageUrl': source_name,
              'imageSha256': hashlib.sha256(image_path.read_bytes()).hexdigest(), 'imageSize': [w, h],
              'status': 'candidate', 'reviewed': False, 'graphModified': False,
              'method': {'regions': region_method, 'labels': model,
                         'grouping': 'nearest_number_geometry', 'llmUsed': False, 'usesCachedPageOcr': True,
                         'inkThreshold': threshold, 'closeRatio': close_ratio,
                         'columnRightEdges': columns},
              'regions': regions, 'captions': captions, 'figureNumbers': labels,
              'rejectedLabels': rejected, 'issues': issues,
              'summary': {'regions': len(regions), 'captions': len(captions), 'figureNumbers': len(labels),
                          'boundRegions': len(bindings), 'seconds': round(time.perf_counter()-started, 3)}}
    (output / 'candidate-annotations.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    template = Path(__file__).with_name('plate_annotation_review.html').read_text()
    # Embedded data avoids fetch/file:// issues and protects script boundaries.
    embedded = json.dumps(result, ensure_ascii=False).replace('<', '\\u003c')
    (output / 'index.html').write_text(template.replace('__PLATE_ANNOTATIONS__', embedded))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--layout', type=Path, required=True)
    parser.add_argument('--extraction', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model-dir', type=Path, default=Path.home()/'.paddlex/official_models/PP-OCRv5_server_rec')
    parser.add_argument('--ink-threshold', type=int, default=160)
    parser.add_argument('--close-ratio', type=float, default=.0116)
    args = parser.parse_args()
    if not 0 < args.ink_threshold < 256 or not 0 < args.close_ratio < .1:
        parser.error('Invalid foreground threshold or closing ratio')
    result = generate(args.image, args.layout, args.extraction, args.output,
                      args.model_dir, args.ink_threshold, args.close_ratio)
    print(json.dumps({'output': str(args.output/'index.html'), **result['summary'],
                      'issues': result['issues'], 'llmUsed': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
