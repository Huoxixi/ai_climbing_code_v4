import tempfile
import unittest
from pathlib import Path
import numpy as np

from core.photo_route_instance_masks import encode_mask,decode_mask
from core.photo_route_evaluation import evaluate_objects,mask_for_object
from scripts.run_climbing_instance_model import export_instances


class InstanceMaskTests(unittest.TestCase):
    def test_round_trip_preserves_holes_and_disconnected_objects(self):
        mask=np.zeros((80,100),np.uint8);mask[10:40,10:40]=1;mask[20:30,20:30]=0;mask[60:70,80:90]=1
        encoded=encode_mask(mask)
        np.testing.assert_array_equal(mask,decode_mask(encoded,mask.shape))
        obj={'kind':'hold','mask_rle':encoded,'contour':[[10,10],[40,10],[40,40]]}
        np.testing.assert_array_equal(mask,mask_for_object(obj,mask.shape))
        self.assertEqual(evaluate_objects([obj],[obj],mask.shape)['ious'],[1.0])

    def test_bad_encoding_counts_and_bounds_are_rejected(self):
        encoded=encode_mask(np.ones((10,10),np.uint8))
        for changes in [{'counts':[0,99]},{'counts':[0,-100]},{'origin':[95,0]}, {'encoding':'other'}]:
            with self.assertRaises(ValueError):decode_mask({**encoded,**changes},(100,100))

    def test_model_export_preserves_native_mask_and_class_confidence(self):
        image=np.full((80,100,3),[200,70,30],np.uint8)
        mask=np.zeros((80,100),np.uint8);mask[10:40,10:40]=1;mask[20:30,20:30]=0;mask[60:70,80:90]=1
        with tempfile.TemporaryDirectory() as tmp:
            objects,empty=export_instances(image,[mask],[1],[.85],Path(tmp),'interior-v3')
            self.assertEqual(empty,0);self.assertEqual(objects[0]['kind'],'volume')
            self.assertEqual(objects[0]['confidence'],.85);self.assertEqual(objects[0]['component_count'],2)
            np.testing.assert_array_equal(decode_mask(objects[0]['mask_rle'],mask.shape),mask)

    def test_export_rejects_unmapped_classes_and_nonoriginal_size(self):
        image=np.zeros((80,100,3),np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):export_instances(image,[np.ones((80,100))],[3],[.8],Path(tmp),'interior-v3')
            with self.assertRaises(ValueError):export_instances(image,[np.ones((40,50))],[0],[.8],Path(tmp),'interior-v3')
