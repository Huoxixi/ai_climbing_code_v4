"""Exercise shared admission and cleanup using real child processes."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from core import replay_resources as resources
from core.photo_route_inference_lock import serialized_inference


class ResourceAdmissionTests(unittest.TestCase):
    def test_photo_and_video_stages_are_serialized_and_release_on_failure(self):
        entered = []
        release = threading.Event()

        @serialized_inference
        def photo():
            entered.append("photo")
            release.wait(2)

        def video():
            with resources.high_resource_slot():
                entered.append("video")

        first = threading.Thread(target=photo)
        second = threading.Thread(target=video)
        first.start()
        deadline = time.monotonic() + 2
        while not entered and time.monotonic() < deadline:
            time.sleep(.01)
        second.start()
        time.sleep(.15)
        self.assertEqual(entered, ["photo"])
        release.set()
        first.join(3)
        second.join(3)
        self.assertEqual(entered, ["photo", "video"])
        with self.assertRaises(ValueError):
            with resources.high_resource_slot():
                raise ValueError("failure")
        with resources.high_resource_slot():
            pass

    def test_waiting_cancel_does_not_take_slot(self):
        cancelled = threading.Event()
        outcome = []

        def waiter():
            try:
                with resources.high_resource_slot(cancelled=cancelled.is_set):
                    outcome.append("entered")
            except InterruptedError:
                outcome.append("cancelled")

        with resources.high_resource_slot():
            thread = threading.Thread(target=waiter)
            thread.start()
            cancelled.set()
            thread.join(2)
            self.assertEqual(outcome, ["cancelled"])

    def test_nested_stage_rejected_without_hang(self):
        with resources.high_resource_slot():
            with self.assertRaisesRegex(RuntimeError, "nested"):
                with resources.high_resource_slot():
                    pass

    def test_cross_process_serialization(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "entered"
            code = ("from core.replay_resources import high_resource_slot; "
                    "from pathlib import Path; import sys\n"
                    "with high_resource_slot(): Path(sys.argv[1]).write_text('ok')")
            with resources.high_resource_slot():
                process = subprocess.Popen([sys.executable, "-c", code, str(marker)],
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    time.sleep(.3)
                    self.assertFalse(marker.exists())
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
            process.wait(timeout=5)
            self.assertEqual(process.returncode, 0)
            self.assertTrue(marker.exists())


@unittest.skipIf(resources.psutil is None, "resource monitoring dependency unavailable")
class WorkerProtectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.reference = self.root / "reference.png"
        self.manifest = self.root / "manifest.json"
        self.output = self.root / "tail.webm"
        self.metrics = self.root / "metrics.json"
        self.reference.write_bytes(b"test")
        self.manifest.write_text("{}")
        self.processes = []
        self.original_popen = subprocess.Popen

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
                process.wait()
        self.temporary.cleanup()

    def launch_sleeper(self, command, **kwargs):
        # A genuine subprocess tree makes cancellation more than a mock assertion.
        code = ("import subprocess,sys,time; from pathlib import Path; "
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
                "Path(sys.argv[2]).write_bytes(b'unfinished frame'); "
                "Path(sys.argv[1]).write_text(str(child.pid)); time.sleep(30)")
        process = self.original_popen([sys.executable, "-c", code, str(self.root / "child.pid"),
                                      str(self.output.with_name(f'.{self.output.name}.partial.webm'))], **kwargs)
        self.processes.append(process)
        return process

    def run_worker(self, **kwargs):
        return resources.run_visual_worker(self.reference, self.manifest, self.output, self.metrics,
                                          min_start_available_mib=0, min_running_available_mib=0, **kwargs)

    def test_admission_does_not_launch_when_low_memory(self):
        with patch.object(resources.psutil, "virtual_memory", return_value=SimpleNamespace(available=100)), \
             patch.object(resources.subprocess, "Popen") as popen:
            with self.assertRaises(resources.VisualRenderFailure) as caught:
                resources.run_visual_worker(self.reference, self.manifest, self.output, self.metrics)
            self.assertEqual(caught.exception.code, "memory_admission")
            popen.assert_not_called()

    def test_timeout_stops_child_tree_and_releases_slot(self):
        with patch.object(resources.subprocess, "Popen", side_effect=self.launch_sleeper):
            with self.assertRaises(resources.VisualRenderFailure) as caught:
                self.run_worker(timeout_seconds=.8)
        self.assertEqual(caught.exception.code, "timeout")
        self.assertIsNotNone(self.processes[0].poll())
        child = int((self.root / "child.pid").read_text())
        self.assertFalse(resources.psutil.pid_exists(child))
        self.assertFalse(self.output.exists())
        self.assertFalse(self.metrics.exists())
        self.assertFalse(self.output.with_name(f'.{self.output.name}.partial.webm').exists())
        with resources.high_resource_slot():
            pass

    def test_cancel_stops_child_tree(self):
        with patch.object(resources.subprocess, "Popen", side_effect=self.launch_sleeper):
            with self.assertRaises(InterruptedError):
                self.run_worker(cancelled=lambda: (self.root / "child.pid").exists())
        child = int((self.root / "child.pid").read_text())
        self.assertFalse(resources.psutil.pid_exists(child))
        self.assertIsNotNone(self.processes[0].poll())

    def test_memory_limit_stops_process(self):
        with patch.object(resources.subprocess, "Popen", side_effect=self.launch_sleeper):
            with self.assertRaises(resources.VisualRenderFailure) as caught:
                self.run_worker(max_tree_mib=.001)
        self.assertEqual(caught.exception.code, "memory_limit")
        self.assertIsNotNone(self.processes[0].poll())

    def test_existing_output_is_never_overwritten(self):
        self.output.write_bytes(b"existing playable version")
        with self.assertRaises(ValueError):
            self.run_worker()
        self.assertEqual(self.output.read_bytes(), b"existing playable version")


if __name__ == "__main__":
    unittest.main()
