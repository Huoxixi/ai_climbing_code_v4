import copy
import os
import shutil
import tempfile
import unittest
from dataclasses import asdict
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import HTTPException, FastAPI, Request
from fastapi.testclient import TestClient

from core.climb_replay import ClimbReplayStore, VideoInfo, ReplayHoldPoint, ClimbReplayManager, create_climb_replay_router
from core.replay_hold_editor import (EditorFrameRequest, EditorPreviewRequest, editor_frame,
    editor_preview, editor_commit, validate_polygon, clear_editor_cache, cancel_editor_request)


class HoldEditorTests(unittest.TestCase):
    def test_closed_region_detects_only_inside_and_excludes_existing_contour(self):
        from core.replay_hold_editor import _frames
        image=np.full((96,128,3),(180,205,220),np.uint8)
        cv2.rectangle(image,(42,40),(57,56),(170,125,20),-1)
        cv2.rectangle(image,(58,40),(70,56),(170,125,20),-1)
        self.draft['holds']=[{'id':1,'polygon':[[42/128,40/96],[57/128,40/96],[57/128,56/96],[42/128,56/96]],'bbox':[42/128,40/96,15/128,16/96]}]
        self.store.update(self.job['id'],hold_draft=self.draft)
        self.frame=editor_frame(self.store,self.job['id'],'alice',EditorFrameRequest())
        _frames[self.frame['frame_token']]['png']=cv2.imencode('.png',image)[1].tobytes()
        boundary=[[38/128,35/96],[74/128,35/96],[74/128,61/96],[38/128,61/96]]
        value=editor_preview(self.store,self.job['id'],'alice',EditorPreviewRequest(
            frame_token=self.frame['frame_token'],mode='region',polygon=boundary))['candidates'][0]
        self.assertGreaterEqual(min(p[0] for p in value['source_polygon']),58/128)
        self.assertLessEqual(max(p[0] for p in value['source_polygon']),74/128)
        self.assertNotEqual(value['source_polygon'],boundary,'selection boundary is not the hold contour')
        self.assertEqual(self.store.get(self.job['id'],'alice',private=True)['hold_draft'],self.draft)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        source = self.root / "clip.mp4"
        writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 5, (128, 96))
        if not writer.isOpened():
            self.skipTest("MP4 writer unavailable")
        frame = np.random.default_rng(8).integers(0, 255, (96, 128, 3), dtype=np.uint8)
        for _ in range(10):
            writer.write(frame)
        writer.release()
        self.info = VideoInfo(128, 96, 5, 10, 2, source.stat().st_size)
        self.store = ClimbReplayStore(self.root / "store")
        self.job = self.store.create(owner="alice", route_id=None, route_color="黄色", source=source,
            original_name="clip.mp4", info=self.info, consent={}, retention_mode="keep_private_original")
        self.draft = {"holds": [], "hold_candidates": [], "hold_evidence": {"reference_frame": 0}}
        self.store.update(self.job["id"], status="awaiting_hold_review", hold_draft=self.draft)
        self.frame = editor_frame(self.store, self.job["id"], "alice", EditorFrameRequest())
        self.polygon = [[.2, .2], [.35, .2], [.35, .35], [.2, .35]]

    def tearDown(self):
        if hasattr(self, "store"):
            clear_editor_cache(self.store, self.job["id"])
        self.temp.cleanup()

    def preview(self, **kwargs):
        return editor_preview(self.store, self.job["id"], "alice", EditorPreviewRequest(
            frame_token=self.frame["frame_token"], mode="manual", polygon=self.polygon, **kwargs))["candidates"][0]

    def test_manual_preview_is_read_only_commit_is_exact_and_invalidates_confirmation(self):
        before = self.store.get(self.job["id"], "alice", private=True)
        proposal = self.preview()
        self.assertEqual(before, self.store.get(self.job["id"], "alice", private=True))
        self.store.update(self.job["id"], holds_confirmation={"revision": self.frame["holds_revision"]})
        with patch("core.climb_replay.render_replay_overlay_video", side_effect=AssertionError("no render")), \
             patch("core.climb_replay._climbing_model_masks_batch", side_effect=AssertionError("no inference")):
            changed = editor_commit(self.store, self.job["id"], "alice", proposal["proposal_id"])
        hold = changed["hold_draft"]["holds"][0]
        self.assertEqual(hold["polygon"], proposal["reference_polygon"])
        self.assertIsNone(hold["score"])
        self.assertTrue(hold["user_confirmed"])
        self.assertEqual(hold["mask"]["encoding"], "png-base64")
        self.assertIsNone(changed["holds_confirmation"])
        with self.assertRaises(HTTPException):
            editor_commit(self.store, self.job["id"], "alice", proposal["proposal_id"])

    def test_stale_revision_cross_account_and_removed_media_are_rejected(self):
        proposal = self.preview()
        with self.assertRaises(HTTPException):
            editor_commit(self.store, self.job["id"], "bob", proposal["proposal_id"])
        other = copy.deepcopy(self.draft)
        other["hold_review_version"] = 1
        self.store.update(self.job["id"], hold_draft=other)
        with self.assertRaises(HTTPException) as error:
            editor_commit(self.store, self.job["id"], "alice", proposal["proposal_id"])
        self.assertEqual(error.exception.status_code, 409)
        self.store.delete_media(self.job["id"], "alice", "source_video")
        with self.assertRaises(HTTPException):
            editor_frame(self.store, self.job["id"], "alice", EditorFrameRequest())

    def test_edit_keeps_identity_and_undo_restores_previous_geometry(self):
        proposal = self.preview()
        added = editor_commit(self.store, self.job["id"], "alice", proposal["proposal_id"])
        old = added["hold_draft"]["holds"][0]
        self.frame = editor_frame(self.store, self.job["id"], "alice", EditorFrameRequest())
        self.polygon = [[.2, .2], [.4, .2], [.4, .4], [.2, .4]]
        proposal = self.preview(hold_id=old["id"])
        changed = editor_commit(self.store, self.job["id"], "alice", proposal["proposal_id"])
        self.assertEqual(len(changed["hold_draft"]["holds"]), 1)
        self.assertEqual(changed["hold_draft"]["holds"][0]["id"], old["id"])
        restored = self.store.undo_clicked_hold(self.job["id"], "alice", 2)
        self.assertEqual(restored["hold_draft"]["holds"], [old])

    def test_local_model_crop_maps_native_mask_and_never_commits_it_implicitly(self):
        seen = []
        def inference(images, *args, **kwargs):
            image = images[0]
            seen.append(image.shape)
            mask = np.zeros(image.shape[:2], np.uint8)
            cv2.rectangle(mask, (7, 7), (16, 15), 255, -1)
            return [([mask], [.93])], "fixture-native"
        with patch("core.photo_route_analysis._climbing_model_masks_batch", side_effect=inference):
            result = editor_preview(self.store, self.job["id"], "alice", EditorPreviewRequest(
                frame_token=self.frame["frame_token"], mode="model", region_xyxy=[.2, .2, .4, .4]))
        self.assertTrue(seen and seen[0][1] < 128)
        self.assertEqual(result["model_version"], "fixture-native")
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(self.store.get(self.job["id"], private=True)["hold_draft"]["holds"], [])
        self.assertGreater(result["candidates"][0]["source_polygon"][0][0], .1)

    def test_unaligned_frame_keeps_manual_input_and_cannot_save(self):
        with patch("core.replay_hold_editor.align_to_reference", return_value=(None, {})):
            self.frame = editor_frame(self.store, self.job["id"], "alice", EditorFrameRequest(frame_index=2))
        self.assertFalse(self.frame["aligned"])
        with self.assertRaises(HTTPException):
            self.preview()

    def test_cancel_before_queue_admission_prevents_model_execution(self):
        request_id = "a" * 32
        cancel_editor_request(self.store, self.job["id"], "alice", request_id)
        with patch("core.photo_route_analysis._climbing_model_masks_batch", side_effect=AssertionError("cancelled model ran")):
            with self.assertRaises(InterruptedError):
                editor_preview(self.store, self.job["id"], "alice", EditorPreviewRequest(
                    frame_token=self.frame["frame_token"], mode="model", region_xyxy=[.2,.2,.4,.4], request_id=request_id))

    def test_native_candidate_is_read_only_until_confirmed_and_removed_once(self):
        candidate = {"bbox":[.2,.2,.15,.15], "polygon":self.polygon,
            "contour_source":"climbing_model_native_mask", "score":.76, "color_group":"黄色"}
        self.store.update(self.job["id"], hold_draft={**self.draft,"hold_candidates":[candidate]})
        self.frame = editor_frame(self.store,self.job["id"],"alice",EditorFrameRequest())
        self.assertEqual(self.frame["candidates"][0]["candidate_index"],0)
        with patch("core.photo_route_analysis._climbing_model_masks_batch",side_effect=AssertionError("candidate must not rerun model")):
            proposal = editor_preview(self.store,self.job["id"],"alice",EditorPreviewRequest(
                frame_token=self.frame["frame_token"],mode="candidate",candidate_index=0))["candidates"][0]
            self.assertEqual(len(self.store.get(self.job["id"],private=True)["hold_draft"]["hold_candidates"]),1)
            changed = editor_commit(self.store,self.job["id"],"alice",proposal["proposal_id"])
        self.assertEqual(changed["hold_draft"]["hold_candidates"],[])
        self.assertEqual(changed["hold_draft"]["holds"][0]["score"],.76)
        restored=self.store.undo_clicked_hold(self.job["id"],"alice",1)
        self.assertEqual(restored["hold_draft"]["hold_candidates"],[candidate])

    def test_many_local_candidates_do_not_evict_returned_proposals(self):
        def inference(images,*args,**kwargs):
            mask=np.zeros(images[0].shape[:2],np.uint8)
            mask[7:16,7:17]=255
            return [([mask]*100,[.99-i*.001 for i in range(100)])],"fixture-many"
        with patch("core.photo_route_analysis._climbing_model_masks_batch",side_effect=inference):
            preview=editor_preview(self.store,self.job["id"],"alice",EditorPreviewRequest(
                frame_token=self.frame["frame_token"],mode="model",region_xyxy=[.2,.2,.4,.4]))
        self.assertEqual(len(preview["candidates"]),12)
        changed=editor_commit(self.store,self.job["id"],"alice",preview["candidates"][0]["proposal_id"])
        self.assertEqual(changed["hold_draft"]["holds"][0]["contour_evidence"]["model_version"],"fixture-many")

    def test_model_guided_candidate_remains_read_only_and_preserves_its_origin(self):
        candidate={"bbox":[.2,.2,.15,.15],"polygon":self.polygon,
            "contour_source":"model_guided_mobilesam_mask","score":.95,"color_group":"黄色"}
        self.store.update(self.job['id'],hold_draft={**self.draft,'hold_candidates':[candidate]})
        frame=editor_frame(self.store,self.job['id'],'alice',EditorFrameRequest())
        self.assertEqual(frame['candidates'][0]['candidate_index'],0)
        with patch('core.photo_route_analysis._climbing_model_masks_batch',side_effect=AssertionError('reuse candidate')):
            proposal=editor_preview(self.store,self.job['id'],'alice',EditorPreviewRequest(
                frame_token=frame['frame_token'],mode='candidate',candidate_index=0))['candidates'][0]
        self.assertEqual(self.store.get(self.job['id'],private=True)['hold_draft']['hold_candidates'],[candidate])
        self.assertEqual(proposal['contour_source'],'model_guided_mobilesam_mask')

    def test_4k_original_and_1080_analysis_copy_share_exact_wall_coordinates(self):
        job=self.store.get(self.job["id"],private=True)
        raw=self.store._path(job["id"]).parent/"source.mp4"
        writer=cv2.VideoWriter(str(raw),cv2.VideoWriter_fourcc(*"mp4v"),5,(3840,2160))
        writer.write(np.full((2160,3840,3),130,np.uint8));writer.release()
        # A 16:9 analysis stream, independently normalized to 1920x1080.
        source=self.store._media_path(job["id"],job,"source_video")
        writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*"mp4v"),5,(1920,1080))
        writer.write(np.full((1080,1920,3),130,np.uint8));writer.release()
        self.store.update(job["id"],video=asdict(VideoInfo(1920,1080,5,1,.2,source.stat().st_size)),
            high_resolution_source={"storage_name":"source.mp4","trim_start_seconds":0})
        self.frame=editor_frame(self.store,job["id"],"alice",EditorFrameRequest())
        self.assertEqual((self.frame["width"],self.frame["height"]),(3840,2160))
        proposal=self.preview()
        self.assertTrue(np.allclose(proposal["reference_polygon"],self.polygon,atol=1e-6))
        changed=editor_commit(self.store,job["id"],"alice",proposal["proposal_id"])
        evidence=changed["hold_draft"]["holds"][0]["contour_evidence"]
        self.assertEqual(evidence["source_to_reference"],[[.5,0,0],[0,.5,0],[0,0,1]])
        self.frame=editor_frame(self.store,job["id"],"alice",EditorFrameRequest())
        with patch("core.photo_route_analysis._climbing_model_masks_batch",side_effect=AssertionError("oversized crop ran")):
            with self.assertRaises(HTTPException) as error:
                editor_preview(self.store,job["id"],"alice",EditorPreviewRequest(
                    frame_token=self.frame["frame_token"],mode="model",region_xyxy=[0,0,1,1]))
        self.assertEqual(error.exception.status_code,422)

    def test_legacy_preview_token_confirms_without_recomputing(self):
        mapped = self.polygon
        job = self.store.get(self.job["id"], private=True)
        source = self.store._media_path(self.job["id"], job, "source_video")
        value = (job, copy.deepcopy(self.draft), source, 0, mapped, mapped, [.2, .2, .15, .15], 1)
        point = ReplayHoldPoint(point_xy=[.27, .27], time_seconds=0)
        with patch.object(self.store, "_clicked_hold_proposal", return_value=value):
            proposal = self.store.preview_hold_at_point(self.job["id"], "alice", point)
        with patch.object(self.store, "_clicked_hold_proposal", side_effect=AssertionError("must not recalculate")):
            changed = self.store.add_hold_at_point(self.job["id"], "alice", point.model_copy(update={"proposal_id":proposal["proposal_id"]}))
        self.assertEqual(changed["hold_draft"]["holds"][0]["polygon"], mapped)

    def test_tiny_foothold_concavity_and_invalid_shapes(self):
        small = [[.2, .2], [.204, .2], [.204, .204], [.2, .204]]
        self.assertEqual(validate_polygon(small, 1920, 1080), small)
        concave = [[.1, .1], [.4, .1], [.4, .4], [.25, .25], [.1, .4]]
        self.assertEqual(validate_polygon(concave, 128, 96), concave)
        for bad in ([[[0, 0], [1, 1], [0, 1], [1, 0]], [[float("nan"), 0], [1, 0], [1, 1]], [[0, 0], [0, 0], [1, 1]]]):
            with self.assertRaises(HTTPException):
                validate_polygon(bad, 128, 96)

    def test_high_resolution_copy_survives_cleanup_and_follows_source_deletion(self):
        source = self.root / "raw.mp4"
        shutil.copy2(self.store._media_path(self.job["id"], self.store.get(self.job["id"], private=True), "source_video"), source)
        pending = self.store.create_pending(owner="alice", route_id=None, route_color="黄色", source=source,
            original_name="clip.mp4", content_type="video/mp4", consent={}, retention_mode="keep_private_original")
        prepared = self.root / "prepared.mp4"
        shutil.copy2(self.store._media_path(self.job["id"], self.store.get(self.job["id"], private=True), "source_video"), prepared)
        with patch.dict(os.environ, {"CLIMB_REPLAY_KEEP_HIGH_RESOLUTION":"1"}):
            finished = self.store.finish_preparation(pending["id"], prepared, self.info)
        raw = self.store._path(pending["id"]).parent / finished["high_resolution_source"]["storage_name"]
        self.store.update(pending["id"], status="awaiting_hold_review", hold_draft=self.draft)
        self.store.cleanup_due_media()
        self.assertTrue(raw.exists())
        frame = editor_frame(self.store, pending["id"], "alice", EditorFrameRequest())
        self.assertEqual(frame["quality"], "保留的原始清晰度")
        self.store.delete_media(pending["id"], "alice", "source_video")
        self.assertFalse(raw.exists())

    def test_private_http_editor_roundtrip_and_validation(self):
        from test_climb_replay import FakeAnalyzer
        app=FastAPI()
        @app.middleware("http")
        async def identify(request:Request,call_next):
            request.state.pilot_user=SimpleNamespace(username=request.headers.get("x-user","alice"))
            return await call_next(request)
        app.include_router(create_climb_replay_router(self.store,ClimbReplayManager(self.store,FakeAnalyzer())))
        url=f"/api/climb-replay/jobs/{self.job['id']}/holds/editor"
        with TestClient(app) as client:
            self.assertEqual(client.post(url+"/frame",json={},headers={"x-user":"bob"}).status_code,404)
            frame=client.post(url+"/frame",json={"frame_index":0}).json()
            response=client.post(url+"/preview",json={"frame_token":frame["frame_token"],"mode":"manual","polygon":self.polygon})
            self.assertEqual(response.status_code,200)
            proposal=response.json()["candidates"][0]
            saved=client.post(url+"/confirm",json={"proposal_id":proposal["proposal_id"]})
            self.assertEqual(saved.status_code,200)
            self.assertEqual(saved.json()["hold_draft"]["holds"][0]["polygon"],proposal["reference_polygon"])
            self.assertEqual(client.post(url+"/frame",json={"frame_index":-1}).status_code,422)
            self.assertEqual(client.post(url+"/confirm",json={"proposal_id":proposal["proposal_id"]}).status_code,409)

    def test_completed_replay_renders_drawn_contour_only_after_global_confirmation(self):
        from core.climb_replay import AliyunReplayAnalyzer
        poses=[{"sample_index":i,"source_frame_id":i,"observed":True,"wall_alignment":"aligned",
            "kpts_xy":[[.5,.5]]*17,"kpts_score":[1]*17,"time_seconds":i/5} for i in range(10)]
        result={**self.draft,"pose_samples":poses,"analysis":{"sampling":{"effective_fps":5}}}
        self.store.update(self.job["id"],status="succeeded",result=result,hold_draft=None)
        self.frame=editor_frame(self.store,self.job["id"],"alice",EditorFrameRequest())
        with patch.object(AliyunReplayAnalyzer,"_request_pose",side_effect=AssertionError("no new pose")), \
             patch.dict(os.environ,{"CLIMB_REPLAY_VISUAL_ENABLED":"0"}):
            proposal=self.preview()
            changed=editor_commit(self.store,self.job["id"],"alice",proposal["proposal_id"])
            self.assertEqual(changed["result"]["holds"],[])
            confirmed=self.store.confirm_all_holds(self.job["id"],"alice",changed["holds_revision"])
        self.assertEqual(confirmed["result"]["pose_samples"],poses)
        self.assertEqual(confirmed["result"]["holds"][0]["polygon"],proposal["reference_polygon"])
        from core.replay_analysis_view import LAYOUT
        self.assertEqual(confirmed["result"]["overlay"]["layout"],LAYOUT)
        target,_=self.store.media_file(self.job["id"],"alice","reviewed_overlay_video")
        cap=cv2.VideoCapture(str(target))
        try:
            count=0
            while cap.read()[0]:
                count+=1
            self.assertEqual(count,10)
        finally:
            cap.release()


if __name__ == "__main__":
    unittest.main()

