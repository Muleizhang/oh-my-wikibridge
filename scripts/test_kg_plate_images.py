"""Check crop ownership, source isolation and portable atlas assets."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from kg_v2.plate_images import attach_plate_images
from merge_kg_volumes import merge_volumes
from package_kg_share import asset_urls, original_pages


class AtlasPlateImagesTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.pdf = self.root / 'book.pdf'
        self.pdf.write_bytes(b'original-source-pdf')
        self.plates = self.root / 'plate-images'
        self.plates.mkdir()
        rows = []
        for item in [1, 2]:
            row = {'page': 1, 'item': item, 'artifact': '同名彩陶盆', 'predicate': 'decorated_with'}
            for field in ['imageUrl', 'detailUrl', 'captionUrl']:
                name = f'{item}-{field}.jpg'
                (self.plates / name).write_bytes(f'{item}:{field}'.encode())
                row[field] = 'book-sample/' + name
            rows.append(row)
        self.annotation = {'sha256': hashlib.sha256(self.pdf.read_bytes()).hexdigest(), 'rows': rows}
        self.annotation_path = self.plates / 'manifest.json'
        self.annotation_path.write_text(json.dumps(self.annotation, ensure_ascii=False))
        self.site = self.root / 'site'
        self.site.mkdir()
        (self.site / 'page.jpg').write_bytes(b'full-page-image')
        self.manifest = {
            'title': '测试卷', 'pages': [{'page': 1, 'previewUrl': 'page.jpg'}],
            'items': [{'artifactId': f'a{i}', 'artifact': '同名彩陶盆', 'page': 1, 'item': i,
                       'imageUrl': 'page.jpg', 'detailUrl': 'page.jpg', 'captionUrl': '',
                       'pageUrl': 'page.jpg', 'imageKind': 'page', 'evidenceId': f'e{i}'} for i in [1, 2, 3]],
            'rows': [{'id': f's{i}', 'artifactId': f'a{i}', 'page': 1, 'item': i, 'artifact': '同名彩陶盆',
                      'evidenceId': f'e{i}', 'predicate': 'decorated_with', 'object': '鸟纹'} for i in [1, 2, 3]],
            'evidence': [{'id': f'e{i}', 'page': 1, 'ordinal': 1, 'previewUrl': 'page.jpg',
                          'captionUrl': '', 'bbox': [0.1, 0.7, 0.2, 0.8]} for i in [1, 2, 3]],
        }

    def test_crops_stay_with_same_page_item_through_merge_and_original_page_packaging(self):
        report = attach_plate_images(self.manifest, self.annotation_path, self.pdf, self.site)
        self.assertEqual(report['annotatedItems'], 2)
        a, b, missing = self.manifest['items']
        self.assertNotEqual(a['imageUrl'], b['imageUrl'])
        self.assertEqual((self.site / a['imageUrl']).read_bytes(), b'1:imageUrl')
        self.assertEqual((self.site / b['imageUrl']).read_bytes(), b'2:imageUrl')
        self.assertEqual(missing['imageKind'], 'page')
        self.assertEqual(missing['imageUrl'], 'page.jpg')
        self.assertEqual(self.manifest['evidence'][0]['previewUrl'], 'page.jpg')
        self.assertEqual(self.manifest['evidence'][0]['captionUrl'], a['captionUrl'])
        (self.site / 'manifest.json').write_text(json.dumps(self.manifest, ensure_ascii=False))
        merged_site = self.root / 'merged'
        merged = merge_volumes([f'测试卷={self.site}'], merged_site, mode='copy', build_html=False)
        self.assertEqual(merged['summary']['artifactCrops'], 2)
        a = merged['items'][0]
        crop_urls = {field: a[field] for field in ['imageUrl', 'detailUrl', 'captionUrl']}
        for url in crop_urls.values():
            self.assertTrue((merged_site / url).is_file())

        image_root = self.root / 'images'
        image_root.mkdir()
        original = image_root / 'scan.jpg'
        original.write_bytes(b'full-resolution-original')
        (self.root / 'page-images.json').write_text(json.dumps({'pages': {'1': {
            'file': original.name, 'width': 2000, 'height': 3000,
            'sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
        }}}))
        originals, _ = original_pages(merged, [self.root / 'graph.json'])
        self.assertEqual({field: a[field] for field in crop_urls}, crop_urls)
        self.assertIn(a['pageUrl'], originals)
        self.assertEqual(originals[a['pageUrl']].read_bytes(), original.read_bytes())
        self.assertTrue(set(crop_urls.values()).issubset(set(asset_urls(merged))))

    def test_source_mismatch_is_rejected_before_binding_any_crop(self):
        original = copy.deepcopy(self.manifest)
        self.pdf.write_bytes(b'a-different-edition')
        with self.assertRaisesRegex(ValueError, 'different source PDF'):
            attach_plate_images(self.manifest, self.annotation_path, self.pdf, self.site)
        self.assertEqual(self.manifest, original)

    def test_name_mismatch_or_ambiguous_position_does_not_guess_an_image(self):
        self.manifest['items'][0]['artifact'] = '另一件器物'
        self.manifest['items'].append({**self.manifest['items'][1], 'artifactId': 'duplicate-position'})
        report = attach_plate_images(self.manifest, self.annotation_path, self.pdf, self.site)
        self.assertEqual(report['annotatedItems'], 0)
        self.assertEqual({row['reason'] for row in report['skipped']},
                         {'artifact_name_mismatch', 'record_missing_or_ambiguous'})


if __name__ == '__main__':
    unittest.main()
