import unittest

from kg_v2.artifact_types import infer_type
from kg_v2.caption_fields import caption_fields
from kg_v2.documents import caption_records


def infer(name):
    text = '1.'+name
    doc = {'page': 1, 'engine': 'test', 'pageKind': 'plate', 'text': text,
           'imageSize': [1000, 1000], 'blocks': [{'id': 'b', 'start': 0, 'end': len(text),
             'text': text, 'bbox': [0, 0, 100, 20]}]}
    record = caption_records(doc)[0]
    spans = [field['span'] for field in caption_fields({'document': doc, 'records': [record], 'fields': []})
             if field['kind'] == 'motif']
    value, _ = infer_type(record, doc, spans)
    if value:
        assert doc['text'][value['span'][0]:value['span'][1]] == value['raw']
    return value['label'] if value else None


class ArtifactTypeTests(unittest.TestCase):
    def test_depicted_object_does_not_become_carrier(self):
        self.assertEqual(infer('鹳鸟衔鱼石斧纹彩陶缸'), '缸')
        self.assertIsNone(infer('石斧纹'))

    def test_prefix_suffix_and_compound_names(self):
        for name, expected in [('人面鱼纹彩陶盆', '盆'), ('战国铜壶 兽耳龙凤纹', '壶'),
            ('商代铜镜（拓本与摹本）几何纹', '镜'), ('唐代金银平脱镜', '镜'),
            ('春秋瓦当 几何纹', '瓦当'), ('隋代织锦联珠对鸭纹', '织锦')]:
            with self.subTest(name=name):
                self.assertEqual(infer(name), expected)

    def test_shape_and_whitespace_do_not_change_head(self):
        self.assertEqual(infer('盘 口长颈瓷壶'), '壶')
        self.assertEqual(infer('人头塑像彩陶罐'), '罐')

    def test_motif_only_and_merged_captions_remain_unassigned(self):
        self.assertIsNone(infer('几何形纹'))
        self.assertIsNone(infer('汉代画像石4.汉代画像砖'))


if __name__ == '__main__':
    unittest.main()
