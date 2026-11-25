import unittest
from kg_v2.name_materials import name_material


def material(name):
    text='1.'+name
    doc={'page':1,'engine':'ppstructure','text':text,'blocks':[{'text':text,'start':0,'end':len(text),'bbox':[0,0,500,40]}]}
    record={'id':'record','titleSpan':[2,len(text)],'span':[0,len(text)],'text':text}
    result,_=name_material(record,doc)
    if result:
        assert doc['text'][slice(*result['span'])] == result['raw']
    return result


class NameMaterialTest(unittest.TestCase):
    def test_rare_carriers_and_spacing_keep_exact_material_evidence(self):
        for name in ['战国铜鉴 水陆攻战纹','战国刻纹铜匝残片 人物鸟兽纹','战国刻纹铜匜残片','战国铜 鉴']:
            self.assertEqual(material(name)['label'],'铜')

    def test_depicted_materials_and_surface_treatments_are_not_substrates(self):
        self.assertEqual(material('鹳鸟衔鱼石斧纹彩陶缸')['label'],'陶')
        self.assertEqual(material('鎏金铜鉴')['label'],'铜')
        self.assertIsNone(material('鎏金佛像'))
        self.assertEqual(material('金鱼纹铜镜')['label'],'铜')
        self.assertEqual(material('西汉铜贮贝器 人物牛马纹')['label'],'铜')
        self.assertIsNone(material('汉代贮贝器 虎牛鹿纹'))

    def test_ambiguous_names_do_not_assign_a_material(self):
        for name in ['金鱼纹','仿铜镜','金银器','铜镜玉佩']:
            self.assertIsNone(material(name))


if __name__=='__main__':unittest.main()
