"""Native-frame sampling plans. Display interpolation is never evidence."""
import math
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal

VERSION = 'native-pose-sampling-v1'


class FocusWindow(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    fps: Literal[15, 20] = 20

    @model_validator(mode='after')
    def ordered(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError('重点片段结束时间须晚于开始时间')
        return self


def native_plan(video, base_fps=10, windows=()):
    fps = min(float(base_fps), float(video.fps))
    if not math.isfinite(fps) or not 1 <= fps <= 20:
        raise ValueError('Invalid native pose sampling rate')
    positions = set(np.rint(np.arange(0, video.duration_seconds, 1 / fps) * video.fps).astype(int))
    accepted = []
    for row in windows:
        row = row.model_dump() if isinstance(row, FocusWindow) else FocusWindow(**row).model_dump()
        start, end = row['start_seconds'], row['end_seconds']
        if end > video.duration_seconds + 1e-6:
            raise ValueError('重点片段超出视频时长')
        effective = min(row['fps'], video.fps)
        positions.update(np.rint(np.arange(start, end, 1 / effective) * video.fps).astype(int))
        accepted.append({**row, 'effective_fps': effective, 'reason': 'user_selected'})
    positions = np.asarray(sorted(p for p in positions if 0 <= p < video.frame_count), dtype=int)
    gaps = np.diff(positions) / video.fps
    return fps, positions, {'version': VERSION, 'base_fps': fps, 'focus_windows': accepted,
        'native_only': True, 'planned_frames': len(positions),
        'max_gap_seconds': round(float(max(gaps)), 6) if len(gaps) else None,
        'automatic_focus_validation': 'pending_real_video_review'}


def speed_focus_windows(samples, source_fps, *, video=None, threshold=1.4, target_fps=20):
    """Offline experimental proposals only; never silently changes a job's plan."""
    windows = []
    if not video or not video.get('width') or not video.get('height'):
        return windows
    aspect = np.asarray([video['width'],video['height']], float)
    aspect /= min(aspect)
    for a, b in zip(samples, samples[1:]):
        dt = b.get('time_seconds', 0) - a.get('time_seconds', 0)
        if not 0 < dt <= .3 or not a.get('observed') or not b.get('observed'):
            continue
        try:
            p, q = np.asarray(a['kpts_xy'])*aspect, np.asarray(b['kpts_xy'])*aspect
            valid = (np.asarray(a['kpts_score']) >= .5) & (np.asarray(b['kpts_score']) >= .5)
            scale = np.linalg.norm(p[5] - p[11])
            if scale <= .02 or not all(valid[i] for i in (5, 6, 11, 12)):
                continue
            root = {9: 5, 10: 6, 15: 11, 16: 12}
            speed = max((np.linalg.norm((q[i]-q[root[i]])-(p[i]-p[root[i]])) / dt / scale
                         for i in root if valid[i] and valid[root[i]]), default=0)
            if speed > threshold:
                windows.append({'start_seconds': a['time_seconds'], 'end_seconds': b['time_seconds'],
                                'fps': min(target_fps, source_fps), 'reason': 'speed_signal',
                                'status': 'experimental_proposal'})
        except (KeyError, ValueError, IndexError, TypeError):
            continue
    return windows
