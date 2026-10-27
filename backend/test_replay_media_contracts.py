"""Retained media behavior and legacy replacement seams; no model inference."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from core import climb_replay as replay


class ReplayMediaContractsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.mov'
        self.source.write_bytes(b'original-media')
        self.output = self.root / 'prepared.mp4'
        self.info = replay.VideoInfo(width=96, height=128, fps=20, frame_count=50,
                                     duration_seconds=2.5, size_bytes=self.source.stat().st_size)

    def tearDown(self):
        self.temp.cleanup()

    def test_media_import_does_not_load_replay_jobs_or_services(self):
        script = (
            'import sys; from core import replay_media; '
            'assert "core.climb_replay" not in sys.modules; '
            'assert not any(name == "services" or name.startswith("services.") for name in sys.modules)'
        )
        result = subprocess.run([sys.executable, '-B', '-c', script], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_media_exports_keep_function_constants_and_dto_identity(self):
        from core import replay_media
        for name in ('probe_video', 'validate_video_upload_type', 'validate_video',
                     'REPLAY_VIDEO_MIME_TYPES', 'REPLAY_VIDEO_SUFFIXES', 'VideoInfo', 'VideoLimits'):
            with self.subTest(name=name):
                self.assertIs(getattr(replay, name), getattr(replay_media, name))

    def test_probe_reads_native_metadata_and_releases_capture(self):
        capture = MagicMock()
        capture.isOpened.return_value = True
        capture.read.return_value = (True, np.zeros((128, 96, 3), dtype=np.uint8))
        capture.get.side_effect = lambda key: {
            replay.cv2.CAP_PROP_FPS: 20, replay.cv2.CAP_PROP_FRAME_COUNT: 50,
        }[key]
        with patch.object(replay.cv2, 'VideoCapture', return_value=capture), \
             patch.object(replay.subprocess, 'run') as fallback:
            self.assertEqual(replay.probe_video(self.source), self.info)
        capture.release.assert_called_once_with()
        fallback.assert_not_called()
        orientation = getattr(replay.cv2, 'CAP_PROP_ORIENTATION_AUTO', None)
        if orientation is not None:
            capture.set.assert_called_once_with(orientation, 1)

    def test_probe_fallback_preserves_rotation_and_bounded_metadata_command(self):
        capture = MagicMock()
        capture.isOpened.return_value = False
        diagnostic = ('Duration: 00:00:02.50\n'
                      'Video: h264, yuv420p, 96x128, 20 fps\nrotation of -90.0 degrees')
        with patch.object(replay.cv2, 'VideoCapture', return_value=capture), \
             patch('imageio_ffmpeg.get_ffmpeg_exe', return_value='test-ffmpeg'), \
             patch.object(replay.subprocess, 'run', return_value=SimpleNamespace(stderr=diagnostic)) as run:
            actual = replay.probe_video(self.source)
        self.assertEqual(actual, replace(self.info, width=128, height=96))
        capture.release.assert_called_once_with()
        run.assert_called_once_with(
            ['test-ffmpeg', '-hide_banner', '-i', str(self.source), '-t', '0', '-f', 'null', '-'],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=15,
        )

    def test_probe_read_error_still_releases_capture(self):
        capture = MagicMock()
        capture.isOpened.return_value = True
        capture.read.side_effect = RuntimeError('native read failed')
        with patch.object(replay.cv2, 'VideoCapture', return_value=capture):
            with self.assertRaisesRegex(RuntimeError, '^native read failed$'):
                replay.probe_video(self.source)
        capture.release.assert_called_once_with()

    def test_probe_fallback_timeout_keeps_public_error_private(self):
        capture = MagicMock()
        capture.isOpened.return_value = False
        with patch.object(replay.cv2, 'VideoCapture', return_value=capture), \
             patch('imageio_ffmpeg.get_ffmpeg_exe', return_value='test-ffmpeg'), \
             patch.object(replay.subprocess, 'run', side_effect=subprocess.TimeoutExpired(str(self.source), 15)):
            with self.assertRaises(ValueError) as error:
                replay.probe_video(self.source)
        self.assertEqual(str(error.exception), '服务器无法读取这个视频，可能是文件损坏或编码暂不支持；可更换视频重试，仍失败请联系管理员')
        self.assertNotIn(str(self.source), str(error.exception))
        capture.release.assert_called_once_with()

    def test_upload_type_keeps_suffix_mime_and_fast_path_contracts(self):
        for filename, mime, fast_path in (
            ('phone.MP4', 'video/mp4; codecs=avc1', True),
            ('phone.mp4', 'application/octet-stream', True),
            ('phone.mp4', '', True),
            ('phone.mp4', 'image/png', False),
            ('phone.MOV', 'application/octet-stream', False),
            ('phone.unknown', 'video/x-private-container', False),
        ):
            with self.subTest(filename=filename, mime=mime):
                self.assertIs(replay.validate_video_upload_type(filename, mime), fast_path)
        with self.assertRaisesRegex(ValueError, '请选择常见视频文件'):
            replay.validate_video_upload_type('program.exe', 'application/octet-stream')

    def test_video_validation_keeps_limits_orientation_and_byte_override(self):
        limits = replay.VideoLimits(max_bytes=32, max_duration_seconds=2.5,
                                    max_width=128, max_height=96, max_frames=50)
        replay.validate_video(self.info, limits)
        replay.validate_video(replace(self.info, width=128, height=96), limits)
        replay.validate_video(replace(self.info, size_bytes=33), limits, max_bytes=33)
        for info, error in (
            (replace(self.info, size_bytes=33), '视频不能超过'),
            (replace(self.info, duration_seconds=2.551), '试用阶段仅支持'),
            (replace(self.info, width=129), '试用阶段最高支持'),
            (replace(self.info, frame_count=51), '试用阶段最多处理'),
        ):
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                replay.validate_video(info, limits)

    def test_preparation_keeps_legacy_replacement_seams_and_call_order(self):
        events = []
        limits = replay.VideoLimits(max_duration_seconds=1)
        converted = replace(self.info, duration_seconds=1, frame_count=20)
        cancelled = lambda: False

        def probe(path):
            events.append('probe-source' if path == self.source else 'probe-output')
            return self.info if path == self.source else converted

        def convert(source, output, **kwargs):
            events.append('convert')
            self.assertEqual((source, output), (self.source, self.output))
            self.assertEqual(kwargs, dict(limits=limits, start_seconds=0, end_seconds=1, cancelled=cancelled))
            output.write_bytes(b'prepared-media')

        with patch.object(replay, 'validate_video_upload_type', side_effect=lambda *args: events.append('type')), \
             patch.object(replay, 'probe_video', side_effect=probe), \
             patch.object(replay, 'convert_video_to_mp4', side_effect=convert), \
             patch.object(replay, 'validate_video', side_effect=lambda *args: events.append('bounds')):
            result = replay.prepare_video_upload(
                self.source, filename='phone.mov', content_type='video/quicktime',
                limits=limits, output=self.output, cancelled=cancelled,
            )
        self.assertEqual(result, (self.output, converted))
        self.assertEqual(events, ['type', 'probe-source', 'convert', 'probe-output', 'bounds'])
        self.assertEqual(self.source.read_bytes(), b'original-media')

    def test_preparation_cancellation_removes_partial_output_and_keeps_source(self):
        def cancel(*args, **kwargs):
            self.output.write_bytes(b'partial')
            raise replay.ReplayCancelled()

        with patch.object(replay, 'probe_video', return_value=self.info), \
             patch.object(replay, 'convert_video_to_mp4', side_effect=cancel):
            with self.assertRaises(replay.ReplayCancelled):
                replay.prepare_video_upload(
                    self.source, filename='phone.mov', content_type='video/quicktime',
                    limits=replay.VideoLimits(), output=self.output,
                )
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), b'original-media')


if __name__ == '__main__':
    unittest.main()
