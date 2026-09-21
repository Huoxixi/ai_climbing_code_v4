import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from core.climb_replay import (AliyunReplayAnalyzer, ClimbReplayManager,
                               ClimbReplayStore, REPLAY_CONSENT_VERSION,
                               REPLAY_OVERLAY_FILENAME, REPLAY_OVERLAY_MEDIA_KIND,
                               REPLAY_RETENTION_DELETE, REPLAY_RETENTION_KEEP,
                               ReplayCancelled, ReplayConfigurationError, VideoInfo, VideoLimits,
                               build_action_steps, build_pose_render_timeline,
                               build_visible_action_markers,
                               create_climb_replay_router, fit_aspect_rect,
                               fit_hold_map_rect, probe_video,
                               native_mask_polygon,
                               render_replay_overlay_video)


def make_video(path: Path, *, frames=8, fps=4.0, width=96, height=64):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise unittest.SkipTest("当前 OpenCV 环境不能编码 MP4")
    for index in range(frames):
        image = np.full((height, width, 3), 20 + index, dtype=np.uint8)
        writer.write(image)
    writer.release()


class FakeAnalyzer:
    def analysis_contract(self, video_info):
        return {"contract_version": 1, "pipeline_version": "test-pipeline",
                "usage": {"planned_requests": 1, "actual_requests": 0}}

    def analyze(self, video, *, route_color, video_info, progress, cancelled, telemetry):
        progress("测试分析", 50)
        analysis = self.analysis_contract(video_info)
        analysis["usage"]["actual_requests"] = 1
        telemetry(analysis)
        video.with_name(REPLAY_OVERLAY_FILENAME).write_bytes(b"test-overlay")
        return {"schema_version": 2, "route": {"color": route_color},
                "video": {"frame_count": video_info.frame_count},
                "pose_samples": [],
                "attempt": {"sequence": [1, 2], "topped_out": True, "contacts": []},
                "analysis": analysis,
                "overlay": {"pose_rendering": "sampled_only_no_interpolation"}}


class FailingAnalyzer(FakeAnalyzer):
    def analyze(self, video, *, route_color, video_info, progress, cancelled, telemetry):
        analysis = self.analysis_contract(video_info)
        analysis["usage"].update(actual_requests=1, failed_requests=1)
        telemetry(analysis)
        raise RuntimeError("测试姿态请求失败")


class OverlayThenFailAnalyzer(FakeAnalyzer):
    def analyze(self, video, *, route_color, video_info, progress, cancelled, telemetry):
        video.with_name(REPLAY_OVERLAY_FILENAME).write_bytes(b"partial-overlay")
        telemetry(self.analysis_contract(video_info))
        raise RuntimeError("叠加登记前失败")


class BlockingAnalyzer(FakeAnalyzer):
    def __init__(self):
        self.started = threading.Event()

    def analyze(self, video, *, route_color, video_info, progress, cancelled, telemetry):
        self.started.set()
        deadline = time.time() + 2
        while time.time() < deadline and not cancelled():
            time.sleep(.01)
        raise ReplayCancelled()


class ClimbReplayApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = ClimbReplayStore(root)
        self.manager = ClimbReplayManager(self.store, FakeAnalyzer())
        self.video = root / "sample.mp4"
        make_video(self.video)
        self.test_videos = []
        for index in range(1, 4):
            path = root / f"sample-{index}.mp4"
            make_video(path, frames=6 + index)
            item = {
                "id": f"case-{index}", "label": f"本地案例 {index}",
                "description": "仅用于本机流程验收", "path": path,
            }
            if index == 2:
                comparison_path = root / "sample-2-comparison.webm"
                comparison_path.write_bytes(b"latest-comparison-video")
                item["comparison_path"] = comparison_path
                item["comparison_route_color"] = "蓝色"
                item["comparison_action_count"] = 17
            self.test_videos.append(item)
        app = FastAPI()

        @app.middleware("http")
        async def identify(request: Request, call_next):
            request.state.pilot_user = SimpleNamespace(username=request.headers.get("x-user", "owner"))
            return await call_next(request)

        app.include_router(create_climb_replay_router(
            self.store,
            self.manager,
            route_lookup=lambda route_id, owner: {"id": route_id, "owner": owner,
                                                   "color_group": "绿色"},
            limits=VideoLimits(max_bytes=2 * 1024 * 1024, max_duration_seconds=5,
                               max_width=640, max_height=480, max_frames=30),
            test_video_cases=self.test_videos,
        ))
        self.client = TestClient(app)

    def tearDown(self):
        self.manager.close()
        self.temp.cleanup()

    def wait(self, job_id):
        deadline = time.time() + 3
        while time.time() < deadline:
            job = self.client.get(f"/api/climb-replay/jobs/{job_id}").json()
            if job["status"] in {"succeeded", "failed", "cancelled"}:
                return job
            time.sleep(0.02)
        self.fail("复盘任务没有在测试时限内结束")

    def test_local_acceptance_videos_are_private_listed_and_downloadable(self):
        listing = self.client.get("/api/climb-replay/test-videos")
        self.assertEqual(listing.status_code, 200)
        items = listing.json()["items"]
        self.assertEqual(len(items), 3)
        self.assertEqual([item["id"] for item in items], ["case-1", "case-2", "case-3"])
        self.assertEqual(items[1]["label"], "本地案例 2")
        self.assertEqual(items[1]["usage"], "local_acceptance_only")
        self.assertTrue(items[1]["comparison_available"])
        self.assertFalse(items[0]["comparison_available"])
        self.assertEqual(items[1]["comparison_route_color"], "蓝色")
        self.assertEqual(items[1]["comparison_action_count"], 17)
        self.assertNotIn("path", items[1])
        self.assertNotIn("comparison_path", items[1])

        video = self.client.get("/api/climb-replay/test-videos/case-2")
        self.assertEqual(video.status_code, 200)
        self.assertEqual(video.headers["content-type"], "video/mp4")
        self.assertEqual(video.headers["cache-control"], "private, no-store")
        self.assertEqual(video.content, self.test_videos[1]["path"].read_bytes())
        comparison = self.client.get("/api/climb-replay/test-videos/case-2/comparison")
        self.assertEqual(comparison.status_code, 200)
        self.assertEqual(comparison.headers["content-type"], "video/webm")
        self.assertEqual(comparison.headers["cache-control"], "private, no-store")
        self.assertEqual(comparison.content, b"latest-comparison-video")
        self.assertEqual(
            self.client.get("/api/climb-replay/test-videos/case-1/comparison").status_code,
            404,
        )
        self.assertEqual(self.client.get("/api/climb-replay/test-videos/missing").status_code, 404)

    def test_upload_runs_in_owner_scoped_single_worker(self):
        with self.video.open("rb") as source:
            response = self.client.post(
                "/api/climb-replay/jobs",
                data={"route_id": "route-1", "consent_version": REPLAY_CONSENT_VERSION,
                      "consent_granted": "true"},
                files={"video": ("attempt.mp4", source, "video/mp4")},
            )
        self.assertEqual(response.status_code, 202)
        job = self.wait(response.json()["id"])
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["route_color"], "绿色")
        self.assertEqual(job["result"]["attempt"]["sequence"], [1, 2])
        self.assertEqual(job["analysis_runs"][0]["state"], "succeeded")
        self.assertEqual(job["analysis_runs"][0]["analysis"]["usage"]["actual_requests"], 1)
        self.assertEqual(job["media"][REPLAY_OVERLAY_MEDIA_KIND]["status"], "available")
        self.assertEqual(job["consent_history"][0]["version"], REPLAY_CONSENT_VERSION)
        self.assertEqual(job["consent_history"][0]["region"], "cn-shanghai")
        self.assertFalse(job["consent_history"][0]["full_video_sent"])
        self.assertEqual(
            job["media"]["source_video"]["retention_mode"], REPLAY_RETENTION_DELETE,
        )
        self.assertIsNotNone(job["media"]["source_video"]["delete_at"])
        self.assertNotIn("input_path", job)
        self.assertEqual(self.client.get("/api/climb-replay/jobs").status_code, 200)
        self.assertEqual(self.client.get(
            f"/api/climb-replay/jobs/{job['id']}", headers={"x-user": "other"}).status_code, 404)

    def test_proxy_safe_chunk_upload_creates_job(self):
        content = self.video.read_bytes()
        started = self.client.post('/api/climb-replay/uploads', json={
            'filename':'attempt.mp4', 'content_type':'video/mp4', 'size_bytes':len(content),
            'route_id':'route-1', 'route_color':'',
            'consent_version':REPLAY_CONSENT_VERSION, 'consent_granted':True,
        })
        self.assertEqual(started.status_code, 200, started.text)
        upload_id = started.json()['id']; split = max(1, len(content) // 2)
        first = self.client.put(f'/api/climb-replay/uploads/{upload_id}', content=content[:split],
                                headers={'x-upload-offset':'0'})
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.put(f'/api/climb-replay/uploads/{upload_id}', content=content[split:],
                                 headers={'x-upload-offset':str(split)})
        self.assertTrue(second.json()['complete'])
        completed = self.client.post(f'/api/climb-replay/uploads/{upload_id}/complete')
        self.assertEqual(completed.status_code, 202, completed.text)
        job = self.wait(completed.json()['id'])
        self.assertEqual(job['status'], 'succeeded')
        self.assertEqual(job['route_color'], '绿色')

    def test_keep_private_original_has_no_automatic_delete_time(self):
        content = self.video.read_bytes()
        started = self.client.post('/api/climb-replay/uploads', json={
            'filename':'attempt.mp4', 'content_type':'video/mp4', 'size_bytes':len(content),
            'route_color':'绿色', 'consent_version':REPLAY_CONSENT_VERSION,
            'consent_granted':True, 'retention_mode':REPLAY_RETENTION_KEEP,
        })
        self.assertEqual(started.status_code, 200, started.text)
        upload_id = started.json()['id']
        self.client.put(f'/api/climb-replay/uploads/{upload_id}', content=content,
                        headers={'x-upload-offset':'0'})
        completed = self.client.post(f'/api/climb-replay/uploads/{upload_id}/complete')
        job = self.wait(completed.json()['id'])
        source = job['media']['source_video']
        self.assertEqual(source['retention_mode'], REPLAY_RETENTION_KEEP)
        self.assertIsNone(source['delete_at'])

    def test_delete_source_keeps_result_and_prevents_retry(self):
        content = self.video.read_bytes()
        started = self.client.post('/api/climb-replay/uploads', json={
            'filename':'attempt.mp4', 'content_type':'video/mp4', 'size_bytes':len(content),
            'route_color':'绿色', 'consent_version':REPLAY_CONSENT_VERSION,
            'consent_granted':True,
        }).json()
        self.client.put(f"/api/climb-replay/uploads/{started['id']}", content=content,
                        headers={'x-upload-offset':'0'})
        job = self.wait(self.client.post(
            f"/api/climb-replay/uploads/{started['id']}/complete").json()['id'])
        denied = self.client.delete(
            f"/api/climb-replay/jobs/{job['id']}/media/source-video",
            headers={'x-user':'other'},
        )
        self.assertEqual(denied.status_code, 404)
        deleted = self.client.delete(
            f"/api/climb-replay/jobs/{job['id']}/media/source-video",
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(deleted.json()['media']['source_video']['status'], 'deleted')
        self.assertEqual(
            deleted.json()['media'][REPLAY_OVERLAY_MEDIA_KIND]['status'], 'available',
        )
        self.assertEqual(deleted.json()['result']['attempt']['sequence'], [1, 2])
        self.store.update(job['id'], status='failed')
        retry = self.client.post(f"/api/climb-replay/jobs/{job['id']}/retry", json={
            'consent_version':REPLAY_CONSENT_VERSION, 'consent_granted':True,
        })
        self.assertEqual(retry.status_code, 409)
        self.assertIn('原视频已删除', retry.json()['detail'])

    def test_overlay_media_is_private_downloadable_and_separately_deletable(self):
        content = self.video.read_bytes()
        started = self.client.post('/api/climb-replay/uploads', json={
            'filename':'attempt.mp4', 'content_type':'video/mp4', 'size_bytes':len(content),
            'route_color':'绿色', 'consent_version':REPLAY_CONSENT_VERSION,
            'consent_granted':True,
        }).json()
        self.client.put(f"/api/climb-replay/uploads/{started['id']}", content=content,
                        headers={'x-upload-offset':'0'})
        job = self.wait(self.client.post(
            f"/api/climb-replay/uploads/{started['id']}/complete").json()['id'])
        path = f"/api/climb-replay/jobs/{job['id']}/media/overlay-video"
        denied = self.client.get(path, headers={'x-user':'other'})
        self.assertEqual(denied.status_code, 404)
        source_stream = self.client.get(
            f"/api/climb-replay/jobs/{job['id']}/media/source-video",
            headers={'range':'bytes=0-15'},
        )
        self.assertEqual(source_stream.status_code, 206)
        self.assertEqual(source_stream.headers['content-type'], 'video/mp4')
        overlay_stream = self.client.get(path, headers={'range':'bytes=0-3'})
        self.assertEqual(overlay_stream.status_code, 206)
        self.assertEqual(overlay_stream.content, b'test')
        downloaded = self.client.get(f"{path}?download=true")
        self.assertEqual(downloaded.status_code, 200)
        self.assertEqual(downloaded.headers['content-type'], 'video/webm')
        self.assertIn('attachment', downloaded.headers['content-disposition'])
        deleted = self.client.delete(path)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()['media'][REPLAY_OVERLAY_MEDIA_KIND]['status'], 'deleted')
        self.assertEqual(deleted.json()['media']['source_video']['status'], 'available')
        self.assertEqual(deleted.json()['result']['attempt']['sequence'], [1, 2])
        self.assertEqual(self.client.get(path).status_code, 404)

    def test_delete_entire_replay_returns_owner_scoped_receipt(self):
        content = self.video.read_bytes()
        started = self.client.post('/api/climb-replay/uploads', json={
            'filename':'attempt.mp4', 'content_type':'video/mp4', 'size_bytes':len(content),
            'route_color':'绿色', 'consent_version':REPLAY_CONSENT_VERSION,
            'consent_granted':True,
        }).json()
        self.client.put(f"/api/climb-replay/uploads/{started['id']}", content=content,
                        headers={'x-upload-offset':'0'})
        job = self.wait(self.client.post(
            f"/api/climb-replay/uploads/{started['id']}/complete").json()['id'])
        job_directory = self.store.jobs / job['id']
        denied = self.client.delete(
            f"/api/climb-replay/jobs/{job['id']}", headers={'x-user':'other'},
        )
        self.assertEqual(denied.status_code, 404)
        requested = self.client.delete(f"/api/climb-replay/jobs/{job['id']}")
        self.assertEqual(requested.status_code, 202, requested.text)
        deadline = time.time() + 2
        receipt = requested.json()
        while time.time() < deadline and receipt['state'] == 'queued':
            time.sleep(.01)
            receipt = self.client.get(f"/api/climb-replay/deletions/{job['id']}").json()
        self.assertEqual(receipt['state'], 'completed')
        self.assertIsNotNone(receipt['completed_at'])
        self.assertFalse(job_directory.exists())
        self.assertEqual(self.client.get(f"/api/climb-replay/jobs/{job['id']}").status_code, 404)
        self.assertEqual(self.client.get(
            f"/api/climb-replay/deletions/{job['id']}", headers={'x-user':'other'},
        ).status_code, 404)

    def test_consent_is_server_enforced_versioned_and_withdrawable(self):
        policy = self.client.get('/api/climb-replay/consent-policy')
        self.assertEqual(policy.status_code, 200)
        self.assertEqual(policy.json()['version'], REPLAY_CONSENT_VERSION)
        self.assertFalse(policy.json()['full_video_sent'])

        missing = self.client.post('/api/climb-replay/uploads', json={
            'filename':'attempt.mp4', 'content_type':'video/mp4',
            'size_bytes':self.video.stat().st_size, 'route_color':'绿色',
            'consent_version':REPLAY_CONSENT_VERSION, 'consent_granted':False,
        })
        self.assertEqual(missing.status_code, 422)
        stale = self.client.post('/api/climb-replay/uploads', json={
            'filename':'attempt.mp4', 'content_type':'video/mp4',
            'size_bytes':self.video.stat().st_size, 'route_color':'绿色',
            'consent_version':'old-policy', 'consent_granted':True,
        })
        self.assertEqual(stale.status_code, 409)

        content = self.video.read_bytes()
        started = self.client.post('/api/climb-replay/uploads', json={
            'filename':'attempt.mp4', 'content_type':'video/mp4', 'size_bytes':len(content),
            'route_color':'绿色', 'consent_version':REPLAY_CONSENT_VERSION,
            'consent_granted':True,
        }).json()
        self.client.put(f"/api/climb-replay/uploads/{started['id']}", content=content,
                        headers={'x-upload-offset':'0'})
        job = self.wait(self.client.post(
            f"/api/climb-replay/uploads/{started['id']}/complete").json()['id'])
        denied = self.client.post(
            f"/api/climb-replay/jobs/{job['id']}/consent/withdraw",
            headers={'x-user':'other'},
        )
        self.assertEqual(denied.status_code, 404)
        withdrawn = self.client.post(
            f"/api/climb-replay/jobs/{job['id']}/consent/withdraw").json()
        self.assertEqual(withdrawn['consent_history'][-1]['event'], 'withdrawn')
        self.assertIn('本次处理已结束', withdrawn['consent_history'][-1]['outcome'])

    def test_retry_requires_a_fresh_consent_record(self):
        content = self.video.read_bytes()
        started = self.client.post('/api/climb-replay/uploads', json={
            'filename':'attempt.mp4', 'content_type':'video/mp4', 'size_bytes':len(content),
            'route_color':'绿色', 'consent_version':REPLAY_CONSENT_VERSION,
            'consent_granted':True,
        }).json()
        self.client.put(f"/api/climb-replay/uploads/{started['id']}", content=content,
                        headers={'x-upload-offset':'0'})
        job = self.wait(self.client.post(
            f"/api/climb-replay/uploads/{started['id']}/complete").json()['id'])
        self.store.update(job['id'], status='failed', stage='测试失败', error='测试')
        self.assertEqual(self.client.post(
            f"/api/climb-replay/jobs/{job['id']}/retry").status_code, 422)
        retried = self.client.post(f"/api/climb-replay/jobs/{job['id']}/retry", json={
            'consent_version':REPLAY_CONSENT_VERSION, 'consent_granted':True,
        })
        self.assertEqual(retried.status_code, 200, retried.text)
        self.assertEqual(retried.json()['attempt'], 2)
        self.assertEqual(retried.json()['consent_history'][-1]['attempt'], 2)

    def test_rejects_non_mp4_and_overlong_video(self):
        response = self.client.post(
            "/api/climb-replay/jobs",
            data={"route_color": "green", "consent_version": REPLAY_CONSENT_VERSION,
                  "consent_granted": "true"},
            files={"video": ("attempt.mov", b"not-video", "video/quicktime")},
        )
        self.assertEqual(response.status_code, 422)
        long_video = Path(self.temp.name) / "long.mp4"
        make_video(long_video, frames=24, fps=4.0)
        with long_video.open("rb") as source:
            response = self.client.post(
                "/api/climb-replay/jobs",
                data={"route_color": "green", "consent_version": REPLAY_CONSENT_VERSION,
                      "consent_granted": "true"},
                files={"video": ("long.mp4", source, "video/mp4")},
            )
        self.assertEqual(response.status_code, 422)
        self.assertIn("5 秒", response.json()["detail"])


class ClimbReplayAnalysisTests(unittest.TestCase):
    def test_default_video_limit_allows_ninety_seconds(self):
        limits = VideoLimits()
        self.assertEqual(limits.max_bytes, 200 * 1024 * 1024)
        self.assertEqual(limits.max_duration_seconds, 90.0)
        self.assertEqual(limits.max_frames, 2700)

    def test_missing_domestic_pose_keys_fails_before_any_upload(self):
        with patch.dict("os.environ", {
            "ALIBABA_CLOUD_ACCESS_KEY_ID": "",
            "ALIBABA_CLOUD_ACCESS_KEY_SECRET": "",
        }):
            analyzer = AliyunReplayAnalyzer(access_key_id="", access_key_secret="")
            with self.assertRaises(ReplayConfigurationError):
                analyzer._client()

    def test_aliyun_pose_response_is_normalized_to_replay_contract(self):
        def body(label, x, y, score):
            return {"Label": label, "Confident": score,
                    "Positions": [{"Points": [x, y]}]}

        payload = {"Data": {"Outputs": [{"HumanCount": 1, "Results": [{"Bodies": [
            body("left_wrist", .1, .25, .8),
            body("right_wrist", .2, .3, .7),
            body("left_ankle", .1125, .9, .9),
            body("right_ankle", .225, .9, .9),
        ]}]}]}}
        analyzer = AliyunReplayAnalyzer(client=object())
        analyzer._request_pose = lambda _jpeg: payload
        record = analyzer._pose_frame(np.zeros((200, 400, 3), np.uint8), frame_id=2, source_frame_id=15)
        self.assertEqual(record["frame_id"], 2)
        self.assertEqual(record["source_frame_id"], 15)
        self.assertEqual(record["kpts_xy"][9], [0.1, 0.25])
        self.assertEqual(record["bbox_xywh"], [0.1, 0.25, 0.125, 0.65])

    def test_analysis_contract_records_versions_usage_cost_and_timings(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "sample.mp4"
            make_video(video, frames=8, fps=4.0)
            info = probe_video(video)
            analyzer = AliyunReplayAnalyzer(client=object(), pose_fps=2)
            holds = [{"id": 1, "bbox": [0.1, 0.1, 0.5, 0.8],
                      "score": 0.9, "appearances": 1}]
            telemetry = []

            def pose_frame(_frame, *, frame_id, source_frame_id, before_request):
                before_request(1200)
                if frame_id % 2:
                    return None
                points = [[0.3, 0.3] for _ in range(17)]
                return {"frame_id": frame_id, "source_frame_id": source_frame_id,
                        "track_id": 0, "kpts_xy": points, "kpts_score": [0.9] * 17,
                        "bbox_xywh": [0.1, 0.1, 0.4, 0.8]}

            with patch.object(analyzer, "_sample_frames",
                              return_value=[np.zeros((64, 96, 3), np.uint8)] * 9), \
                 patch.object(analyzer, "_local_holds", return_value=(holds, "hold-checkpoint-v1")), \
                 patch.object(analyzer, "_pose_frame", side_effect=pose_frame):
                result = analyzer.analyze(
                    video, route_color="绿色", video_info=info,
                    progress=lambda _stage, _value: None, cancelled=lambda: False,
                    telemetry=telemetry.append,
                )

            analysis = result["analysis"]
            self.assertEqual(result["schema_version"], 2)
            self.assertEqual(analysis["provider"]["api_version"], "2019-12-30")
            self.assertEqual(analysis["models"]["holds"]["version"], "hold-checkpoint-v1")
            self.assertEqual(analysis["sampling"]["effective_fps"], 2.0)
            self.assertEqual(analysis["usage"]["planned_requests"], 4)
            self.assertEqual(analysis["usage"]["actual_requests"], 4)
            self.assertEqual(analysis["usage"]["successful_requests"], 4)
            self.assertEqual(analysis["usage"]["successful_pose_frames"], 2)
            self.assertEqual(analysis["usage"]["responses_without_pose"], 2)
            self.assertEqual(analysis["usage"]["request_image_bytes"], 4800)
            self.assertEqual(analysis["cost"]["estimated_amount"], 0.0064)
            self.assertEqual(analysis["timings_ms"].keys(), {
                "total", "background", "hold_inference", "pose", "contact", "overlay", "report",
            })
            self.assertEqual(len(result['pose_samples']), 4)
            self.assertEqual(
                [sample['source_frame_id'] for sample in result['pose_samples']], [0, 2, 4, 6],
            )
            self.assertEqual(
                result['overlay']['pose_rendering'],
                'local_linear_between_measured_samples',
            )
            self.assertFalse(result['overlay']['audio_included'])
            self.assertTrue(video.with_name(REPLAY_OVERLAY_FILENAME).is_file())
            self.assertTrue(telemetry)

    def test_overlay_renderer_keeps_every_source_frame_and_exact_sample_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'sample.mp4'
            target = Path(directory) / REPLAY_OVERLAY_FILENAME
            make_video(source, frames=8, fps=4.0)
            points = [[.5, .5] for _ in range(17)]
            result = {
                'holds': [{'id': 1, 'bbox': [.1, .1, .2, .2]}],
                'pose_samples': [{
                    'source_frame_id': 2, 'observed': True,
                    'kpts_xy': points, 'kpts_score': [.9] * 17,
                }],
                'attempt': {'contacts': [{
                    'limb': 'left_hand', 'hold_id': 1,
                    'start_source_frame': 2, 'end_source_frame': 4,
                }]},
            }
            contract = render_replay_overlay_video(source, target, result)
            self.assertEqual(contract['frames_written'], 8)
            self.assertEqual(
                contract['pose_rendering'],
                'local_linear_between_measured_samples',
            )
            self.assertEqual(contract['layout'], 'split_route_map_actions_v7')
            self.assertEqual(contract['hold_map'], 'route_bounds_zoom_with_touch_markers')
            self.assertEqual(
                contract['action_labels'], 'sequence_limb_and_chinese_supplement_v1',
            )
            self.assertEqual(contract['hold_count'], 1)
            self.assertEqual(contract['action_count'], 1)
            self.assertFalse(contract['audio_included'])
            rendered = cv2.VideoCapture(str(target))
            try:
                self.assertTrue(rendered.isOpened())
                self.assertEqual(int(rendered.get(cv2.CAP_PROP_FRAME_COUNT)), 8)
            finally:
                rendered.release()

    def test_overlay_renderer_cancellation_leaves_no_partial_media(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'sample.mp4'
            target = Path(directory) / REPLAY_OVERLAY_FILENAME
            make_video(source, frames=8, fps=4.0)
            with self.assertRaises(ReplayCancelled):
                render_replay_overlay_video(
                    source, target, {'holds': [], 'pose_samples': [], 'attempt': {}},
                    cancelled=lambda: True,
                )
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(directory).glob('.*.tmp.webm')), [])

    def test_failed_attempt_keeps_telemetry_in_its_run_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.mp4"
            source.write_bytes(b"test")
            store = ClimbReplayStore(root / "store")
            manager = ClimbReplayManager(store, FailingAnalyzer())
            try:
                job = store.create(
                    owner="owner", route_id=None, route_color="绿色", source=source,
                    original_name="sample.mp4",
                    info=VideoInfo(96, 64, 4.0, 8, 2.0, 4),
                    consent={"event": "granted", "attempt": 1,
                             "version": REPLAY_CONSENT_VERSION},
                    retention_mode=REPLAY_RETENTION_DELETE,
                )
                manager.enqueue(job["id"])
                deadline = time.time() + 2
                while time.time() < deadline:
                    job = store.get(job["id"])
                    if job["status"] == "failed":
                        break
                    time.sleep(0.01)
                self.assertEqual(job["status"], "failed")
                self.assertEqual(job["error_code"], "analysis_failed")
                self.assertEqual(job["analysis_runs"][0]["state"], "failed")
                self.assertEqual(
                    job["analysis_runs"][0]["analysis"]["usage"]["actual_requests"], 1,
                )
            finally:
                manager.close()

    def test_failed_attempt_discards_uncommitted_overlay_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.mp4"
            source.write_bytes(b"test")
            store = ClimbReplayStore(root / "store")
            manager = ClimbReplayManager(store, OverlayThenFailAnalyzer())
            try:
                job = store.create(
                    owner="owner", route_id=None, route_color="绿色", source=source,
                    original_name="sample.mp4",
                    info=VideoInfo(96, 64, 4.0, 8, 2.0, 4),
                    consent={"event": "granted", "attempt": 1,
                             "version": REPLAY_CONSENT_VERSION},
                    retention_mode=REPLAY_RETENTION_DELETE,
                )
                manager.enqueue(job["id"])
                deadline = time.time() + 2
                while time.time() < deadline:
                    current = store.get(job["id"])
                    if current["status"] == "failed":
                        break
                    time.sleep(.01)
                self.assertEqual(current["status"], "failed")
                self.assertFalse((store.jobs / job["id"] / REPLAY_OVERLAY_FILENAME).exists())
                self.assertNotIn(REPLAY_OVERLAY_MEDIA_KIND, current["media"])
            finally:
                manager.close()

    def test_restart_closes_the_current_analysis_run_with_the_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "store"
            source = Path(directory) / "sample.mp4"
            source.write_bytes(b"test")
            store = ClimbReplayStore(root)
            job = store.create(
                owner="owner", route_id=None, route_color="绿色", source=source,
                original_name="sample.mp4", info=VideoInfo(96, 64, 4.0, 8, 2.0, 4),
                consent={"event": "granted", "attempt": 1,
                         "version": REPLAY_CONSENT_VERSION},
                retention_mode=REPLAY_RETENTION_DELETE,
            )
            store.update(job["id"], status="running", started_at="2026-09-20T00:00:00Z")
            store.start_analysis_run(job["id"], 1, {"pipeline_version": "test"})

            recovered = ClimbReplayStore(root).get(job["id"])
            self.assertEqual(recovered["status"], "failed")
            self.assertEqual(recovered["error_code"], "service_restarted")
            self.assertEqual(recovered["analysis_runs"][0]["state"], "failed")
            self.assertEqual(recovered["analysis_runs"][0]["error_code"], "service_restarted")

    def test_due_cleanup_deletes_only_the_source_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "store"
            source = Path(directory) / "sample.mp4"
            source.write_bytes(b"test")
            store = ClimbReplayStore(root)
            job = store.create(
                owner="owner", route_id=None, route_color="绿色", source=source,
                original_name="sample.mp4", info=VideoInfo(96, 64, 4.0, 8, 2.0, 4),
                consent={"event": "granted", "attempt": 1,
                         "version": REPLAY_CONSENT_VERSION},
                retention_mode=REPLAY_RETENTION_DELETE,
            )
            private = store.update(job['id'], status='succeeded', result={'kept': True})
            overlay_path = store.jobs / job['id'] / REPLAY_OVERLAY_FILENAME
            overlay_path.write_bytes(b'overlay-kept')
            store.register_overlay(job['id'])
            private = store.get(job['id'], private=True)
            media = private['media']
            media['source_video']['delete_at'] = '2000-01-01T00:00:00+00:00'
            store.update(job['id'], media=media)
            self.assertEqual(store.cleanup_due_media(), [job['id']])
            cleaned = store.get(job['id'])
            self.assertEqual(cleaned['media']['source_video']['status'], 'deleted')
            self.assertEqual(cleaned['media'][REPLAY_OVERLAY_MEDIA_KIND]['status'], 'available')
            self.assertTrue(overlay_path.is_file())
            self.assertEqual(cleaned['result'], {'kept': True})
            self.assertTrue((store.jobs / job['id'] / 'job.json').is_file())

    def test_delete_running_job_stops_analysis_before_removing_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "store"
            source = Path(directory) / "sample.mp4"
            source.write_bytes(b"test")
            store = ClimbReplayStore(root)
            analyzer = BlockingAnalyzer()
            manager = ClimbReplayManager(store, analyzer)
            try:
                job = store.create(
                    owner="owner", route_id=None, route_color="绿色", source=source,
                    original_name="sample.mp4",
                    info=VideoInfo(96, 64, 4.0, 8, 2.0, 4),
                    consent={"event": "granted", "attempt": 1,
                             "version": REPLAY_CONSENT_VERSION},
                    retention_mode=REPLAY_RETENTION_KEEP,
                )
                manager.enqueue(job['id'])
                self.assertTrue(analyzer.started.wait(1))
                receipt = store.request_delete(job['id'], 'owner')
                self.assertEqual(receipt['state'], 'queued')
                manager.enqueue_delete(job['id'])
                deadline = time.time() + 2
                while time.time() < deadline:
                    receipt = store.get_deletion(job['id'], 'owner')
                    if receipt['state'] == 'completed':
                        break
                    time.sleep(.01)
                self.assertEqual(receipt['state'], 'completed')
                self.assertFalse((store.jobs / job['id']).exists())
            finally:
                manager.close()

    def test_hold_consensus_and_contact_summary_are_deterministic(self):
        detections = [
            [{"bbox_xywh": [0.1, 0.8, 0.1, 0.08], "score": 0.9},
             {"bbox_xywh": [0.5, 0.2, 0.1, 0.08], "score": 0.95}],
            [{"bbox_xywh": [0.105, 0.8, 0.1, 0.08], "score": 0.85},
             {"bbox_xywh": [0.505, 0.2, 0.1, 0.08], "score": 0.9}],
        ]
        holds = AliyunReplayAnalyzer._consensus_holds(detections)
        self.assertEqual([hold["id"] for hold in holds], [1, 2])
        self.assertGreater(holds[0]["bbox"][1], holds[1]["bbox"][1])

        records = []
        for frame in range(8):
            points = [[0.0, 0.0] for _ in range(17)]
            scores = [1.0] * 17
            points[5] = [0.3, 0.5]; points[6] = [0.4, 0.5]
            points[11] = [0.3, 0.6]; points[12] = [0.4, 0.6]
            target = holds[0] if frame < 4 else holds[1]
            x = target["bbox"][0] + target["bbox"][2] / 2
            y = target["bbox"][1] + target["bbox"][3] / 2
            points[9] = [x, y]; points[10] = [x, y]
            points[15] = [x, y - 0.02]; points[16] = [x, y - 0.02]
            records.append({"frame_id": frame, "track_id": 7, "kpts_xy": points,
                            "kpts_score": scores, "bbox_xywh": [0.1, 0.1, 0.5, 0.8]})
        result = AliyunReplayAnalyzer._contacts(records, holds, fps=4.0)
        self.assertEqual(result["sequence"], [1, 2])
        self.assertTrue(result["topped_out"])
        self.assertEqual(result["completion_frame"], 5)
        self.assertIn("left_hand", result["per_limb"])

    def test_polygon_shape_controls_contact_and_actions_are_chronological(self):
        triangular_hold = {
            "id": 4,
            "bbox": [0.1, 0.1, 0.4, 0.4],
            "polygon": [[0.1, 0.1], [0.5, 0.1], [0.1, 0.5]],
        }
        self.assertTrue(AliyunReplayAnalyzer._inside((0.2, 0.2), triangular_hold, 0.0))
        self.assertFalse(AliyunReplayAnalyzer._inside((0.45, 0.45), triangular_hold, 0.0))

        steps = build_action_steps([
            {"limb": "right_hand", "hold_id": 7,
             "start_source_frame": 12, "end_source_frame": 18},
            {"limb": "left_foot", "hold_id": 2,
             "start_source_frame": 4, "end_source_frame": 9},
            {"limb": "left_hand", "hold_id": 5,
             "start_source_frame": 12, "end_source_frame": 16},
        ])
        self.assertEqual(
            [(step["step"], step["limb"], step["hold_id"]) for step in steps],
            [(1, "left_foot", 2), (2, "left_hand", 5), (3, "right_hand", 7)],
        )

    def test_action_steps_add_conservative_chinese_supplement_names(self):
        steps = build_action_steps([
            {"limb": "left_hand", "hold_id": 1,
             "start_source_frame": 0, "end_source_frame": 10},
            {"limb": "right_hand", "hold_id": 1,
             "start_source_frame": 3, "end_source_frame": 8},
            {"limb": "left_hand", "hold_id": 2,
             "start_source_frame": 12, "end_source_frame": 18},
            {"limb": "left_hand", "hold_id": 2,
             "start_source_frame": 20, "end_source_frame": 24},
        ])
        self.assertEqual(
            [step["supplementary_name"] for step in steps],
            ["起步接触 1", "双手匹配 1", "换点 1→2", "原点调整 2"],
        )
        self.assertEqual(steps[2]["source_hold_id"], 1)
        self.assertTrue(all(step["action_name_version"] == "zh-action-v1" for step in steps))

    def test_native_mask_polygon_preserves_model_edge_detail(self):
        mask = np.zeros((80, 120), dtype=np.uint8)
        points = np.asarray([
            [12, 18], [28, 18], [32, 25], [39, 20], [48, 27],
            [55, 19], [68, 22], [74, 34], [67, 46], [52, 43],
            [45, 55], [31, 49], [19, 55], [10, 39],
        ], dtype=np.int32)
        cv2.fillPoly(mask, [points], 255)

        contour = native_mask_polygon(mask)

        self.assertGreater(len(contour), 20)
        self.assertLessEqual(len(native_mask_polygon(mask, max_points=8)), 8)

    def test_route_map_fit_preserves_source_aspect_ratio(self):
        x, y, width, height = fit_aspect_rect(
            1280, 720, x=700, y=40, width=300, height=500,
        )

        self.assertEqual((x, width), (700, 300))
        self.assertEqual(y, 205)
        self.assertAlmostEqual(width / height, 1280 / 720, places=2)

    def test_route_map_zoom_uses_hold_bounds_without_distorting_shapes(self):
        full = fit_aspect_rect(1280, 720, x=700, y=40, width=300, height=500)
        zoomed = fit_hold_map_rect(
            [{"bbox": [.25, .2, .5, .6]}], 1280, 720,
            x=700, y=40, width=300, height=500,
        )

        self.assertGreater(zoomed[2], full[2])
        self.assertGreater(zoomed[3], full[3])
        self.assertAlmostEqual(zoomed[2] / zoomed[3], 1280 / 720, places=2)

    def test_touch_markers_keep_every_repeated_contact_sequence(self):
        markers = build_visible_action_markers([
            {"step": 1, "limb": "left_hand", "hold_id": 2, "start_source_frame": 4},
            {"step": 2, "limb": "right_hand", "hold_id": 5, "start_source_frame": 8},
            {"step": 3, "limb": "left_foot", "hold_id": 2, "start_source_frame": 12},
        ], 12)

        self.assertEqual([item["step"] for item in markers[2]], [1, 3])
        self.assertEqual([item["limb"] for item in markers[2]], ["left_hand", "left_foot"])

    def test_pose_render_timeline_smooths_only_between_adjacent_measured_samples(self):
        left_points = [[.2, .3] for _ in range(17)]
        right_points = [[.4, .5] for _ in range(17)]
        timeline = build_pose_render_timeline([
            {"source_frame_id": 0, "observed": True,
             "kpts_xy": left_points, "kpts_score": [.9] * 17},
            {"source_frame_id": 2, "observed": True,
             "kpts_xy": right_points, "kpts_score": [.9] * 17},
        ], 3)
        self.assertEqual(timeline[0]["render_mode"], "measured")
        self.assertEqual(timeline[1]["render_mode"], "interpolated")
        self.assertEqual(timeline[2]["render_mode"], "measured")
        self.assertEqual(timeline[1]["kpts_xy"][0], [.3, .4])


if __name__ == "__main__":
    unittest.main()
