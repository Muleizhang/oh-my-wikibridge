import unittest

from kg_v2.caption_fields import caption_fields, supplement_relations
from kg_v2.common import ident
from kg_v2.documents import caption_records


def fixture(text):
    blocks = []
    start = 0
    for index, line in enumerate(text.splitlines()):
        blocks.append({'id': f'b{index}', 'kind': 'ocr_line', 'text': line,
            'start': start, 'end': start + len(line), 'bbox': [0, index * 10, 100, index * 10 + 9]})
        start += len(line) + 1
    doc = {'page': 3, 'pageKind': 'plate', 'engine': 'test', 'text': text,
           'blocks': blocks, 'imageSize': [100, 1000]}
    return {'document': doc, 'records': caption_records(doc), 'fields': []}


class CaptionFieldsTests(unittest.TestCase):
    def test_motif_material_and_heading_keep_separate_source_evidence(self):
        x = fixture('新石器时代\n1.人面鱼纹彩陶盆\n高16.5厘米\n陕西西安半坡出土')
        entities = {ident('entity', r['id']): {'id': ident('entity', r['id']), 'label': r['label'], 'kind': 'artifact'} for r in x['records']}
        extra, statements = supplement_relations(x, entities, [])
        labels = {e['id']: e['label'] for e in extra}
        self.assertEqual({(s['predicate'], labels[s['object']['id']]) for s in statements},
                         {('period', '新石器时代'), ('decorated_with', '人面鱼纹'), ('made_of', '陶')})
        period = next(s for s in statements if s['predicate'] == 'period')
        self.assertEqual([e['text'] for e in period['evidence']], ['人面鱼纹彩陶盆', '新石器时代'])
        self.assertEqual(next(e for e in extra if e['kind'] == 'period')['aliases'], ['新石器时代'])
        for s in statements:
            for ev in s['evidence']:
                self.assertEqual(x['document']['text'][slice(*ev['span'])], ev['text'])
        self.assertFalse(any('16.5' in e['label'] for e in extra))

    def test_depicted_stone_axe_is_not_the_material_of_the_pottery(self):
        fields = caption_fields(fixture('1.鹳鸟衔鱼石斧纹彩陶缸\n高47厘米'))
        self.assertIn(('motif', '鹳鸟衔鱼石斧纹'), [(f['kind'], f['label']) for f in fields])
        self.assertEqual([f['label'] for f in fields if f['kind'] == 'material'], ['陶'])

    def test_explicit_dating_takes_priority_and_mixed_heading_assigns_no_single_era(self):
        fields = caption_fields(fixture('新石器时代\n1.商代青铜鼎饕餮纹'))
        self.assertEqual([f['label'] for f in fields if f['kind'] == 'period'], ['商代'])
        fields = caption_fields(fixture('商、西周、春秋\n1.兽面纹铜尊'))
        self.assertFalse(any(f['kind'] == 'period' for f in fields))

    def test_wrapped_name_and_carrier_prefix_are_supported(self):
        fields = caption_fields(fixture('1.象牙梳\nS纹\n长22厘米'))
        self.assertIn(('motif', 'S纹'), [(f['kind'], f['label']) for f in fields])
        self.assertIn(('material', '象牙'), [(f['kind'], f['label']) for f in fields])
        fields = caption_fields(fixture('1.商代青铜鼎饕餮纹'))
        self.assertIn(('motif', '饕餮纹'), [(f['kind'], f['label']) for f in fields])

    def test_existing_relations_are_preserved_and_second_run_is_idempotent(self):
        x = fixture('1.云雷纹青铜尊')
        entities = {ident('entity', r['id']): {'id': ident('entity', r['id']), 'label': r['label'], 'kind': 'artifact'} for r in x['records']}
        extra, statements = supplement_relations(x, entities, [])
        entities.update({e['id']: e for e in extra})
        self.assertEqual(supplement_relations(x, entities, statements), ([], []))

    def test_no_era_is_inferred_from_a_place_or_excavation_date(self):
        fields = caption_fields(fixture('1.人面鱼纹彩陶盆\n1974年陕西西安半坡出土'))
        self.assertFalse(any(f['kind'] == 'period' for f in fields))

    def test_vessel_named_jue_is_not_misread_as_horn_material(self):
        fields = caption_fields(fixture('1.商周铜角器形'))
        self.assertEqual([f['label'] for f in fields if f['kind'] == 'material'], ['铜'])


if __name__ == '__main__':
    unittest.main()
