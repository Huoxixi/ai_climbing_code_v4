import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from core.climb_replay import (ClimbReplayManager, ClimbReplayStore,
                               ReplayConfigurationError, VideoLimits,
                               VlmRunReplayAnalyzer, create_climb_replay_router)


def make_video(path: Path, *, frames=8, fps=4.0, width=96, height=64):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise unittest.SkipTest("当前 OpenCV 环境不能编码 MP4")
    for index in range(frames):
        image = np.full((height, width, 3), 20 + index, dtype=np.uint8)
        writer.write(image)
    writer.release()


class FakeAnalyzer:
    def analyze(self, video, *, route_color, video_info, progress, cancelled):
        progress("测试分析", 50)
        return {"schema_version": 1, "route": {"color": route_color},
                "video": {"frame_count": video_info.frame_count},
                "attempt": {"sequence": [1, 2], "topped_out": True}}


class ClimbReplayApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = ClimbReplayStore(root)
        self.manager = ClimbReplayManager(self.store, FakeAnalyzer())
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
        ))
        self.client = TestClient(app)
        self.video = root / "sample.mp4"
        make_video(self.video)

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

    def test_upload_runs_in_owner_scoped_single_worker(self):
        with self.video.open("rb") as source:
            response = self.client.post(
                "/api/climb-replay/jobs",
                data={"route_id": "route-1"},
                files={"video": ("attempt.mp4", source, "video/mp4")},
            )
        self.assertEqual(response.status_code, 202)
        job = self.wait(response.json()["id"])
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["route_color"], "绿色")
        self.assertEqual(job["result"]["attempt"]["sequence"], [1, 2])
        self.assertNotIn("input_path", job)
        self.assertEqual(self.client.get("/api/climb-replay/jobs").status_code, 200)
        self.assertEqual(self.client.get(
            f"/api/climb-replay/jobs/{job['id']}", headers={"x-user": "other"}).status_code, 404)

    def test_proxy_safe_chunk_upload_creates_job(self):
        content = self.video.read_bytes()
        started = self.client.post('/api/climb-replay/uploads', json={
            'filename':'attempt.mp4', 'content_type':'video/mp4', 'size_bytes':len(content),
            'route_id':'route-1', 'route_color':'',
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

    def test_rejects_non_mp4_and_overlong_video(self):
        response = self.client.post(
            "/api/climb-replay/jobs",
            data={"route_color": "green"},
            files={"video": ("attempt.mov", b"not-video", "video/quicktime")},
        )
        self.assertEqual(response.status_code, 422)
        long_video = Path(self.temp.name) / "long.mp4"
        make_video(long_video, frames=24, fps=4.0)
        with long_video.open("rb") as source:
            response = self.client.post(
                "/api/climb-replay/jobs",
                data={"route_color": "green"},
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

    def test_missing_cloud_key_fails_before_any_upload(self):
        with patch.dict("os.environ", {"VLMRUN_API_KEY": ""}):
            analyzer = VlmRunReplayAnalyzer(api_key="")
            with self.assertRaises(ReplayConfigurationError):
                analyzer._client()

    def test_hold_consensus_and_contact_summary_are_deterministic(self):
        detections = [
            [{"bbox_xywh": [0.1, 0.8, 0.1, 0.08], "score": 0.9},
             {"bbox_xywh": [0.5, 0.2, 0.1, 0.08], "score": 0.95}],
            [{"bbox_xywh": [0.105, 0.8, 0.1, 0.08], "score": 0.85},
             {"bbox_xywh": [0.505, 0.2, 0.1, 0.08], "score": 0.9}],
        ]
        holds = VlmRunReplayAnalyzer._consensus_holds(detections)
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
        result = VlmRunReplayAnalyzer._contacts(records, holds, fps=4.0)
        self.assertEqual(result["sequence"], [1, 2])
        self.assertTrue(result["topped_out"])
        self.assertEqual(result["completion_frame"], 5)
        self.assertIn("left_hand", result["per_limb"])


if __name__ == "__main__":
    unittest.main()
