import copy
import unittest

from kg_v2.common import OUT, load
from kg_v2.identity import build_identity_review, lexical_candidates, normalize_name


class IdentityReviewTests(unittest.TestCase):
    def test_formatting_does_not_join_latin_words_or_rewrite_names(self):
        self.assertEqual(normalize_name(' \n商代玉器\u3000玉人\t'), '商代玉器玉人')
        self.assertEqual(normalize_name('ＡＢＣ　１２'), 'ABC 12')
        self.assertEqual(normalize_name(' New\n York '), 'New York')
        self.assertNotEqual(normalize_name('New York'), normalize_name('NewYork'))
        self.assertNotEqual(normalize_name('彩陶盆'), normalize_name('彩陶钵'))

    def test_formatted_names_are_lexically_retrievable_without_type_filter(self):
        entities = [{'label': ' 商代玉器 玉人 ', 'aliases': []},
                    {'label': '商代玉器玉人', 'aliases': []},
                    {'label': '另一名称', 'aliases': ['商代玉器玉人']},
                    {'label': '其他器物', 'aliases': []}]
        self.assertEqual(lexical_candidates(entities, 0), [1, 2])

    def test_real_candidates_are_partitioned_without_mutation_or_merges(self):
        graph = load(OUT / 'graph.json'); before = copy.deepcopy(graph)
        review = build_identity_review(graph)
        ids = [pid for group in review['groups'] for pid in group['proposalIds']]
        ids += review['differentNameProposalIds'] + review['typeConflictProposalIds']
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {p['id'] for p in graph['identityProposals']})
        self.assertEqual(graph, before)
        self.assertEqual(review['summary']['automaticIdentityMerges'], 0)

    def test_same_named_artifacts_retain_individual_sources_and_ids(self):
        graph = load(OUT / 'graph.json'); review = build_identity_review(graph)
        group = next(g for g in review['groups'] if g['name'] == '商代玉器玉人')
        self.assertEqual(len(group['memberIds']), 3)
        self.assertEqual(len(group['variants']), 2)
        self.assertFalse(group['identityConfirmed'])
        sources = [review['sources'][eid] for eid in group['memberIds']]
        self.assertEqual(len({s['recordId'] for s in sources}), 3)
        for source in sources:
            self.assertEqual(source['rawName'], source['evidence'][0]['text'])

    def test_source_context_belongs_to_its_caption(self):
        graph = load(OUT / 'graph.json'); review = build_identity_review(graph)
        records = {r['id']: r for r in graph['records']}
        for source in review['sources'].values():
            if source['recordId']:
                record = records[source['recordId']]
                self.assertEqual(source['context'], record['text'])
                self.assertEqual(source['page'], record['page'])
                self.assertEqual(source['item'], record['item'])
                ev = source['evidence'][0]
                self.assertTrue(record['span'][0] <= ev['span'][0] < ev['span'][1] <= record['span'][1])

    def test_concept_policy_unifies_period_occurrences_but_not_artifacts(self):
        review = build_identity_review(load(OUT / 'graph.json'))
        shang = next(c for c in review['concepts'] if c['name'] == '商代' and c['kind'] == 'period')
        self.assertEqual(len(shang['memberIds']), 22)
        self.assertEqual({review['sources'][eid]['conceptId'] for eid in shang['memberIds']}, {shang['id']})
        artifacts = [s for s in review['sources'].values() if s['kind'] == 'artifact']
        self.assertTrue(artifacts)
        self.assertTrue(all('conceptId' not in s for s in artifacts))


if __name__ == '__main__':
    unittest.main()
