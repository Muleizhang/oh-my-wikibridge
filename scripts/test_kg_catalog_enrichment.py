from copy import deepcopy
import unittest
from kg_v2.name_structure import parse_name
from kg_v2.catalog_enrichment import section_scopes,interpretation_context
from kg_v2.identity_manifest import apply_manifest_identity


def parse(text):
    return parse_name({'text':text,'span':[0,len(text)],'titleSpan':[0,len(text)]},{'text':text})


class CatalogStructureTest(unittest.TestCase):
    def test_ornament_and_quoted_inscription_do_not_hide_the_material(self):
        slots=parse('商代青铜象尊')
        self.assertEqual(slots['material'][0]['label'],'青铜')
        self.assertEqual(slots['shape'][0]['label'],'象形')
        self.assertEqual(slots['artifact_type'][0]['label'],'尊')
        slots=parse('商代后期凤鸟纹青铜“戈”卤')
        self.assertEqual(slots['material'][0]['label'],'青铜')
        self.assertNotEqual(slots['artifact_type'][0]['label'],'戈')

    def test_material_and_process_and_depicted_objects_have_different_slots(self):
        self.assertEqual(parse('鹳鸟衔鱼石斧纹彩陶缸')['material'][0]['label'],'陶')
        slots=parse('鎏金铜鉴')
        self.assertEqual(slots['material'][0]['label'],'铜')
        self.assertEqual(slots['decoration_material'][0]['label'],'金')
        self.assertEqual(slots['technique'][0]['label'],'鎏金')
        slots=parse('商代玉管展开图兽面纹')
        self.assertEqual(slots['material'][0]['label'],'玉')
        self.assertEqual(slots['artifact_type'][0]['label'],'管')
        self.assertNotIn('material',parse('金鱼纹'))
        self.assertEqual(parse('金银器'),{})

    def test_section_context_stops_at_prose_divider_and_ignores_map_labels(self):
        def doc(page,text,box,kind='plate'):
            return {'page':page,'engine':'ppstructure','pageKind':kind,'text':text,'imageSize':[1000,1400],
                    'blocks':[{'id':'b','text':text,'start':0,'end':len(text),'bbox':box}]}
        graph={'selection':[1,2,3,4], 'records':[], 'documents':[
            doc(1,'新石器时代',[100,500,800,600]),
            doc(2,'新石器时代',[900,100,950,700]),
            doc(3,'商·西周·春秋',[100,500,800,600],kind='prose')]}
        scopes=section_scopes(graph)
        self.assertEqual([(s['page'],s['endPageExclusive']) for s in scopes],[(1,3)])

    def test_interpretation_retains_culture_time_and_uncertain_language(self):
        text='良渚文化随葬器物的兽面纹，可能是一种辟邪的象征。'
        doc={'text':text,'page':1,'engine':'test','blocks':[{'id':'b','text':text,'start':0,'end':len(text),'bbox':[0,0,500,40]}]}
        ev={'page':1,'engine':'test','span':[0,len(text)]}
        record={'evidence':[ev],'valueEvidence':{'span':[text.index('辟邪'),text.index('辟邪')+2]}}
        result=interpretation_context(record,{(1,'test'):doc})
        self.assertEqual(result['certainty'],'hypothesis')
        self.assertEqual(result['cultures'],['良渚文化'])
        self.assertEqual(result['usages'],['随葬'])

    def test_superseded_source_relation_remains_available_but_is_not_queried(self):
        identity={'version':'test','volume':'v1','recordToCanonical':{'r':'c'},'entities':[]}
        manifest={'items':[{'artifactId':'r','artifact':'玉管'}],
            'rows':[{'id':'bad','artifactId':'r','predicate':'made_of','object':'玉管','evidenceId':'e',
                     'projectionStatus':'superseded','supersededBy':['good']},
                    {'id':'good','artifactId':'r','predicate':'made_of','object':'玉','evidenceId':'e'}],
            'evidence':[{'id':'e'}]}
        apply_manifest_identity(manifest,identity)
        self.assertEqual(len(manifest['sourceRows']),2)
        self.assertEqual([r['object'] for r in manifest['rows']],['玉'])
        before=deepcopy(manifest);apply_manifest_identity(manifest,identity);self.assertEqual(before,manifest)


if __name__=='__main__':unittest.main()
