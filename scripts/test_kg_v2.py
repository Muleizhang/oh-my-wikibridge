import copy
import sqlite3
import tempfile
import unittest
from pathlib import Path

from kg_v2.common import OUT, load
from kg_v2.contracts import publication_gate, statement_issues
from kg_v2.documents import caption_records
from kg_v2.evaluation import score_quantities, wilson_lower
from kg_v2.records import attributes
from kg_v2.values import parse_quantity, extract_quantities
from kg_v2_validate import validate


def document(text):
    return {'page': 1, 'pageKind': 'plate', 'engine': 'test', 'text': text,
            'blocks': [{'id': 'block', 'start': 0, 'end': len(text), 'bbox': [0,0,100,100]}]}


class TypedPipelineTests(unittest.TestCase):
    def test_quantity_preserves_unexpected_source_decimal(self):
        self.assertEqual(parse_quantity('2.1厘米')['value'], '2.1')
        self.assertEqual(parse_quantity('0.165米')['normalized']['lower'], '16.5')
        self.assertEqual(parse_quantity('约15～17厘米')['upper'], '17')
        self.assertTrue(parse_quantity('约15～17厘米')['approximate'])
        self.assertIsNone(parse_quantity('17至15厘米'))
        self.assertIsNone(parse_quantity('16.5悍米'))

    def test_dimensions_keep_distinct_meanings(self):
        fields = extract_quantities('上宽10.4厘米、下宽6.4厘米、通高5.2厘米、厚0.3厘米')
        self.assertEqual([f['predicate'] for f in fields], ['upper_width','lower_width','overall_height','thickness'])

    def test_adjacent_same_name_artifacts_do_not_share_dimensions(self):
        doc = document('1.彩陶盆\n高16.5厘米\n2.彩陶盆\n高20厘米')
        records = caption_records(doc); values = attributes(doc,records)
        self.assertEqual(len(records),2)
        self.assertNotEqual(values[0]['subject'],values[1]['subject'])
        self.assertEqual([(v['binding']['item'],v['object']['value']) for v in values],[(1,'16.5'),(2,'20')])

    def test_unassigned_quantity_is_not_attached_to_next_record(self):
        doc = document('高99厘米\n1.彩陶盆\n高16.5厘米')
        values = attributes(doc,caption_records(doc))
        self.assertEqual(len(values),1)
        self.assertEqual(values[0]['object']['value'],'16.5')

    def test_duplicate_numbers_are_not_silently_bound(self):
        doc = document('1.彩陶盆\n高16.5厘米\n1.彩陶盆\n高20厘米')
        values = attributes(doc,caption_records(doc))
        self.assertTrue(all(v['subject'] is None for v in values))

    def test_quantity_dimension_mismatch_blocks_acceptance(self):
        statement = {'subject':'a','predicate':'height','object':parse_quantity('16克'),'evidence':[{}]}
        self.assertIn('quantity_dimension_mismatch',statement_issues(statement,{'a':{'kind':'artifact'}}))

    def test_reference_score_requires_correct_owner(self):
        ref={'scope':[{'page':1,'items':[1,2]}],'authority':'synthetic_test','independent':False,
             'assertions':[{'page':1,'item':1,'predicate':'height','object':parse_quantity('16.5厘米')}]}
        doc=document('1.彩陶盆\n2.彩陶盆\n高16.5厘米');records=caption_records(doc)
        result=score_quantities(ref,attributes(doc,records),records)
        self.assertEqual((result['truePositive'],result['falsePositive'],result['falseNegative']),(0,1,1))

    def test_small_perfect_sample_does_not_establish_high_precision(self):
        self.assertLess(wilson_lower(18,18),.95)
        self.assertFalse(publication_gate({'referenceAuthority':'assistant_image_review',
            'factPrecisionLower95':1,'mergePrecisionLower95':1,'coverageMeasured':True})['automaticAcceptance'])
        self.assertFalse(publication_gate({'referenceAuthority':'independent_human',
            'factPrecisionLower95':1,'mergePrecisionLower95':1,'coverageMeasured':False})['automaticAcceptance'])

    def test_real_corpus_typed_values_and_event_time(self):
        graph=load(OUT/'graph.json');validate(graph)
        owner=next(r for r in graph['records'] if r['page']==3 and r['item']==3)
        values=[s for s in graph['assertions'] if s['recordId']==owner['id'] and s['predicate']=='height']
        self.assertEqual(len(values),1)
        self.assertEqual(values[0]['object']['kind'],'quantity')
        self.assertEqual(values[0]['object']['value'],'16.5')
        self.assertFalse(any(e['label']=='16.5厘米' for e in graph['entities']))
        self.assertTrue(any(e['time'] and '1974' in e['time']['raw'] and e['kind']=='collection' for e in graph['events']))
        self.assertFalse(any(s['predicate']=='period' and '1974' in str(s['object']) for s in graph['assertions']))

    def test_illustrated_prose_pages_are_not_skipped(self):
        for page in [32,40,42,52,78,94,100]:
            extraction=load(OUT/f'extractions/v1-p{page:04d}.json')
            self.assertEqual(extraction['document']['pageKind'],'prose')
            self.assertGreater(len(extraction['prose']),0)
            self.assertEqual(extraction['records'],[])

    def test_corrupt_source_span_is_rejected(self):
        graph=load(OUT/'graph.json');broken=copy.deepcopy(graph)
        broken['assertions'][0]['evidence'][0]['text']='invented evidence'
        with self.assertRaises(ValueError):validate(broken)

    def test_repeat_import_preserves_review_history(self):
        from kg_v2_store import persist
        graph=load(OUT/'graph.json')
        with tempfile.TemporaryDirectory(prefix='wikibridge-v2-test-') as tmp:
            root=Path(tmp);first=persist(graph,root)
            with sqlite3.connect(root/'knowledge.sqlite3') as conn:
                conn.execute(
                    'INSERT INTO kg_reviews(id,run_id,target_kind,target_id,decision,reviewer,note) VALUES (?,?,?,?,?,?,?)',
                    ('test-review',first['runId'],'assertion',graph['assertions'][0]['id'],'reject','synthetic-test','Test fixture only'))
            second=persist(graph,root)
            self.assertEqual(first['runId'],second['runId'])
            self.assertEqual(second['reviewsPreserved'],1)
            with sqlite3.connect(root/'knowledge.sqlite3') as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM kg_runs').fetchone()[0],1)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM kg_assertions').fetchone()[0],len(graph['assertions']))


if __name__ == '__main__': unittest.main()
