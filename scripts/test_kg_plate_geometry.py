"""Regressions for complete-object crops and numbered multi-view plates."""
import unittest

import numpy as np

from kg_v2.plate_regions import complete_regions, deduplicate_labels, nearest_groups


def label(item, box):
    return {'item': item, 'bbox': box, 'score': .99}


class PlateGeometryTest(unittest.TestCase):
    def test_adjacent_figures_pair_independently_instead_of_consuming_a_column(self):
        boxes = [[100, 100, 400, 400], [500, 100, 800, 400], [100, 500, 400, 800]]
        numbers = [label(1,[390,420,410,450]), label(2,[790,420,810,450]), label(3,[390,820,410,850])]
        groups, missing, _, _ = nearest_groups(boxes,numbers,1000,1400)
        self.assertEqual(groups,{1:[0],2:[1],3:[2]})
        self.assertEqual(missing,[])

    def test_one_caption_can_cover_multiple_rows_of_hairpins(self):
        boxes = [[100,100,160,500],[180,100,240,500],[100,550,160,950],
                 [550,100,900,500],[550,550,900,900]]
        groups,missing,_,_=nearest_groups(boxes,[label(1,[300,960,320,980]),
                                               label(2,[900,910,920,930])],1000,1400)
        self.assertEqual(groups,{1:[0,1,2],2:[3,4]})
        self.assertEqual(missing,[])

    def test_digit_one_inside_ten_and_outer_page_number_do_not_duplicate_labels(self):
        numbers=[label(1,[800,1200,810,1230]),label(10,[800,1200,840,1230]),
                 label(5,[970,650,990,680])]
        self.assertEqual([r['item'] for r in deduplicate_labels(numbers,1000,1400)],[10])

    def test_long_internal_shafts_are_not_removed_as_table_rules(self):
        gray=np.full((1400,1000),255,dtype=np.uint8)
        gray[180:1050,300:312]=30
        layout={'raw':{'width':1000,'height':1400,'layout_det_res':{'boxes':[]}}}
        regions=complete_regions(gray,[],[label(1,[310,1070,330,1100])],layout)
        self.assertTrue(any(b[0]<=300 and b[2]>=312 and b[1]<=180 and b[3]>=1050 for b in regions))

    def test_unrecorded_figure_numbers_still_keep_images_from_neighboring_captions(self):
        boxes=[[100,100,800,400],[100,500,400,850],[550,500,800,850]]
        groups,_,_,_=nearest_groups(boxes,[label(1,[790,420,810,450]),
                                         label(2,[390,870,410,900]),
                                         label(3,[790,870,810,900])],1000,1400)
        self.assertEqual(groups,{1:[0],2:[1],3:[2]})


if __name__=='__main__':
    unittest.main()
