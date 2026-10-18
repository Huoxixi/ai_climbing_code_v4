import copy
import unittest
import numpy as np
from core.replay_foot_points import registered_feet,interpolate_feet
from core.replay_analysis_view import AnalysisView,visual_evidence
from test_replay_segments_and_analysis_view import scene

class FootPointsTests(unittest.TestCase):
    def sample(self):
        sample=scene()['pose_samples'][0]
        sample['wholebody']={'schema':'coco-wholebody-133','coordinates':'source_image_normalized',
            'kpts_xy':[[.4,.8]]*133,'kpts_score':[.9]*133}
        sample['wall_reference_transform']=[[1,0,9.6],[0,1,0],[0,0,1]]
        return sample

    def test_toes_follow_same_registration_and_source_stays_unchanged(self):
        sample=self.sample(); before=copy.deepcopy(sample)
        feet=registered_feet(sample,scene()['video'])
        np.testing.assert_allclose(feet['kpts_xy'][1],[.5,.8])
        np.testing.assert_allclose(feet['kpts_xy'][0],[.4,.9])
        self.assertEqual(sample,before)

    def test_missing_weak_and_failed_registration_never_invent_feet(self):
        sample=self.sample();sample['wholebody']['kpts_score'][17]=.2
        feet=registered_feet(sample,scene()['video']);self.assertEqual(feet['kpts_score'][1],0)
        right=copy.deepcopy(feet);right['kpts_score'][2]=0
        middle=interpolate_feet(feet,right,.5)
        self.assertEqual(middle['kpts_score'][2],0)
        self.assertIsNone(interpolate_feet(feet,None,.5))
        sample['observed']=False
        self.assertIsNone(registered_feet(sample,scene()['video']))

    def test_export_branches_exist_only_on_supported_observations(self):
        result=scene(); result['pose_samples']=[self.sample()]
        evidence=visual_evidence(result)
        self.assertIsNotNone(evidence['pose_samples'][0]['feet'])
        view=AnalysisView(result)
        self.assertIsNotNone(view.timeline[0]['feet'])
        self.assertNotIn(1,view.timeline)
        result['pose_samples'][0].pop('wholebody')
        self.assertIsNone(visual_evidence(result)['pose_samples'][0]['feet'])

if __name__=='__main__':unittest.main()
