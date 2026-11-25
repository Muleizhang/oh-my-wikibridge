"""Only the exact identity acceptance/rejection boundary and reversibility."""
from copy import deepcopy
import unittest

from kg_v2.artifact_identity import name_key, quantity_key, compare, plan, VERSION
from kg_v2.values import parse_quantity


def profile(key, value='19', *, location='陕西西安半坡'):
    return {'id': key, 'sourceEntityId': key, 'sourceRecordId': key.replace('entity', 'record'),
            'volume': key.split(':')[0], 'entityId': key.split(':')[-1],
            'recordId': key.replace('entity', 'record').split(':')[-1], 'rawName': '人面鱼纹彩陶盆',
            'name': '人面鱼纹彩陶盆', 'page': 1, 'item': 1, 'issues': [],
            'locations': [location], 'dimensionSignature': [['height', 'length', value, 'cm']],
            'knownProperties': {}, 'eligible': True}


class ExactArtifactIdentityTest(unittest.TestCase):
    def test_only_whitelisted_view_notes_disappear(self):
        self.assertEqual(name_key(' 人面鱼纹彩陶盆（上：俯视图） '), '人面鱼纹彩陶盆')
        self.assertEqual(name_key('盆（残片）'), '盆(残片)')
        self.assertEqual(name_key('盆（俯视图，仿制品）'), '盆(俯视图,仿制品)')

    def test_units_use_decimal_without_tolerance(self):
        self.assertEqual(quantity_key(parse_quantity('165毫米')), quantity_key(parse_quantity('16.50厘米')))
        with self.assertRaises(ValueError): quantity_key(parse_quantity('约19厘米'))
        with self.assertRaises(ValueError): quantity_key(parse_quantity('19-20厘米'))

    def test_conflict_missing_and_field_identity(self):
        a, b = profile('v1:entity-a'), profile('v1:entity-b', '20')
        self.assertEqual(compare(a, b)['status'], 'recorded_dimension_conflict')
        b['dimensionSignature'] = []
        self.assertIn('dimensions_missing', compare(a, b)['reasons'])
        a['dimensionSignature'] = []
        self.assertNotEqual(compare(a, b)['status'], 'strict_rule_supported')
        a, b = profile('v1:entity-a'), profile('v1:entity-b')
        b['dimensionSignature'][0][0] = 'mouth_diameter'
        self.assertNotEqual(compare(a, b)['status'], 'strict_rule_supported')

    def test_exact_place_and_explicit_properties(self):
        a, b = profile('v1:entity-a'), profile('v1:entity-b', location='陕西西安')
        self.assertIn('location_mismatch_or_missing', compare(a, b)['reasons'])
        b['locations'] = a['locations']
        a['knownProperties'] = {'made_of': ['陶']}; b['knownProperties'] = {'made_of': ['铜']}
        self.assertEqual(compare(a, b)['status'], 'identity_property_conflict')
        a['knownProperties'] = {'made_of': ['青铜']}
        self.assertEqual(compare(a, b)['status'], 'strict_rule_supported')

    def test_complete_groups_do_not_bridge_missing_record(self):
        aa = [profile('v1:entity-a'), profile('v1:entity-b'), profile('v1:entity-c')]
        aa[-1]['dimensionSignature'] = []; aa[-1]['issues'] = ['dimensions_missing']
        p = plan(aa, {})
        self.assertEqual(p['summary']['mergedGroups'], 1)
        self.assertNotEqual(p['sourceToCanonical'][aa[0]['id']], p['sourceToCanonical'][aa[-1]['id']])

    def test_ocr_or_image_holds_block_the_rule(self):
        a, b = profile('v1:entity-a'), profile('v1:entity-b')
        a['issues'] = ['ocr_numeric_disagreement']
        self.assertEqual(plan([a,b], {})['summary']['mergedGroups'], 0)

    def test_idempotence_cross_volume_namespace_and_revocation(self):
        aa = [profile('v1:entity-a'), profile('v2:entity-a')]
        p = plan(aa, {})
        self.assertEqual(p, plan(deepcopy(aa), {'canonicalBySource':p['sourceToCanonical']}))
        registry = {'rejectedPairs':[{'members':[a['id'] for a in aa], 'active':True}]}
        undone = plan(aa, registry)
        self.assertEqual(undone['summary']['mergedGroups'], 0)
        self.assertEqual(len(set(undone['sourceToCanonical'].values())), 2)
        self.assertEqual(undone, plan(aa, registry))
        self.assertEqual(p['version'], VERSION)


if __name__ == '__main__': unittest.main()
