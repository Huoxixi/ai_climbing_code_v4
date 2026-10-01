import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import cv2
import numpy as np
from pydantic import ValidationError

from core.climb_replay import AliyunReplayAnalyzer, ClimbReplayStore, ReplayUploadCreate, parse_color_sample


class ReplayColorSampleTests(unittest.TestCase):
    def payload(self, sample):
        return ReplayUploadCreate(
            filename='attempt.mp4', content_type='video/mp4', size_bytes=1024,
            route_color='青色', consent_version='test-consent', consent_granted=True,
            route_color_sample=sample,
        )

    def test_video_sample_is_validated_and_serializable(self):
        value=self.payload({'source':'video','hex':'#20a6a6','rgb':[32,166,166],'time_seconds':2.35})
        self.assertEqual(value.route_color_sample.rgb,[32,166,166])
        self.assertEqual(parse_color_sample(value.route_color_sample)['source'],'video')

    def test_invalid_hex_or_rgb_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.payload({'source':'palette','hex':'20a6a6','rgb':[32,166,166]})
        with self.assertRaises(ValidationError):
            self.payload({'source':'palette','hex':'#20a6a6','rgb':[32,166,999]})
        with self.assertRaises(ValidationError):
            self.payload({'source':'video','hex':'#20a6a6','rgb':[32,166,166],
                          'point_xy':[1.2,.5]})
        with self.assertRaises(ValidationError):
            self.payload({'source':'video','hex':'#20a6a6','rgb':[32,166,166],
                          'point_xy':[.2,.5]})

    def test_missing_sample_remains_backward_compatible(self):
        self.assertIsNone(self.payload(None).route_color_sample)
        self.assertIsNone(parse_color_sample(None))

    def test_pending_job_persists_the_sample_without_touching_history(self):
        sample={'source':'video','hex':'#20a6a6','rgb':[32,166,166],'time_seconds':2.35}
        with TemporaryDirectory() as folder:
            source=Path(folder)/'source.mp4'; source.write_bytes(b'video')
            job=ClimbReplayStore(Path(folder)/'replays').create_pending(
                owner='owner',route_id=None,route_color='青色',route_color_sample=sample,
                source=source,original_name='source.mp4',content_type='video/mp4',
                consent={'event':'granted'},retention_mode='delete_after_processing',
            )
            self.assertEqual(job['route_color_sample'],sample)

    def test_saved_route_reference_is_private_to_worker(self):
        with TemporaryDirectory() as folder:
            source=Path(folder)/'source.mp4'; source.write_bytes(b'video')
            store=ClimbReplayStore(Path(folder)/'replays')
            job=store.create_pending(
                owner='owner',route_id='route',route_color='青色',
                saved_route_reference={'board_id':'test-board','asset_path':'private-photo','members':[]},
                source=source,original_name='source.mp4',content_type='video/mp4',
                consent={'event':'granted'},retention_mode='delete_after_processing')
            self.assertNotIn('saved_route_reference',job)
            self.assertEqual(store.get(job['id'],private=True)['saved_route_reference']['asset_path'],'private-photo')

    def test_video_sample_drives_hold_matching_instead_of_the_preset_label(self):
        image=np.zeros((100,200,3),np.uint8)
        cyan=cv2.cvtColor(np.uint8([[[90,170,190]]]),cv2.COLOR_HSV2BGR)[0,0]
        red=cv2.cvtColor(np.uint8([[[2,180,190]]]),cv2.COLOR_HSV2BGR)[0,0]
        image[20:80,20:80]=cyan; image[20:80,120:180]=red
        cyan_mask=np.zeros((100,200),np.uint8); cyan_mask[20:80,20:80]=255
        red_mask=np.zeros((100,200),np.uint8); red_mask[20:80,120:180]=255
        sample_rgb=cv2.cvtColor(np.uint8([[cyan]]),cv2.COLOR_BGR2RGB)[0,0].tolist()
        with patch('core.climb_replay._climbing_model_masks_batch',return_value=([([cyan_mask,red_mask],[.9,.9])],'test-model')):
            holds,candidates,_,_,_=AliyunReplayAnalyzer._video_holds(
                frames=[(0,image)],route_color='红色',
                route_color_sample={'source':'palette','hex':'#20a6a6','rgb':sample_rgb,'time_seconds':1.0},
                saved_route_reference=None,deadline=10**12,progress=lambda *_:None,cancelled=lambda:False,
            )
        self.assertEqual(len(holds),1)
        self.assertEqual(len(candidates),1)
        self.assertEqual(holds[0]['color_group'],'青色')
        self.assertEqual(holds[0]['color_source'],'palette')


if __name__ == '__main__':
    unittest.main()
