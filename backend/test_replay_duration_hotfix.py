import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import cv2
import numpy as np
from core.replay_actions import organize
from core.replay_action_renderer import make_plan, validate, render_actions
from core.replay_template_renderer import _render
from test_replay_actions import evidence, ActionLifecycleTests
from core.replay_vision_settings import save_settings, VisionSettings
from core.replay_commentary import VERSION

class ReplayDurationHotfixTests(unittest.TestCase):
    def test_legacy_summary_tail_does_not_invalidate_source_actions(self):
        result=organize({'result':evidence()})
        for speed in (1,.75,.5):
            plan=make_plan(result,speed=speed,base_video={**result['video'],'frame_count':32})
            self.assertEqual(plan['source_duration_seconds'],6)
            self.assertEqual(plan['source_media_duration_seconds'],8)
            self.assertEqual(plan['source_stop_frame'],24)
            self.assertEqual(validate(plan),int(24/speed))
        bad=copy.deepcopy(plan);bad['source_media_duration_seconds']=float('nan')
        with self.assertRaises(ValueError):validate(bad)
        bad=copy.deepcopy(plan);bad['source_media_duration_seconds']=1
        with self.assertRaises(ValueError):validate(bad)

    def test_real_encode_excludes_summary_tail_and_still_detects_wrong_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'base.mp4'
            writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'mp4v'),4,(96,64))
            self.assertTrue(writer.isOpened())
            for i in range(32):writer.write(np.full((64,96,3),30 if i<24 else 230,np.uint8))
            writer.release(); original=source.read_bytes()
            result=organize({'result':evidence()})
            plan=make_plan(result,speed=1,base_video={**result['video'],'frame_count':32})
            encoded=render_actions(source,plan,root/'actions.mp4')
            self.assertTrue(encoded['fully_decoded']);self.assertEqual(encoded['frame_count'],24)
            cap=cv2.VideoCapture(str(root/'actions.mp4'));cap.set(cv2.CAP_PROP_POS_FRAMES,23)
            ok,last=cap.read();cap.release();self.assertTrue(ok);self.assertLess(last.mean(),80)
            self.assertEqual(source.read_bytes(),original)
            wrong=make_plan(result,speed=1,base_video={**result['video'],'frame_count':36})
            from core.replay_action_renderer import ActionComposition
            with self.assertRaisesRegex(ValueError,'Source duration'):
                _render(source,wrong,root/'wrong.mp4',root/'metrics.json',composition_factory=ActionComposition,validator=validate)
            self.assertFalse((root/'wrong.mp4').exists())

    def test_commentary_success_does_not_depend_on_video_rendering(self):
        fixture=ActionLifecycleTests();fixture.setUp();self.addCleanup(fixture.tearDown)
        save_settings(fixture.store.root.parent,'alice',VisionSettings(base_url='https://vision.invalid/v1',model='test',api_key='synthetic-key'))
        def run(source,job,result,**kwargs):
            kwargs['usage_callback']({'request_id':'test','stage':'action_commentary','status':'succeeded','usage_complete':True,'usage':{}})
            return result
        engine=Mock();engine.run.side_effect=run
        fixture.manager.renderer=Mock(side_effect=RuntimeError('synthetic-key'))
        with patch('core.replay_action_jobs.VisionCommentaryEngine',return_value=engine):
            response=fixture.client.post(fixture.url,json={'cloud_consent':True,'consent_version':VERSION,'budget_confirmed':True})
            self.assertEqual(response.status_code,202)
            failed=fixture.wait()
        self.assertEqual(failed['task']['status'],'succeeded')
        fixture.manager.renderer.assert_not_called()
        self.assertNotIn('synthetic-key',json.dumps(failed))

if __name__=='__main__':unittest.main()
