"""Fixed audit failures: display/contact agreement and persistent identity conflicts."""
import copy
import unittest
import numpy as np
from core.climb_replay import AliyunReplayAnalyzer
from core.replay_action_trajectory import registered_points
from core.replay_hold_fusion import align_pose_record
from core.replay_pose_rtmw import LocalRTMWReplayAnalyzer


class ObservationValidityTests(unittest.TestCase):
    def test_same_frame_consensus_keeps_fast_high_step_without_old_endpoint_anchor(self):
        from core.replay_pose_context import consensus_retry
        points=np.zeros((17,2))+.5
        for j,xy in {5:[.4,.3],6:[.6,.3],7:[.3,.2],8:[.7,.2],9:[.2,.1],10:[.8,.1],
                     11:[.4,.6],12:[.6,.6],13:[.3,.55],14:[.7,.75],15:[.25,.4],16:[.7,.9]}.items(): points[j]=xy
        scores=np.ones(17)*.9
        wrong=points.copy(); wrong[9]=points[15]; wrong[15]=points[9]
        proposal={'scale':100.,'previous':wrong*200}
        self.assertTrue(consensus_retry(proposal,[(points,scores),(points,scores)],wrong,[200,200]))
        disagree=points.copy(); disagree[15]=[.7,.1]
        self.assertFalse(consensus_retry(proposal,[(points,scores),(disagree,scores)],wrong,[200,200]))

    def test_audit_boundaries_agree_and_preserve_source(self):
        for error,score,expected in ((3.2,.9,False),(0,.2,False),(3,.9,True),(0,.9,True)):
            source={'observed':True,'wall_alignment':'aligned',
                    'wall_reference_transform':np.eye(3).tolist(),
                    'wall_alignment_diagnostics':{'median_error_px':error,'inliers':20},
                    'kpts_xy':[[.5,.5]]*17,'kpts_score':[score]*17}
            original=copy.deepcopy(source)
            mapped=registered_points(source,{'width':100,'height':100})
            supported=mapped is not None and bool(mapped[1][9])
            records=[align_pose_record({**source,'frame_id':i,'source_frame_id':i},np.eye(3),100,100) for i in range(10)]
            attempt=AliyunReplayAnalyzer._contacts(records,[{'id':1,'bbox':[.4,.4,.2,.2]}],10)
            self.assertEqual(supported,expected)
            self.assertEqual(bool(attempt['contacts']),expected)
            self.assertEqual(source,original)

    def test_route_conflict_recovers_but_one_frame_swing_keeps_identity(self):
        analyzer=LocalRTMWReplayAnalyzer()
        analyzer._route_bounds=[.4,.2,.7,.8]
        analyzer._previous_box=np.array([0,20,20,90],float)
        analyzer._previous_source_frame=0
        boxes=[[0,20,20,90],[40,20,70,90]]
        for source in (3,6):
            analyzer._current_source_frame=source
            box,reason=analyzer._select_box(boxes,100,100)
            self.assertEqual(reason,'iou_follow')
        analyzer._current_source_frame=9
        box,reason=analyzer._select_box(boxes,100,100)
        self.assertEqual(reason,'route_conflict_reselected')
        self.assertEqual(box.tolist(),boxes[1])
        self.assertEqual(analyzer.selection_evidence['observations'],3)

    def test_missing_rival_resets_conflict_and_cannot_switch_on_stale_evidence(self):
        analyzer=LocalRTMWReplayAnalyzer()
        analyzer._route_bounds=[.4,.2,.7,.8]
        analyzer._previous_box=np.array([0,20,20,90],float)
        analyzer._previous_source_frame=0
        for frame,boxes in ((3,[[0,20,20,90],[40,20,70,90]]),(6,[[0,20,20,90]]),(9,[[0,20,20,90],[40,20,70,90]])):
            analyzer._current_source_frame=frame
            self.assertEqual(analyzer._select_box(boxes,100,100)[1],'iou_follow')
        self.assertEqual(analyzer.selection_evidence['observations'],1)
