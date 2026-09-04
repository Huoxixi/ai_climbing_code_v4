import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from core.photo_route_processing import PhotoProcessingError
from core.photo_wall_processing import prepare_repair_mask, composite_wall, restore_wall
from scripts.benchmark_photo_wall import reviewed_masks
from scripts.evaluate_photo_routes import result_fingerprint


class PhotoWallTests(unittest.TestCase):
    def scene(self):
        image=np.full((100,160,3),180,np.uint8)
        target=np.zeros((100,160),np.uint8)
        other=np.zeros_like(target)
        target[30:50,25:45]=255
        other[40:65,100:125]=255
        image[target>0]=(0,220,245)
        image[other>0]=(100,0,180)
        return image,target,other

    def test_target_is_exact_and_wall_layer_has_no_baked_target(self):
        image,target,other=self.scene()
        original=image.copy()
        repair=prepare_repair_mask(image,other|target,target,margin=4)
        prediction=np.full_like(image,200)
        result=composite_wall(image,repair,target,prediction)
        np.testing.assert_array_equal(result.composite[target>0],image[target>0])
        self.assertTrue(np.all(result.background[target>0]==200))
        np.testing.assert_array_equal(result.composite[repair==0],image[repair==0])
        np.testing.assert_array_equal(image,original)
        self.assertTrue(np.all(result.display_repair_mask[target>0]==0))

    def test_preserved_person_is_not_erased_by_mask_or_shadow_margin(self):
        image,target,other=self.scene()
        person=np.zeros_like(target)
        person[40:65,100:108]=255
        repair=prepare_repair_mask(image,other,target,margin=8,preserve_mask=person)
        self.assertFalse(np.any(repair[person>0]))
        self.assertTrue(np.any(repair[other>0]))

    def test_invalid_or_empty_target_and_overbroad_selection_fail(self):
        image,target,other=self.scene()
        for removal,selected in [(other[:50],target),(other,np.zeros_like(target)),
                                 (np.ones_like(other)*255,target),(other.astype(float),target)]:
            with self.subTest(shape=removal.shape),self.assertRaises(PhotoProcessingError):
                prepare_repair_mask(image,removal,selected)

    def test_local_baseline_preserves_target_and_source(self):
        image,target,other=self.scene()
        before=image.copy()
        result=restore_wall(image,other,target,working_edge=256)
        np.testing.assert_array_equal(result.composite[target>0],before[target>0])
        np.testing.assert_array_equal(image,before)
        self.assertFalse(np.array_equal(result.composite[other>0],before[other>0]))

    def test_missing_model_fails_without_fallback_or_download(self):
        image,target,other=self.scene()
        with tempfile.TemporaryDirectory() as root,self.assertRaisesRegex(PhotoProcessingError,'缺少本地'):
            restore_wall(image,other,target,method='lama',checkpoint=Path(root)/'absent.pt')

    def test_failed_prediction_cannot_be_composited(self):
        image,target,other=self.scene()
        with self.assertRaises(PhotoProcessingError):
            composite_wall(image,other,target,np.zeros((1,1,3),np.uint8))

    def test_review_is_bound_to_source_and_saved_masks(self):
        image,target,other=self.scene()
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);route=root/'route';scene=root/'scene'
            route.mkdir();scene.mkdir()
            reports=[]
            for folder,mask in [(route,target),(scene,other)]:
                encoded=cv2.imencode('.png',mask)[1].tobytes()
                (folder/'object-01-mask.png').write_bytes(encoded)
                report={'source_sha256':'photo','algorithm':'test','objects':[
                    {'id':'object-01','mask_sha256':hashlib.sha256(encoded).hexdigest()}]}
                (folder/'report.json').write_text(json.dumps(report),'utf-8')
                reports.append(report)
            review={'source_sha256':'photo','route_result_sha256':result_fingerprint(reports[0]),
                    'scene_report_sha256':hashlib.sha256((scene/'report.json').read_bytes()).hexdigest(),
                    'target_ids':['object-01'],'remove_ids':['object-01']}
            got_target,got_removal,_=reviewed_masks(image,'photo',route,scene,review)
            np.testing.assert_array_equal(target,got_target)
            np.testing.assert_array_equal(other,got_removal)
            with self.assertRaisesRegex(ValueError,'same original'):
                reviewed_masks(image,'another-photo',route,scene,review)
            (scene/'object-01-mask.png').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'mask changed'):
                reviewed_masks(image,'photo',route,scene,review)


if __name__=='__main__':unittest.main()
