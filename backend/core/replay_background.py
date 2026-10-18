"""Select a real empty frame and register it to the saved wall coordinates."""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from .replay_hold_fusion import align_to_reference
from .replay_observation_validity import registration_reason

VERSION = 'empty-scene-wall-reference-v2'
REASONS = {
    'not_started': '无人背景尚未检查。',
    'running': '正在本地检查无人背景…',
    'no_empty_frame': '未找到可靠的无人画面，不能单独显示真实场景骨架。',
    'camera_moved': '镜头发生移动，不能使用固定无人背景。',
    'unverified': '无法可靠核验无人背景或镜头稳定性。',
    'source_missing': '原片不可用，无法检查无人背景。',
}


def person_detector():
    # Reuse the installed, pinned detector without loading or running RTMW.
    from .replay_pose_rtmw import model_directory, MODEL_DIRECTORY
    directory = model_directory()
    expected = json.loads((MODEL_DIRECTORY / 'manifest.json').read_text('utf8'))
    actual = json.loads((directory / 'manifest.json').read_text('utf8'))
    if actual != expected:
        raise ValueError('Detector manifest mismatch')
    item = next(item for item in expected['files'] if item['file'] == 'detector.onnx')
    path = directory / item['file']
    with path.open('rb') as stream:
        if path.stat().st_size != item['bytes'] or hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
            raise ValueError('Detector checksum mismatch')
    from vendor.rtmlib import YOLOX
    return YOLOX(str(path), model_input_size=(640, 640), score_thr=.2, device='cpu')


def contains_person(frame, detect):
    # Overlapping crops retain edge/partial people that shrink in a full view.
    h, w = frame.shape[:2]
    views = [frame]
    for x, y in ((0, 0), (.35, 0), (0, .35), (.35, .35)):
        views.append(frame[int(y*h):min(h, int((y+.65)*h)), int(x*w):min(w, int((x+.65)*w))])
    for view in views:
        boxes = np.asarray(detect(view))
        if boxes.size:
            # Unexpected/nonfinite detections are uncertainty, never an empty frame.
            return True
    return False


def unavailable(reason):
    return {'version': VERSION, 'status': 'unavailable', 'reason': reason, 'message': REASONS[reason]}


def prepare_background(source, target, result, *, detect=None, cancelled=lambda: False, align=align_to_reference):
    """Select actual empty pixels; only the selected frame needs registration.

    Playback and export already map each qualified pose to wall-reference space.
    Mapping that space to this frame also supports a moving source camera. A
    whole-clip fixed-camera scan is unnecessary and used to block playback for
    many minutes. Never infer an empty scene from a missing pose observation.
    """
    capture = cv2.VideoCapture(str(source))
    try:
        fps, count = capture.get(cv2.CAP_PROP_FPS), int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        reference_id = int((result.get('hold_evidence') or {}).get('reference_frame') or 0)
        capture.set(cv2.CAP_PROP_POS_FRAMES, reference_id)
        okay, reference = capture.read()
        if not okay or not fps > 0 or count < 1:
            return unavailable('unverified')
        h, w = reference.shape[:2]
        if (w, h) != (result['video']['width'], result['video']['height']):
            return unavailable('unverified')
        detect = detect or person_detector()
        stride = max(1, round(fps / 2))
        best, tested = None, set()
        checked = 0
        empty_unregistered = False

        def candidate(index, frame):
            nonlocal checked, empty_unregistered
            checked += 1
            if contains_person(frame, detect):
                return None
            if cancelled():
                raise InterruptedError()
            matrix, diagnostics = align(frame, reference)
            if matrix is None or registration_reason(matrix, diagnostics):
                empty_unregistered = True
                return None
            return (index, frame.copy(), np.linalg.inv(matrix))

        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        for index in range(count):
            if cancelled():
                raise InterruptedError()
            okay, frame = capture.read()
            if not okay:
                return unavailable('unverified')
            if index % stride == 0 or index == count-1:
                tested.add(index)
                best = candidate(index, frame)
                if best is not None:
                    break
        if best is None:
            # Do not miss an empty frame just because it falls between samples.
            capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            for index in range(count):
                if cancelled():
                    raise InterruptedError()
                okay, frame = capture.read()
                if not okay:
                    return unavailable('unverified')
                if index not in tested:
                    best = candidate(index, frame)
                    if best is not None:
                        break
        if best is None:
            return unavailable('unverified' if empty_unregistered else 'no_empty_frame')
        if cancelled():
            raise InterruptedError()
        temporary = Path(target).with_suffix('.tmp.png')
        try:
            encoded, pixels = cv2.imencode('.png', best[1])
            if not encoded:
                raise OSError('Cannot save background')
            pixels.tofile(temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return {'version': VERSION, 'status': 'ready', 'source_frame_id': best[0],
                'reference_to_background': best[2].tolist(), 'width': w, 'height': h,
                'checked_frames': checked, 'message': ''}
    finally:
        capture.release()
