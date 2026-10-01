import copy
import unittest
from core.replay_pose_comparison import normalize, compare, COCO_TO_MP


class PoseComparisonTests(unittest.TestCase):
    def document(self):
        return {'source_sha256':'constructed', 'layout':'coco17','coordinate_space':'image_normalized','native_joint_count':17,
                'samples':[{'time_seconds':1,'observed':True,'kpts_xy':[[.1+i*.02,.5] for i in range(17)],'kpts_score':[.9]*17}]}

    def test_anatomical_mapping_and_zero_filled_slots(self):
        sample=self.document()['samples'][0]
        mp={'observed':True,'time_seconds':1,'kpts_xy':[[0,0] for _ in range(33)],'kpts_score':[0]*33}
        for i,target in enumerate(COCO_TO_MP):
            mp['kpts_xy'][target]=sample['kpts_xy'][i]; mp['kpts_score'][target]=.9
        normalized=normalize(mp,'mediapipe33',17)
        self.assertEqual(normalized['common17'],sample['kpts_xy'])
        self.assertEqual(normalized['foot_details'],{})
        self.assertIsNone(normalize(mp,'mediapipe33',33)['foot_details']['left_heel'])

    def test_unobserved_points_are_not_recovered(self):
        sample=self.document()['samples'][0];sample['observed']=False
        self.assertEqual(normalize(sample)['common17'],[None]*17)

    def test_missing_backend_and_self_comparison_are_not_accuracy(self):
        doc=self.document()
        self.assertFalse(compare(doc)['secondary_available'])
        result=compare(doc,copy.deepcopy(doc))
        self.assertEqual(result['mean_common_joint_distance'],0)
        self.assertFalse(result['accuracy_established'])

    def test_different_source_and_pixels_are_rejected(self):
        doc=self.document()
        with self.assertRaises(ValueError):compare(doc,{**doc,'source_sha256':'different'})
        with self.assertRaises(ValueError):compare({**doc,'coordinate_space':'pixels'})


if __name__=='__main__':unittest.main()
