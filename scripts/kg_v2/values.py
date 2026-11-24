"""Parse values only after a field is identified; never infer an owner here."""
import re
from decimal import Decimal, InvalidOperation

UNITS = {'毫米': ('mm', 'length', '0.1', 'cm'), '厘米': ('cm', 'length', '1', 'cm'),
         '公分': ('cm', 'length', '1', 'cm'), '米': ('m', 'length', '100', 'cm'),
         'mm': ('mm', 'length', '0.1', 'cm'), 'cm': ('cm', 'length', '1', 'cm'),
         'm': ('m', 'length', '100', 'cm'), '克': ('g', 'mass', '1', 'g'),
         '千克': ('kg', 'mass', '1000', 'g'), '公斤': ('kg', 'mass', '1000', 'g'),
         'g': ('g', 'mass', '1', 'g'), 'kg': ('kg', 'mass', '1000', 'g')}
FIELDS = {'通高': 'overall_height', '器高': 'height', '高': 'height', '口径': 'mouth_diameter',
          '底径': 'base_diameter', '最大径': 'maximum_diameter', '直径': 'diameter',
          '上宽': 'upper_width', '下宽': 'lower_width', '宽': 'width', '厚': 'thickness',
          '长': 'length', '重': 'weight', '重量': 'weight'}
FIELD_LABELS = {'height': '高度', 'overall_height': '通高', 'mouth_diameter': '口径',
                'base_diameter': '底径', 'maximum_diameter': '最大径', 'diameter': '直径',
                'upper_width': '上宽', 'lower_width': '下宽', 'width': '宽度',
                'thickness': '厚度', 'length': '长度', 'weight': '重量'}
NUMBER = r'\d+(?:\.\d+)?'
UNIT_RE = '|'.join(sorted(UNITS, key=len, reverse=True))
QUANTITY = re.compile(rf'(?P<approx>约|大约|近)?\s*(?P<lo>{NUMBER})(?:\s*(?:[—–~～-]|至)\s*(?P<hi>{NUMBER}))?\s*(?P<unit>{UNIT_RE})(?P<suffix>左右|余|多)?', re.I)
FIELD_RE = re.compile('(?P<field>' + '|'.join(sorted(FIELDS, key=len, reverse=True)) + r')\s*[:：]?\s*')


def decimal_string(value):
    return format(Decimal(value).normalize(), 'f')


def parse_quantity(raw):
    match = QUANTITY.fullmatch(raw.strip())
    if not match:
        return None
    try:
        lower = Decimal(match['lo']); upper = Decimal(match['hi']) if match['hi'] else lower
    except InvalidOperation:
        return None
    if lower < 0 or upper < lower:
        return None
    symbol, dimension, factor, base = UNITS[match['unit'].lower()]
    return {'kind': 'quantity', 'value': decimal_string(lower) if match['hi'] is None else None,
            'lower': decimal_string(lower), 'upper': decimal_string(upper), 'unit': symbol,
            'dimension': dimension, 'approximate': bool(match['approx'] or match['suffix']),
            'qualifier': (match['approx'] or '') + (match['suffix'] or ''),
            'normalized': {'lower': decimal_string(lower * Decimal(factor)),
                           'upper': decimal_string(upper * Decimal(factor)), 'unit': base}, 'raw': raw}


def extract_quantities(text):
    results = []
    for field in FIELD_RE.finditer(text):
        value = QUANTITY.match(text, field.end())
        if value:
            results.append({'predicate': FIELDS[field['field']], 'label': FIELD_LABELS[FIELDS[field['field']]],
                            'fieldSpan': list(field.span()), 'valueSpan': list(value.span()),
                            'span': [field.start(), value.end()], 'object': parse_quantity(value.group())})
    return results


def value_kind(raw):
    if parse_quantity(raw):
        return 'quantity'
    if re.fullmatch(r'(?:公元前|公元)?\d{1,4}年(?:\d{1,2}月)?(?:\d{1,2}日)?', raw):
        return 'time'
    if re.fullmatch(NUMBER, raw) or re.fullmatch(r'\d+[件个层号页]', raw):
        return 'number'
    return None
