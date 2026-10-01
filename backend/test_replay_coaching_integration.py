"""Run the real report pipeline behind HTTP, with synthetic video and mocked cloud."""
import json
import shutil
import unittest

from core.climb_replay import REPLAY_OVERLAY_FILENAME
from core.replay_coaching_engine import CoachingEngine
from test_replay_coaching_engine import FakeProvider, write_library, write_video
import test_replay_coaching_lifecycle as lifecycle_fixture


class ReplayCoachingIntegrationTests(unittest.TestCase):
    def test_http_to_frames_to_knowledge_to_saved_report(self):
        fixture = lifecycle_fixture.ReplayCoachingLifecycleTests()
        fixture.setUp()
        try:
            video = fixture.root / "actual-synthetic.avi"
            write_video(video)
            target = fixture.store._path(fixture.job_id).parent / REPLAY_OVERLAY_FILENAME
            shutil.copyfile(video, target)
            fixture.store.register_overlay(fixture.job_id)
            # No real user material: make the preferred unannotated copy a
            # valid synthetic video as well, matching its stored time mapping.
            source, _ = fixture.store.media_file(fixture.job_id, "alice", "source_video")
            shutil.copyfile(video, source)
            job = fixture.store.get(fixture.job_id, "alice", private=True)
            fixture.store.update(fixture.job_id, video={**job["video"], "duration_seconds": 5})
            knowledge = fixture.root / "actual-knowledge"
            write_library(knowledge)
            provider = FakeProvider()
            fixture.manager.engine = CoachingEngine(provider=provider, knowledge_root=knowledge)
            submitted = fixture.create(personal={"height_cm": 168}, context={"goal": "核对脚点变化"})
            result = fixture.wait_report()
            self.assertEqual(result["id"], submitted["id"])
            self.assertEqual([call["stage"] for call in provider.calls], ["observe", "verify"])
            self.assertEqual(result["personal"], {"height_cm": 168})
            report = result["report"]
            self.assertEqual(len(report["observations"]), 1)
            self.assertEqual(report["observations"][0]["evidence"][0]["time_seconds"], 0)
            self.assertEqual(report["observations"][0]["knowledge_refs"], [])
            self.assertEqual(report["improvements"], [])
            self.assertEqual(report["risk_reminders"], [])
            self.assertEqual(report["next_attempt"]["kind"], "review")
            self.assertEqual(report["provenance"]["model"], "qwen3-vl-plus-2025-12-19")
            self.assertEqual(result["cost"]["status"], "estimated")
            self.assertEqual(result["cost"]["request_count"], 2)
            saved = fixture.store._path(fixture.job_id).read_text(encoding="utf-8")
            self.assertNotIn("data:image", saved)
            self.assertNotIn("private-original-name", json.dumps(provider.calls))
            repeat = fixture.create(personal={"height_cm": 168}, context={"goal": "核对脚点变化"})
            self.assertEqual(repeat["id"], submitted["id"])
            self.assertEqual(len(provider.calls), 2)
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
