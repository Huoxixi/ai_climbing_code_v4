import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from core.climb_replay import ClimbReplayStore, ReplaySegmentReview


class ReplayReviewTests(unittest.TestCase):
    def test_review_is_owner_scoped_versioned_and_reversible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.mp4"
            source.write_bytes(b"review-test")
            store = ClimbReplayStore(root / "store")
            job = store.create_pending(
                owner="alice", route_id="route-1", route_color="蓝色",
                source=source, original_name="sample.mp4", content_type="video/mp4",
                consent={"event": "granted"}, retention_mode="keep_private_original",
                saved_route_reference={"board_id": "board-1", "asset_path": "unused",
                                       "members": [{"object_id": "H04"}, {"object_id": "H09"}]},
            )
            store.update(job["id"], status="succeeded", video={"fps": 4, "duration_seconds": 3},
                         result={"attempt": {"segments": [{"id": "right_hand:1:2",
                                                             "limb": "right_hand", "comparable": False,
                                                             "reason": "unconfirmed_hold_identity",
                                                             "duration_seconds": 1.5}]}})
            review = ReplaySegmentReview(limb="right_hand", source_route_hold_id="H04",
                                         target_route_hold_id="H09", start_time_seconds=.5,
                                         end_time_seconds=2, technique_label="锁臂")
            with self.assertRaises(HTTPException):
                store.review_segment(job["id"], "bob", "right_hand:1:2", review)
            updated = store.review_segment(job["id"], "alice", "right_hand:1:2", review)
            self.assertEqual(updated["reviewed_segments"][0]["source"], "user_confirmed")
            self.assertEqual(updated["segment_review_history"][0]["version"], 1)
            reverted = store.review_segment(job["id"], "alice", "right_hand:1:2", None)
            self.assertFalse(reverted["reviewed_segments"][0]["comparable"])
            self.assertEqual(reverted["segment_review_history"][-1]["operation"], "revert")


if __name__ == "__main__":
    unittest.main()
