"""Mocked model integration: template groups use this video's actual frame IDs."""
from copy import deepcopy
import json
import tempfile
from pathlib import Path
import unittest

from core.replay_coaching_engine import CoachingEngine, MAX_OUTPUT_TOKENS
from core.replay_template_plan import build_template_plan
from core.replay_template_renderer import validate_plan
from test_replay_coaching_engine import FakeProvider, write_library, write_video


def frame(index):
    return {"frame_id": f"frame-{index}", "time_seconds": float(index)}


def raw_group(ids=None, caption="左脚位置抬高，右手位置向上变化。"):
    ids = ids or ["frame-0", "frame-1", "frame-2"]
    return {"start_frame_id": ids[0], "end_frame_id": ids[-1], "evidence_frame_ids": ids,
            "caption": caption, "limb": "left_foot", "visible": True}


class GroupProvider(FakeProvider):
    def __init__(self, caption):
        super().__init__()
        self.caption = caption

    def __call__(self, **kwargs):
        result = super().__call__(**kwargs)
        if kwargs["stage"] == "observe":
            anchors = [json.loads(item["text"]) for item in kwargs["messages"][1]["content"][1:]
                       if item["type"] == "text"]
            middle = len(anchors) // 2
            result["content"]["action_groups"] = [
                raw_group([anchors[n]["frame_id"] for n in (0, middle // 2, middle)], self.caption),
                raw_group([anchors[n]["frame_id"] for n in (middle, (middle + len(anchors) - 1) // 2,
                                                            len(anchors) - 1)], "手部位置继续向上变化。")]
        return result


class AgentGroupTests(unittest.TestCase):
    def test_group_times_are_resolved_from_real_frames(self):
        groups, reasons = CoachingEngine._action_groups({"action_groups": [raw_group()]},
                                                       [frame(n) for n in range(3)], 2.)
        self.assertEqual(reasons, [])
        self.assertEqual(groups[0]["start_seconds"], 0.)
        self.assertEqual(groups[0]["end_seconds"], 2.)
        self.assertEqual(groups[0]["evidence"], [frame(n) for n in range(3)])
        self.assertEqual(groups[0]["evidence_status"], "sampled_observation")

    def test_invalid_reference_order_visibility_and_prescriptions_are_rejected(self):
        valid = raw_group()
        variants = []
        for changes in ({"end_frame_id": "frame-999"}, {"evidence_frame_ids": ["frame-0", "frame-0", "frame-2"]},
                        {"evidence_frame_ids": ["frame-0", "frame-999", "frame-2"]},
                        {"evidence_frame_ids": ["frame-0", "frame-2", "frame-1"]},
                        {"visible": False}, {"limb": ["left_foot"]}, {"start_seconds": .2},
                        {"caption": "你必须抬高左脚。"}):
            variants.append({**deepcopy(valid), **changes})
        for row in variants:
            with self.subTest(row=row):
                groups, reasons = CoachingEngine._action_groups({"action_groups": [row]},
                                                               [frame(n) for n in range(3)], 2.)
                self.assertEqual(groups, [])
                self.assertIn("action_group_unconfirmed", reasons)

    def test_overlapping_and_reverse_groups_do_not_reorder_into_false_sequence(self):
        rows = [raw_group(["frame-0", "frame-1", "frame-2"]),
                raw_group(["frame-1", "frame-2", "frame-3"]),
                raw_group(["frame-2", "frame-3", "frame-4"])]
        groups, reasons = CoachingEngine._action_groups({"action_groups": rows}, [frame(n) for n in range(5)], 4.)
        self.assertEqual([(row["start_seconds"], row["end_seconds"]) for row in groups], [(0., 2.), (2., 4.)])
        self.assertEqual(reasons, ["action_group_unconfirmed"])

    def test_existing_provider_budget_creates_video_specific_groups_without_new_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media, knowledge = root / "fixture.avi", root / "knowledge"
            write_video(media)
            write_library(knowledge)
            job = {"result": {"video": {"width": 160, "height": 120, "fps": 10., "frame_count": 50,
                                            "duration_seconds": 5.}, "attempt": {"contacts": []}}}
            plans = []
            for caption in ("左脚位置抬高，右手位置向上变化。", "右脚位置向外变化，左手位置抬高。"):
                provider = GroupProvider(caption)
                report = CoachingEngine(provider=provider, knowledge_root=knowledge).generate(
                    job, media, "source_video", {}, {}, lambda: False)
                self.assertEqual([row["stage"] for row in provider.calls], ["observe", "verify"])
                self.assertEqual(len(report["action_groups"]), 2)
                self.assertEqual(report["action_groups"][0]["caption"], caption)
                plan = build_template_plan(job, report)
                self.assertEqual(plan["shots"][1]["source_end_seconds"], 5.)
                self.assertEqual(validate_plan(plan), plan["frame_count"])
                self.assertEqual(sum(row["kind"] == "focus" for row in plan["shots"]), 1)
                self.assertFalse(any(row.get("claim_id") for row in plan["shots"]))
                plans.append(plan)
            self.assertNotEqual(plans[0]["shots"][0]["caption"], plans[1]["shots"][0]["caption"])
            self.assertEqual(MAX_OUTPUT_TOKENS, 1600)


if __name__ == "__main__":
    unittest.main()
