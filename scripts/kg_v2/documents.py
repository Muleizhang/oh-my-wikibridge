"""Preserve separate OCR streams, page geometry, and caption record boundaries."""
import re

from .common import ident

CAPTION = re.compile(r'(?:^|\n)\s*(?P<item>\d{1,2})\s*[.．、]\s*(?P<label>[\u3400-\u9fff][^\n]{1,65})')


def box_union(boxes):
    boxes = [b for b in boxes if b and len(b) == 4]
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)] if boxes else None


def document_from_tesseract(raw):
    text = raw['text']; cursor = 0; blocks = []
    for i, line in enumerate(raw['lines']):
        start = text.find(line['text'], cursor)
        if start < 0:
            raise ValueError('OCR line no longer aligns with original text')
        end = start + len(line['text']); cursor = end
        blocks.append({'id': f'tess:{raw["page_id"]}:{i}', 'kind': 'line', 'bbox': line['bbox'],
                       'start': start, 'end': end, 'text': line['text'], 'order': i})
    return {'page': raw['pdf_page'], 'engine': 'tesseract', 'text': text, 'blocks': blocks,
            'source': raw['source'], 'imageSize': raw['image_size']}


def document_from_structure(result, old):
    blocks, pieces, cursor = [], [], 0
    raw = result['raw']
    width, height = old['image_size']
    images = [b for b in raw['layout_det_res']['boxes'] if b['label'] == 'image']
    area = sum(max(0, b['coordinate'][2]-b['coordinate'][0]) * max(0, b['coordinate'][3]-b['coordinate'][1]) for b in images)
    recognized_characters = sum(len(t.strip()) for t in raw['overall_ocr_res']['rec_texts'])
    source_blocks = raw['parsing_res_list']
    prose_blocks = [b for b in source_blocks if b['block_label'] == 'text'
                    and len(b['block_content']) >= 160
                    and len(re.findall(r'[。！？；]', b['block_content'])) >= 2
                    and not CAPTION.match(b['block_content'])]
    # Long coherent paragraphs keep illustrated prose on the prose path even
    # when multiple figures leave little total text on the page.
    page_kind = 'plate' if (recognized_characters < 600 and not prose_blocks
                           and (len(images) >= 2 or area / (width * height) > .35)) else 'prose'
    fallback = False
    if page_kind == 'plate':
        # Layout detectors may classify an entire illustrated plate as one image.
        # Keep its OCR text, including captions, instead of losing unassigned text.
        ocr = raw['overall_ocr_res']
        source_blocks = [{'block_content': text, 'block_bbox': box, 'block_label': 'ocr_line',
                          'ocr_score': score} for text, box, score in
                         zip(ocr['rec_texts'], ocr['rec_boxes'], ocr['rec_scores']) if text.strip()]
        source_blocks.sort(key=lambda b: (round(b['block_bbox'][1] / 20), b['block_bbox'][0]))
        fallback = True
    for i, block in enumerate(source_blocks):
        content = block['block_content']
        if not content or block['block_label'] in {'image', 'chart'}:
            continue
        pieces.append(content)
        blocks.append({'id': f'pp:{old["page_id"]}:{i}', 'kind': block['block_label'],
                       'bbox': block['block_bbox'], 'start': cursor, 'end': cursor + len(content),
                       'text': content, 'order': block.get('block_order', i), 'ocrScore': block.get('ocr_score')})
        cursor += len(content) + 1
    doc = {'page': old['pdf_page'], 'engine': 'ppstructure', 'text': '\n'.join(pieces),
           'blocks': blocks, 'source': old['source'], 'imageSize': old['image_size'],
           'layout': raw['layout_det_res']}
    doc['pageKind'] = page_kind
    doc['pageKindEvidence'] = {'imageBlocks': len(images), 'imageAreaFraction': round(area / (width * height), 4),
                              'recognizedCharacters': recognized_characters, 'proseBlocks': len(prose_blocks)}
    doc['ocrLinesRetainedInsideImages'] = fallback
    return doc


def caption_records(document):
    if document.get('pageKind') != 'plate':
        return []
    matches = list(CAPTION.finditer(document['text']))
    records = []
    counts = {}
    for index, match in enumerate(matches):
        item = int(match['item']); counts[item] = counts.get(item, 0) + 1
        start = match.start('item')
        end = matches[index + 1].start() if index + 1 < len(matches) else len(document['text'])
        while end > start and document['text'][end - 1].isspace():
            end -= 1
        label = match['label'].strip()
        blocks = [b for b in document['blocks'] if b['start'] < end and b['end'] > start]
        records.append({'id': ident('record', document['page'], item, counts[item]),
            'page': document['page'], 'item': item, 'occurrence': counts[item], 'label': label,
            'titleSpan': list(match.span('label')), 'span': [start, end],
            'text': document['text'][start:end], 'bbox': box_union([b['bbox'] for b in blocks]),
            'blockIds': [b['id'] for b in blocks], 'engine': document['engine'],
            'identityStatus': 'source_record_only', 'issues': []})
    for record in records:
        if counts[record['item']] > 1:
            record['issues'].append('duplicate_item_number')
        if not re.search(r'[器盆壶瓶罐缸碗盘饰玉尊鼎爵簋卣斝觚镜陶铜漆石骨牙纹]', record['label']):
            record['issues'].append('record_subject_type_uncertain')
    return records


def record_for_span(records, start, end):
    found = [r for r in records if r['span'][0] <= start < end <= r['span'][1]]
    return found[0] if len(found) == 1 and not found[0]['issues'] else None
