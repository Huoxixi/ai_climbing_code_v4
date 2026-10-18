"""Prevent misleading scores when comparing native poses with draft labels."""
import unittest

from scripts.compare_ai_wrist_drafts import compare_joint, summarize


def task(left=None, right=None, visibility='visible'):
    return {'case':'test','source_frame_id':42,'time_seconds':1.4,'source_sha256':'bound-source',
            'joints':{'left_wrist':{'xy_px':left,'visibility':visibility,'visual_radius_px':6,'note':'draft'},
                      'right_wrist':{'xy_px':right,'visibility':'visible' if right else 'occluded','visual_radius_px':6 if right else None,'note':'draft'}},
            'hand_regions':{'left':{},'right':{}}}


def record(left, eligible=True):
    points=[[1.,1.] for _ in range(17)];points[9]=left
    return {'joint_observations':{'raw_xy_px':points,'raw_response':[2.5]*17},
            'kpts_xy':[[.9,.9]]*17, 'joint_eligibility':[eligible]*17,
            'pose_evidence':{'observed':True}}


class DraftDisagreementTests(unittest.TestCase):
    def test_raw_source_pixels_and_native_response_are_preserved(self):
        result=compare_joint(task([100,200]),'left',9,record([103,204]))
        self.assertEqual(result['distance_to_ai_draft_px'],5)
        self.assertEqual(result['model_native_response'],2.5)
        self.assertFalse(result['reference_human_reviewed'])
        self.assertEqual(result['interpretation'],'AI_draft_disagreement_not_accuracy')

    def test_hidden_reference_never_receives_a_location_score(self):
        result=compare_joint(task(None,visibility='occluded'),'left',9,record([103,204]))
        self.assertIsNone(result['distance_to_ai_draft_px'])
        self.assertTrue(result['prediction_on_unlocalizable_reference'])
        self.assertEqual(result['interpretation'],'wrist_location_not_scorable')

    def test_missing_prediction_stays_in_the_locatable_denominator(self):
        result=summarize([compare_joint(task([100,200]),'left',9,None)])
        self.assertEqual(result['ai_locatable_denominator'],1)
        self.assertEqual(result['missing_native_on_ai_locatable'],1)
        self.assertIsNone(result['mean_disagreement_px'])

    def test_ineligible_prediction_is_not_counted_as_covered(self):
        row=compare_joint(task([100,200]),'left',9,record([103,204],False))
        self.assertEqual(row['distance_to_ai_draft_px'],5)
        result=summarize([row])
        self.assertEqual(result['eligible_locations_on_ai_locatable'],0)
        self.assertEqual(result['missing_or_ineligible_on_ai_locatable'],1)

    def test_missing_values_do_not_lower_the_mean_disagreement(self):
        rows=[compare_joint(task([100,200]),'left',9,record([103,204])),
              compare_joint(task([100,200]),'left',9,None)]
        result=summarize(rows)
        self.assertEqual(result['mean_disagreement_px'],5)
        self.assertEqual(result['ai_locatable_denominator'],2)
        self.assertFalse(result['accuracy_claim'])

    def test_opposite_draft_advisory_does_not_reassign_the_side(self):
        row=compare_joint(task([100,200],[200,300]),'left',9,record([201,301]))
        self.assertTrue(row['opposite_draft_closer_by_20px'])
        self.assertEqual(row['side'],'left')
        self.assertEqual(row['reference_xy_px'],[100,200])

    def test_nonfinite_native_point_is_missing_not_zero_error(self):
        row=compare_joint(task([100,200]),'left',9,record([float('nan'),204]))
        self.assertIsNone(row['model_xy_px'])
        self.assertIsNone(row['distance_to_ai_draft_px'])
        self.assertFalse(row['model_eligible'])

    def test_hand_fragment_separation_is_distinct_from_wrist_error(self):
        ref=task(None,visibility='occluded')
        ref['hand_regions']['left']['visible_hand_box_xyxy_px']=[100,100,120,120]
        row=compare_joint(ref,'left',9,record([123,124]))
        self.assertEqual(row['distance_to_visible_fragment_box_px'],5)
        self.assertIsNone(row['distance_to_ai_draft_px'])


if __name__=='__main__':
    unittest.main()
