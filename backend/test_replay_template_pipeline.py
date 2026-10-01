"""Synthetic video through the real Agent, planner, queue and media renderer.

Only the cloud provider and approved-claim registry are test doubles. Their
responses establish wiring/commit behavior, never real coaching accuracy.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from core.climb_replay import ClimbReplayStore, REPLAY_CONSENT_VERSION, REPLAY_RETENTION_KEEP, VideoInfo
from core.replay_coaching import CoachingCreate, CoachingManager, CONSENT_VERSION
from core.replay_coaching_engine import CoachingEngine
from core.replay_template import TemplateVideoManager
from core.replay_template_plan import build_template_plan
from core.replay_template_renderer import validate_plan
from test_replay_coaching_engine import FakeProvider, FixtureRegistry, write_library


class PipelineRegistry(FixtureRegistry):
    # This isolated fixture is patched into both policy and engine validation.
    # Production knowledge files and their review status remain untouched.
    fingerprint = "synthetic-pipeline-approved-claim-v1"


class ActionGroupProvider(FakeProvider):
    def __call__(self, *, stage, messages, model, cancelled):
        response = super().__call__(stage=stage, messages=messages, model=model, cancelled=cancelled)
        if stage == "observe":
            anchors = [json.loads(item["text"]) for item in messages[1]["content"][1:]
                       if item["type"] == "text"]
            middle = len(anchors) // 2
            groups = []
            for points, caption, limb in (
                (anchors[:middle + 1], "左脚移动，随后右手位置改变。", "left_foot"),
                (anchors[middle:], "右手继续上移，左脚保持位置。", "right_hand"),
            ):
                groups.append({"start_frame_id": points[0]["frame_id"],
                               "end_frame_id": points[-1]["frame_id"], "caption": caption,
                               "limb": limb, "visible": True,
                               "evidence_frame_ids": [point["frame_id"] for point in points]})
            response["content"]["action_groups"] = groups
        return response


def write_source(path):
    width, height, fps, count = 160, 200, 10, 24
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        raise unittest.SkipTest("Synthetic fixture encoder unavailable")
    try:
        for number in range(count):
            frame = np.full((height, width, 3), 20 + number * 7, np.uint8)
            cv2.circle(frame, (30 + number * 3, 80), 7, (0, 230, 100), -1)
            writer.write(frame)
    finally:
        writer.release()
    return VideoInfo(width=width, height=height, fps=fps, frame_count=count,
                     duration_seconds=count / fps, size_bytes=path.stat().st_size)


class TemplatePipelineTests(unittest.TestCase):
    def test_real_agent_manager_planner_and_renderer_complete_without_network_or_pose_inference(self):
        with tempfile.TemporaryDirectory(prefix="replay-template-pipeline-") as directory:
            root = Path(directory)
            source = root / "synthetic.mp4"
            info = write_source(source)
            original_digest = hashlib.sha256(source.read_bytes()).hexdigest()
            knowledge = root / "knowledge"
            write_library(knowledge)
            store = ClimbReplayStore(root / "store")
            job = store.create(owner="pipeline-owner", route_id=None, route_color="cyan", source=source,
                               original_name="synthetic.mp4", info=info,
                               consent={"event": "granted", "attempt": 1, "version": REPLAY_CONSENT_VERSION},
                               retention_mode=REPLAY_RETENTION_KEEP)
            job_id = job["id"]
            result = {"schema_version": 2, "video": job["video"],
                      "analysis": {"sampling": {"effective_fps": 4}}, "pose_samples": [],
                      "holds": [], "attempt": {"action_steps": [], "segments": []}}
            store.update(job_id, status="succeeded", result=copy.deepcopy(result))
            actual_source, _ = store.media_file(job_id, "pipeline-owner", "source_video")
            provider = ActionGroupProvider()
            coaching = template = None
            with patch.dict("os.environ", {"REPLAY_COACHING_MODEL": "qwen3-vl-plus-2025-12-19"}), \
                 patch("core.replay_coaching_knowledge.ClaimRegistry", PipelineRegistry), \
                 patch("core.replay_coaching.ClaimRegistry", PipelineRegistry), \
                 patch("httpx.Client", side_effect=AssertionError("No network in pipeline fixture")), \
                 patch("core.climb_replay.AliyunReplayAnalyzer.analyze",
                       side_effect=AssertionError("No upstream recognition in template creation")) as upstream:
                try:
                    engine = CoachingEngine(provider=provider, knowledge_root=knowledge)
                    coaching = CoachingManager(store, engine, enabled=True)
                    # No injected planner/renderer: the manager imports the actual implementations.
                    template = TemplateVideoManager(store, coaching)
                    payload = CoachingCreate(consent_version=CONSENT_VERSION, consent_granted=True,
                        adult_confirmed=True, indoor_bouldering_confirmed=True, budget_accepted=True,
                        context={"goal": "核对脚部衔接"})
                    task = template.create(job_id, "pipeline-owner", payload)
                    deadline = time.monotonic() + 90
                    while time.monotonic() < deadline:
                        state = template.get(job_id, "pipeline-owner")
                        if state["status"] not in {"queued", "waiting_report", "running"}:
                            break
                        time.sleep(.05)
                    self.assertEqual(state["status"], "succeeded", state)
                    self.assertTrue(state["media_ready"])
                    self.assertEqual(state["media_version"], task["id"])
                    final_job = store.get(job_id, "pipeline-owner", private=True)
                    report = final_job["coaching"]["report"]
                    self.assertEqual(len(report["action_groups"]), 2)
                    self.assertEqual(report["observations"][0]["independent_review"]["status"], "verified")
                    self.assertTrue(report["improvements"], report["reason_codes"])
                    self.assertEqual([call["stage"] for call in provider.calls], ["observe", "verify", "compose"])
                    self.assertTrue(all(any(item["type"] == "image_url" for item in call["messages"][1]["content"])
                                        for call in provider.calls[:2]))
                    plan = final_job["template_video"]["plan"]
                    self.assertEqual(plan, build_template_plan(final_job, report))
                    self.assertEqual([shot["kind"] for shot in plan["shots"]],
                                     ["action", "action", "data", "data", "focus"])
                    self.assertEqual(plan["shots"][1]["source_end_seconds"], info.duration_seconds)
                    focus = plan["shots"][-1]
                    self.assertEqual(focus["claim_id"], "CLAIM-TEST-1")
                    self.assertEqual(len(focus["caption_steps"]), 3)
                    self.assertEqual(plan["provenance"]["timing_basis"], "source_video_timestamps")
                    self.assertEqual(final_job["result"], result)
                    upstream.assert_not_called()

                    output = template.media_file(job_id, "pipeline-owner")
                    expected_frames = validate_plan(plan)
                    last_action_frame = sum(round(shot["duration_seconds"] * 30)
                                            for shot in plan["shots"] if shot["kind"] == "action") - 1
                    cap = cv2.VideoCapture(str(output))
                    count, first, completion = 0, None, None
                    try:
                        self.assertTrue(cap.isOpened())
                        self.assertEqual(round(cap.get(cv2.CAP_PROP_FPS)), 30)
                        while True:
                            ok, frame = cap.read()
                            if not ok:
                                break
                            self.assertEqual(frame.shape[:2], (info.height, info.width))
                            if count == 0:
                                first = frame.copy()
                            if count == last_action_frame:
                                completion = frame.copy()
                            count += 1
                    finally:
                        cap.release()
                    self.assertEqual(count, expected_frames)
                    self.assertEqual(count, final_job["template_video"]["metrics"]["frame_count"])
                    self.assertTrue(final_job["template_video"]["metrics"]["fully_decoded"])
                    source_cap = cv2.VideoCapture(str(actual_source))
                    try:
                        source_cap.set(cv2.CAP_PROP_POS_FRAMES, info.frame_count - 1)
                        ok, source_finish = source_cap.read()
                    finally:
                        source_cap.release()
                    self.assertTrue(ok)
                    # Uncovered right-centre pixels distinguish the true final native
                    # frame from a skipped finishing movement or a synthetic still.
                    crop = np.s_[85:105, 145:155]
                    self.assertLess(np.abs(completion[crop].astype(float)
                                           - source_finish[crop].astype(float)).mean(), 12)
                    self.assertGreater(completion[crop].mean() - first[crop].mean(), 120)
                    self.assertEqual(hashlib.sha256(actual_source.read_bytes()).hexdigest(), original_digest)
                    self.assertEqual(template.create(job_id, "pipeline-owner", payload)["id"], task["id"])
                    self.assertEqual(len(provider.calls), 3)
                finally:
                    if template:
                        template.close()
                    if coaching:
                        coaching.close()


if __name__ == "__main__":
    unittest.main()
