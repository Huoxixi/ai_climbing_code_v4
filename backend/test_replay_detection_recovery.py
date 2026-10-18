"""Detector configuration and identity-safe weak observation regressions."""
import unittest
import numpy as np

from vendor.rtmlib import YOLOX
from core.replay_person_tracks import ClipPersonTracks


def row(box=(.2, .2, .5, .8), score=.8, colour=(1., 0.)):
    return {'box':list(box), 'box_xyxy_px':(np.array(box)*100).tolist(),
            'association_box':list(box), 'appearance':list(colour), 'detector_score':score}


class ScoredDetectorTests(unittest.TestCase):
    def detector(self, threshold):
        detector=object.__new__(YOLOX)
        detector.score_thr=threshold
        detector.det_mode='human'
        return detector

    def test_native_nms_threshold_is_configurable_and_scores_align_with_boxes(self):
        raw=np.array([[[10,20,40,60,.2198],[0,0,0,0,0],[30,30,60,90,.8]]])
        saved=raw.copy()
        detector=self.detector(.35)
        self.assertEqual(len(detector.postprocess(raw, .5)),1)
        boxes,scores=detector.postprocess(raw,.5,score_thr=.1,return_scores=True)
        np.testing.assert_allclose(boxes,[[20,40,80,120],[60,60,120,180]])
        np.testing.assert_allclose(scores,[.2198,.8])
        np.testing.assert_array_equal(raw,saved)
        self.assertEqual(detector.score_thr,.35)
        self.assertEqual(len(detector.postprocess(raw,.5)),1)

    def test_zero_nan_and_degenerate_native_boxes_cannot_reach_tracking(self):
        raw=np.array([[[0,0,0,0,.8],[1,1,2,2,float('nan')],[1,1,2,2,.1]]])
        boxes,scores=self.detector(.1).postprocess(raw,return_scores=True)
        self.assertEqual(boxes.shape,(0,4))
        self.assertEqual(scores.shape,(0,))

    def test_packed_output_cannot_invent_multiclass_labels(self):
        detector=self.detector(.1);detector.det_mode='multiclass'
        with self.assertRaisesRegex(NotImplementedError,'no class IDs'):
            detector.postprocess(np.array([[[1,1,2,2,.8]]]))


class LowScoreIdentityTests(unittest.TestCase):
    def test_weak_real_observation_continues_existing_identity_only(self):
        tracks=ClipPersonTracks(low_score_recovery=True)
        tracks.add_frame(0,0,[row()])
        tracks.add_frame(3,.1,[row(score=.2198),row((.7,.1,.9,.5),.2)])
        tracks.add_frame(6,.2,[row()])
        self.assertEqual(len(tracks.tracks),1)
        tracks.select_target()
        actual=tracks.target_observation(3)
        self.assertEqual(actual['track_id'],1)
        self.assertEqual(actual['detector_score'],.2198)
        self.assertEqual(actual['detection_recovery'],'low_score_existing_track')

    def test_weak_detection_cannot_start_a_track_or_fill_a_missing_frame(self):
        tracks=ClipPersonTracks(low_score_recovery=True)
        tracks.add_frame(0,0,[row(score=.2)])
        tracks.add_frame(3,.1,[row()])
        tracks.add_frame(6,.2,[])
        tracks.select_target()
        self.assertIsNone(tracks.target_observation(0))
        self.assertIsNone(tracks.target_observation(6))

    def test_high_score_identity_assignment_precedes_weak_duplicate(self):
        tracks=ClipPersonTracks(low_score_recovery=True)
        tracks.add_frame(0,0,[row()])
        tracks.add_frame(3,.1,[row(score=.2),row((.22,.2,.52,.8),.7)])
        tracks.select_target()
        self.assertEqual(tracks.target_observation(3)['detector_score'],.7)
        self.assertEqual(len(tracks.tracks),1)

    def test_wrong_appearance_and_distant_weak_boxes_remain_missing(self):
        tracks=ClipPersonTracks(low_score_recovery=True)
        tracks.add_frame(0,0,[row()])
        tracks.add_frame(3,.1,[row(score=.2,colour=(0.,1.)),row((.7,.1,.9,.5),.2)])
        tracks.select_target()
        self.assertIsNone(tracks.target_observation(3))

    def test_second_stage_is_one_to_one(self):
        tracks=ClipPersonTracks(low_score_recovery=True)
        tracks.add_frame(0,0,[row(),row((.3,.2,.6,.8))])
        tracks.add_frame(3,.1,[row((.25,.2,.55,.8),.2)])
        self.assertEqual(len(tracks.frames[3]['observations']),1)
        self.assertEqual(sum(len(t.observations)==2 for t in tracks.tracks),1)

    def test_weak_recovery_uses_source_space_when_registration_disappears(self):
        tracks=ClipPersonTracks(low_score_recovery=True)
        for f in (0,3):
            observed=row();observed.update(association_box=[.01,.01,.1,.2],association_space='reference')
            tracks.add_frame(f,f/30,[observed])
        observed=row(score=.2);observed['association_space']='source'
        tracks.add_frame(6,.2,[observed]);tracks.select_target()
        self.assertIsNotNone(tracks.target_observation(6))

    def test_weak_box_cannot_revive_expired_track(self):
        tracks=ClipPersonTracks(low_score_recovery=True)
        tracks.add_frame(0,0,[row()])
        tracks.add_frame(60,2,[row(score=.2)])
        tracks.select_target()
        self.assertIsNone(tracks.target_observation(60))


if __name__=='__main__':unittest.main()
