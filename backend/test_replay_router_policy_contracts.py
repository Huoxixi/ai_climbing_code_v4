"""Policy response data through real handlers; no HTTP server or external service."""
from contextlib import ExitStack
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import APIRouter, HTTPException, Request

from core import climb_replay as replay


class ReplayRouterPolicyContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.uploads = Mock()
        self.uploads.create.return_value = {"id": "constructed-upload"}
        self.store = SimpleNamespace(
            root=self.root, _lock=threading.RLock(), action_manager=object(),
            create_pending=Mock(return_value={"id": "constructed-job"}),
            get=Mock(return_value={"id": "constructed-job", "attempt": 5}),
            retry=Mock(return_value={"id": "constructed-job", "status": "queued"}),
        )
        self.manager = SimpleNamespace(ensure_capacity=Mock(), enqueue=Mock())
        # Unrelated feature routers and their workers are outside this contract.
        with ExitStack() as stack:
            stack.enter_context(patch.object(replay, "ChunkUploadStore", return_value=self.uploads))
            for target in ("core.replay_coaching.coaching_router", "core.replay_template.template_router",
                           "core.replay_action_jobs.action_router", "core.replay_preview.preview_router"):
                stack.enter_context(patch(target, return_value=APIRouter()))
            self.router = replay.create_climb_replay_router(
                self.store, self.manager, coaching_manager=object(), template_manager=object())
        self.request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b""})
        self.request.state.pilot_user = SimpleNamespace(username="constructed-owner")

    def endpoint(self, name):
        return next(route.endpoint for route in self.router.routes if getattr(route, "name", None) == name)

    def payload(self, **changes):
        values = dict(filename="constructed.mp4", content_type="video/mp4", size_bytes=5,
                      consent_version=replay.REPLAY_CONSENT_VERSION, consent_granted=True, skip_holds=True)
        values.update(changes)
        return replay.ReplayUploadCreate(**values)

    def stage(self, retention):
        consent = {"event": "local_processing_granted", "skip_holds": True, "granted_at": "original-clock"}
        metadata = {"filename": "constructed.mp4", "content_type": "video/mp4", "consent": consent,
                    "retention_mode": retention, "trim_start_seconds": 0, "trim_end_seconds": None}
        self.uploads.finish.return_value = ({"metadata": metadata}, self.root / "constructed.part")
        return metadata

    def test_policy_retains_local_execution_privacy_and_high_resolution_flags(self):
        policy = self.endpoint("get_consent_policy")(self.request)
        for key, expected in {"execution": "local", "region": "local", "requires_paid_consent": False,
                              "uploads_frames": False, "full_video_sent": False,
                              "keeps_high_resolution": True}.items():
            self.assertEqual(policy[key], expected)
        self.assertEqual(policy["provider"], "本机 RTMW-L")
        self.assertEqual(policy["service"], "RTMW-L 384×288")
        self.assertEqual(policy["model"], "rtmw-l-384x288-cocktail14-20231122")
        self.uploads.create.assert_not_called()
        self.manager.enqueue.assert_not_called()

    def test_policy_data_types_are_fresh_lists_not_the_shared_constant(self):
        types = ["constructed-frame", "constructed-keypoints"]
        with patch.object(replay, "REPLAY_CONSENT_DATA_TYPES", types):
            first = self.endpoint("get_consent_policy")(self.request)
            self.assertIsNot(first["data_types"], types)
            first["data_types"].append("caller-change")
            second = self.endpoint("get_consent_policy")(self.request)
            self.assertEqual(second["data_types"], ["constructed-frame", "constructed-keypoints"])
            self.assertIsNot(first["data_types"], second["data_types"])
            self.assertEqual(types, ["constructed-frame", "constructed-keypoints"])

    def test_policy_reads_legacy_globals_after_router_construction(self):
        with patch.multiple(replay, REPLAY_CONSENT_VERSION="late-version", REPLAY_CONSENT_PROVIDER="late-provider",
                            REPLAY_CONSENT_SERVICE="late-service", REPLAY_CONSENT_DATA_TYPES=["late-type"]):
            policy = self.endpoint("get_consent_policy")(self.request)
        self.assertEqual(policy["version"], "late-version")
        self.assertEqual(policy["provider"], "late-provider")
        self.assertEqual(policy["service"], "late-service")
        self.assertEqual(policy["data_types"], ["late-type"])

    def test_upload_grant_uses_current_owner_clock_and_policy_without_normalizing_staged_retention(self):
        with patch.multiple(replay, REPLAY_CONSENT_VERSION="late-version", REPLAY_CONSENT_PROVIDER="late-provider",
                            REPLAY_CONSENT_SERVICE="late-service", REPLAY_CONSENT_DATA_TYPES=["late-type"]), \
                patch.object(replay, "utcnow", return_value="late-clock"):
            result = self.endpoint("create_upload")(
                self.payload(consent_version="late-version", retention_mode="delete_after_processing"), self.request)
        self.assertIs(result, self.uploads.create.return_value)
        self.assertEqual(self.uploads.create.call_args.args, ("constructed-owner",))
        metadata = self.uploads.create.call_args.kwargs["metadata"]
        self.assertEqual(metadata["retention_mode"], "delete_after_processing")
        self.assertIsNone(metadata["route_id"])
        self.assertEqual(metadata["route_color"], "")
        self.assertEqual(metadata["consent"], {
            "event": "local_processing_granted", "attempt": 1, "version": "late-version",
            "provider": "late-provider", "service": "late-service", "region": "local",
            "data_types": ["late-type"], "purpose": "生成本次攀岩复盘所需的人体姿态关键点",
            "full_video_sent": False, "execution": "local", "uploads_frames": False,
            "granted_at": "late-clock", "skip_holds": True,
        })
        self.manager.enqueue.assert_not_called()

    def test_consent_rejection_priority_does_not_create_an_upload(self):
        for granted, expected_status, expected_detail in (
            (False, 422, "请先明确同意本次本地视频分析"),
            (True, 409, "数据处理告知已更新，请阅读最新说明并重新同意"),
        ):
            with self.subTest(granted=granted):
                with self.assertRaises(HTTPException) as failure:
                    self.endpoint("create_upload")(
                        self.payload(consent_version="outdated-version", consent_granted=granted), self.request)
                self.assertEqual(failure.exception.status_code, expected_status)
                self.assertEqual(failure.exception.detail, expected_detail)
        self.uploads.create.assert_not_called()
        self.store.create_pending.assert_not_called()

    def test_complete_upload_forces_keep_but_preserves_the_original_consent_object(self):
        for retention in ("delete_after_processing", "keep_private_original"):
            with self.subTest(retention=retention):
                metadata = self.stage(retention)
                self.uploads.discard.reset_mock()
                self.manager.ensure_capacity.reset_mock()
                result = self.endpoint("complete_upload")("constructed-upload", self.request)
                submitted = self.store.create_pending.call_args.kwargs
                self.assertEqual(submitted["owner"], "constructed-owner")
                self.assertEqual(submitted["retention_mode"], "keep_private_original")
                self.assertIs(submitted["consent"], metadata["consent"])
                self.assertEqual(submitted["consent"]["granted_at"], "original-clock")
                self.assertIs(result, self.store.create_pending.return_value)
                self.assertEqual(self.manager.ensure_capacity.call_count, 2)
                self.uploads.discard.assert_called_once_with("constructed-upload")

    def test_invalid_staged_retention_is_rejected_and_discarded_before_job_creation(self):
        self.stage("invalid-retention")
        with self.assertRaises(HTTPException) as failure:
            self.endpoint("complete_upload")("constructed-upload", self.request)
        self.assertEqual(failure.exception.status_code, 422)
        self.assertEqual(failure.exception.detail, "请选择有效的视频保留方式")
        self.store.create_pending.assert_not_called()
        self.manager.enqueue.assert_not_called()
        self.uploads.discard.assert_called_once_with("constructed-upload")

    def test_retry_grant_uses_latest_attempt_and_late_bound_clock(self):
        payload = replay.ReplayRetryCreate(consent_version=replay.REPLAY_CONSENT_VERSION, consent_granted=True)
        with patch.object(replay, "utcnow", return_value="retry-clock"):
            result = self.endpoint("retry_job")("constructed-job", payload, self.request)
        self.store.get.assert_called_once_with("constructed-job", "constructed-owner", private=True)
        args = self.store.retry.call_args.args
        self.assertEqual(args[:2], ("constructed-job", "constructed-owner"))
        self.assertEqual(args[2]["attempt"], 6)
        self.assertEqual(args[2]["event"], "granted")
        self.assertEqual(args[2]["granted_at"], "retry-clock")
        self.assertIs(result, self.store.retry.return_value)
        self.manager.enqueue.assert_called_once_with("constructed-job")


if __name__ == "__main__":
    unittest.main()
