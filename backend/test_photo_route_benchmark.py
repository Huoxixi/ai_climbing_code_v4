"""Verify deadlines and evidence isolation without loading a neural model."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from scripts.run_photo_route_benchmark import run_process


class PhotoRouteBenchmarkTests(unittest.TestCase):
    def test_success_captures_output_and_exit_status(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "run"
            result = run_process([sys.executable, "-c", "print('local-result')"], output, 5)
            self.assertEqual(result["status"], "completed")
            self.assertIn("local-result", (output / "stdout.log").read_text())
            self.assertEqual(json.loads((output / "process.json").read_text())["returncode"], 0)

    def test_failure_is_never_reported_as_success(self):
        with tempfile.TemporaryDirectory() as root:
            result = run_process([sys.executable, "-c", "raise RuntimeError('model failed')"],
                                 Path(root) / "run", 5)
            self.assertEqual(result["status"], "failed")
            self.assertNotEqual(result["returncode"], 0)

    @unittest.skipUnless(sys.platform == "win32" or sys.platform.startswith("linux"), "RSS reader is OS-specific")
    def test_memory_measures_interpreter_not_only_virtualenv_launcher(self):
        with tempfile.TemporaryDirectory() as root:
            result = run_process([sys.executable, "-c",
                                  "import time; payload=bytearray(32*1024*1024); time.sleep(.5)"],
                                 Path(root) / "run", 5)
            self.assertEqual(result["status"], "completed")
            self.assertGreater(result["peak_resident_mib"], 32)

    def test_hard_timeout_kills_child_before_late_write(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "run"
            late = Path(root) / "late.txt"
            command = [sys.executable, "-c",
                       "import time,sys; from pathlib import Path; time.sleep(1); Path(sys.argv[1]).write_text('late')",
                       str(late)]
            result = run_process(command, output, .2)
            self.assertEqual(result["status"], "timed_out")
            self.assertLess(result["wall_seconds"], 1)
            self.assertNotEqual(result["returncode"], 0)
            time.sleep(1)
            self.assertFalse(late.exists(), "timed out inference must not keep running")

    def test_cancel_terminates_child_and_existing_evidence_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "run"
            command = [sys.executable, "-c", "import time; time.sleep(10)"]
            result = run_process(command, output, 5, cancelled=lambda: True)
            self.assertEqual(result["status"], "cancelled")
            before = (output / "process.json").read_bytes()
            with self.assertRaises(FileExistsError):
                run_process(command, output, 5)
            self.assertEqual(before, (output / "process.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
