"""Necessary projection checks: evidence retention, idempotence and both merge inputs."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
import io

from PIL import Image

from kg_v2.identity_manifest import apply_manifest_identity
from merge_kg_volumes import merge_volumes
from export_atlas_kg import export


def identity(volume, canonical='canonical-artifact-shared'):
    return {'version': 'strict-artifact-v1', 'volume': volume,
            'sourceToCanonical': {'entity': canonical}, 'recordToCanonical': {'record': canonical},
            'entities': [{'id': canonical, 'label': '人面鱼纹彩陶盆', 'decision': 'automatic_rule_supported',
                          'members': [{'volume': volume, 'entityId': 'entity', 'recordId': 'record',
                                       'sourceEntityId': f'{volume}:entity', 'sourceRecordId': f'{volume}:record'}]}]}


class IdentityManifestTest(unittest.TestCase):
    def test_idempotent_projection_preserves_every_source_and_undo(self):
        layer = identity('v1')
        layer['recordToCanonical']['record2'] = layer['recordToCanonical']['record']
        layer['entities'][0]['members'].append({'volume': 'v1', 'entityId': 'entity2', 'recordId': 'record2',
                                              'sourceEntityId': 'v1:entity2', 'sourceRecordId': 'v1:record2'})
        manifest = {'items': [{'artifactId': record, 'artifact': '人面鱼纹彩陶盆', 'evidenceId': record,
                               'imageUrl': f'{record}.jpg'} for record in ['record', 'record2']],
                    'rows': [{'id': f'{record}:statement', 'artifactId': record, 'evidenceId': record,
                              'predicate': 'made_of', 'object': '陶', 'status': 'candidate'}
                             for record in ['record', 'record2']],
                    'evidence': [{'id': record, 'text': f'evidence-{record}'} for record in ['record', 'record2']]}
        apply_manifest_identity(manifest, layer)
        self.assertEqual((len(manifest['items']), len(manifest['sourceItems'])), (1, 2))
        self.assertEqual((len(manifest['rows']), len(manifest['sourceRows'])), (1, 2))
        self.assertEqual(len(manifest['items'][0]['sourceRecords']), 2)
        self.assertEqual(set(manifest['rows'][0]['evidenceIds']), {'record', 'record2'})
        self.assertEqual(len(manifest['rows'][0]['sources']), 2)
        original = deepcopy(manifest)
        apply_manifest_identity(manifest, layer)
        self.assertEqual(manifest, original)
        undone = deepcopy(layer)
        undone['recordToCanonical']['record2'] = 'canonical-artifact-separate'
        member = undone['entities'][0]['members'].pop()
        undone['entities'].append({'id': 'canonical-artifact-separate', 'label': '人面鱼纹彩陶盆',
                                   'decision': 'source_record_only', 'members': [member]})
        apply_manifest_identity(manifest, undone)
        self.assertEqual((len(manifest['items']), len(manifest['rows'])), (2, 2))
        self.assertEqual([item['imageUrl'] for item in manifest['sourceItems']], ['record.jpg', 'record2.jpg'])

    def _merge_sources(self, graph_input):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            specs = []
            for number in [1, 2]:
                volume = root / f'volume{number}'
                volume.mkdir()
                layer = identity(f'v{number}')
                if graph_input:
                    (volume / 'images').mkdir()
                    (volume / 'images/v1-p0001.png').write_bytes(f'page-{number}'.encode())
                    graph = {'artifactIdentity': layer,
                             'documents': [{'page': 1, 'imageSize': [100, 100]}],
                             'records': [{'id': 'record', 'page': 1, 'item': 1, 'label': '人面鱼纹彩陶盆', 'text': '盆'}],
                             'entities': [{'id': 'entity', 'kind': 'artifact', 'label': '人面鱼纹彩陶盆', 'recordId': 'record'},
                                          {'id': 'motif', 'kind': 'motif', 'label': '人面鱼纹'}],
                             'assertions': [{'id': 'statement', 'subject': 'entity', 'predicate': 'decorated_with',
                                             'object': {'kind': 'entity', 'id': 'motif'},
                                             'evidence': [{'page': 1, 'text': f'source-{number}'}]}]}
                    (volume / 'graph.json').write_text(json.dumps(graph))
                else:
                    for page in ['p1', 'p2']:
                        (volume / page).mkdir()
                        (volume / page / 'r01.jpg').write_bytes(f'{number}-{page}'.encode())
                    manifest = {
                        'pages': [{'page': 1, 'previewUrl': 'p1/r01.jpg'}],
                        'items': [{'artifactId': 'record', 'artifact': '人面鱼纹彩陶盆', 'page': 1,
                                   'evidenceId': 'evidence', 'imageUrl': 'p1/r01.jpg',
                                   'imageCandidates': [{'imageUrl': 'p1/r01.jpg'}, {'imageUrl': 'p2/r01.jpg'}]}],
                        'rows': [{'id': 'statement', 'artifactId': 'record', 'page': 1,
                                  'evidenceId': 'evidence', 'predicate': 'decorated_with', 'object': '人面鱼纹',
                                  'binding': {'recordId': 'record'}, 'supportingEvidence': [{'page': 1, 'text': '盆'}]}],
                        'evidence': [{'id': 'evidence', 'ordinal': 1, 'text': '盆', 'previewUrl': 'p1/r01.jpg'}]}
                    manifest['rows'].append({'id': 'interpretation-statement', 'subjectKind': 'interpretation',
                        'subjectId': 'interpretation1', 'subjectKey': 'interpretation:interpretation1',
                        'predicate': 'symbolizes', 'object': '吉祥', 'page': 1, 'evidenceId': 'evidence'})
                    apply_manifest_identity(manifest, layer)
                    (volume / 'manifest.json').write_text(json.dumps(manifest))
                specs.append(f'第{number}册={volume}')
            output = root / 'merged'
            merged = merge_volumes(specs, output, mode='copy', build_html=False)
            self.assertEqual((len(merged['items']), len(merged['sourceItems'])), (1, 2))
            self.assertEqual(merged['items'][0]['artifactId'], 'canonical-artifact-shared')
            self.assertEqual((len(merged['rows']), len(merged['sourceRows'])), (1, 2) if graph_input else (3, 4))
            self.assertEqual({row['id'] for row in merged['rows'][0]['sources']}, {'v1:statement', 'v2:statement'})
            self.assertEqual({item['sourceRecordId'] for item in merged['sourceItems']}, {'v1:record', 'v2:record'})
            self.assertEqual(len(merged['evidence']), 2)
            if not graph_input:
                self.assertEqual({row['subjectKey'] for row in merged['rows'] if row.get('subjectKind') == 'interpretation'},
                                 {'interpretation:v1:interpretation1', 'interpretation:v2:interpretation1'})
                for number, source in enumerate(merged['sourceItems'], 1):
                    paths = [output / candidate['imageUrl'] for candidate in source['imageCandidates']]
                    self.assertNotEqual(paths[0], paths[1])
                    self.assertEqual([path.read_bytes() for path in paths], [f'{number}-p1'.encode(), f'{number}-p2'.encode()])

    def test_merge_manifest_sources_with_same_ids_and_same_crop_filenames(self):
        self._merge_sources(False)

    def test_merge_graph_sources_preserves_global_identity_and_evidence(self):
        self._merge_sources(True)

    def test_single_volume_export_keeps_both_catalog_images_and_statement_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            layer = identity('v1')
            layer['recordToCanonical']['record2'] = 'canonical-artifact-shared'
            layer['entities'][0]['members'].append({'volume': 'v1', 'entityId': 'entity2', 'recordId': 'record2',
                                                  'sourceEntityId': 'v1:entity2', 'sourceRecordId': 'v1:record2'})
            graph = {'artifactIdentity': layer, 'selection': [1, 2], 'entities': [{'id': 'motif', 'kind': 'motif', 'label': '人面鱼纹'}],
                     'documents': [], 'records': [], 'assertions': []}
            for number, record in enumerate(['record', 'record2'], 1):
                Image.new('RGB', (12, 12), (number * 90, 0, 0)).save(root / f'p{number}.jpg')
                entity_id = 'entity' if number == 1 else 'entity2'
                graph['documents'].append({'page': number, 'engine': 'ppstructure', 'imageSize': [12, 12], 'source': 'source.pdf'})
                graph['entities'].append({'id': entity_id, 'kind': 'artifact', 'label': '人面鱼纹彩陶盆', 'recordId': record})
                graph['records'].append({'id': record, 'label': '人面鱼纹彩陶盆', 'page': number, 'item': 1})
                graph['assertions'].append({'id': f'statement{number}', 'subject': entity_id, 'recordId': record,
                    'predicate': 'decorated_with', 'object': {'kind': 'entity', 'id': 'motif'},
                    'evidence': [{'page': number, 'engine': 'ppstructure', 'text': f'人面鱼纹-{number}'}], 'reviewStatus': 'unreviewed'})
            graph_file, pages_file = root / 'graph.json', root / 'page-images.json'
            graph_file.write_text(json.dumps(graph))
            pages_file.write_text(json.dumps({'pages': {str(n): {'file': f'p{n}.jpg'} for n in [1, 2]}}))
            with redirect_stdout(io.StringIO()):
                manifest = export(graph_file, pages_file, root, root / 'atlas')
            self.assertEqual((len(manifest['items']), len(manifest['sourceItems'])), (1, 2))
            self.assertEqual((len(manifest['rows']), len(manifest['sourceRows'])), (1, 2))
            sources = manifest['items'][0]['sourceRecords']
            self.assertNotEqual(sources[0]['imageUrl'], sources[1]['imageUrl'])
            for source in sources:
                self.assertTrue((root / 'atlas' / source['imageUrl']).is_file())
            self.assertEqual({source['id'] for source in manifest['rows'][0]['sources']}, {'statement1', 'statement2'})


if __name__ == '__main__':
    unittest.main()
