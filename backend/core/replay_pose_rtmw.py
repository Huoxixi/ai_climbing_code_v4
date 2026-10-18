"""Default offline RTMW-L 384x288 pose provider. Aliyun is historical only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
import time
from copy import deepcopy

import numpy as np

from core.climb_replay import (ReplayAnalyzerBase, ReplayConfigurationError,
                               REPLAY_PIPELINE_VERSION, VideoInfo)
from core.replay_hold_colors import REPLAY_COLOUR_VERSION
from core.replay_person_tracking import (VERSION as TRACKING_VERSION, MAX_RECOVERY_SECONDS,
                                         appearance, appearance_distance, near_route, recovery_geometry,
                                         route_in_frame)

MODEL = 'rtmw-l-384x288-cocktail14-20231122'
MODEL_DIRECTORY = Path(__file__).resolve().parents[1] / 'model_assets/rtmw-l-384x288'


def model_directory() -> Path:
    return Path(os.getenv('CLIMB_REPLAY_RTMW_MODEL_DIR') or MODEL_DIRECTORY)


def model_status(directory: Path | None = None) -> dict:
    directory = directory or model_directory()
    return {'name': MODEL, 'execution': 'local', 'requires_credentials': False,
            'available': all((directory / name).is_file()
                             for name in ('rtmw.onnx', 'detector.onnx', 'manifest.json'))}


class LocalRTMWReplayAnalyzer(ReplayAnalyzerBase):
    pose_model = MODEL
    pose_processing_notice = '岩点与 RTMW-L 骨架均在运行程序的本机分析；抽样画面不发送至阿里云。'

    def __init__(self, *, pose_fps: float | None = None, directory: Path | None = None,
                 device: str | None = None, context_retry: bool = True):
        try:
            self.pose_fps = max(1., min(20., float(pose_fps if pose_fps is not None
                                                 else os.getenv('CLIMB_REPLAY_POSE_FPS', '10'))))
        except (ValueError, TypeError):
            self.pose_fps = 10.
        self._default_fps = self.pose_fps
        self.focus_windows = []
        self.stage_timings = {'person': 0., 'skeleton': 0., 'candidate_pose':0., 'context_pose':0.}
        self.inference_counts = dict(detector=0,pose_primary=0,pose_candidates=0,pose_context=0)
        self.directory = directory or model_directory()
        self.device = device or os.getenv('CLIMB_REPLAY_RTMW_DEVICE', 'auto')
        self._models = None
        self._load_lock = threading.Lock()
        self._previous_box = None
        self._previous_appearance = None
        self._previous_source_frame = None
        self._pending_box = None
        self._pending_source_frame = None
        self._source_fps = 30.
        self._current_source_frame = 0
        self._current_frame = None
        self._active_frame_cache = None
        self._route_bounds = None
        self._reference_transform_supplied = False
        self._frame_route_bounds = None
        self._pose_cache = {}
        self._cache_path = None
        self._cache_binding = None
        self._cache_dirty = 0
        self.last_pose_cache_hit = False
        self.last_pose_failure = None
        self.failure_counts = {}
        self.context_retry = context_retry
        self._previous_pose = None
        self._challenger = None
        self.selection_evidence = {}
        self._candidate_body = {}
        self._candidate_check_frame = None

    def configure_cache(self, path, binding):
        # Selected identities depend on preceding observations. Cache raw detector
        # and per-box pose outputs, then select again even when adding dense frames.
        binding = {**binding, 'person_selection': TRACKING_VERSION, 'cache_schema': 3,
                   'detector_postprocess': 'configured-score-threshold-v2'}
        self._cache_path, self._cache_binding = Path(path), binding
        self._pose_cache, self._cache_dirty = {}, 0
        try:
            saved = json.loads(self._cache_path.read_text('utf-8'))
            if saved.get('binding') == binding:
                self._pose_cache = saved['frames']
        except (OSError, ValueError, KeyError):
            pass

    def flush_pose_cache(self):
        if self._cache_path and self._cache_dirty:
            from .climb_replay import _atomic_json
            _atomic_json(self._cache_path, {'binding':self._cache_binding, 'frames':self._pose_cache})
            self._cache_dirty = 0

    def _load_models(self):
        with self._load_lock:
            if self._models is not None:
                return self._models
            try:
                manifest = json.loads((self.directory / 'manifest.json').read_text('utf-8'))
                expected = json.loads((MODEL_DIRECTORY / 'manifest.json').read_text('utf-8'))
                if manifest != expected or manifest['model'] != MODEL:
                    raise ValueError('model manifest mismatch')
                for item in expected['files']:
                    path = self.directory / item['file']
                    if path.stat().st_size != item['bytes']:
                        raise ValueError('model size mismatch')
                    with path.open('rb') as stream:
                        if hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
                            raise ValueError('model checksum mismatch')
                from vendor.rtmlib import RTMPose, YOLOX
                pose = RTMPose(str(self.directory / 'rtmw.onnx'),
                               model_input_size=(288, 384), device=self.device)
                detector = YOLOX(str(self.directory / 'detector.onnx'),
                                 # Keep the former effective native-NMS cutoff;
                                 # scored clip recovery requests its own lower floor.
                                 model_input_size=(640, 640), score_thr=.3, device=self.device)
                self._models = pose, detector
            except Exception as exc:
                raise ReplayConfigurationError(
                    'RTMW 本地模型或运行依赖不可用。请运行 install-replay-rtmw-local.ps1 安装并校验；'
                    '已有复盘可继续查看。') from exc
            return self._models

    def _prepare_pose_run(self, confirmed_holds: dict) -> None:
        from core.replay_model_cache import release_local_model
        release_local_model()
        self._previous_box = None
        self._previous_appearance = None
        self._previous_source_frame = None
        self._previous_pose = None
        self._pending_box = None
        self._pending_source_frame = None
        self._reference_transform_supplied = False
        self._challenger = None
        self._candidate_check_frame = None
        self._frame_route_bounds = None
        self.stage_timings = {'person': 0., 'skeleton': 0., 'candidate_pose':0., 'context_pose':0.}
        self.inference_counts = dict(detector=0,pose_primary=0,pose_candidates=0,pose_context=0)
        self.failure_counts = {}
        boxes = [hold['bbox'] for hold in confirmed_holds.get('holds', [])
                 if hold.get('bbox') and hold.get('route_candidate') is not False]
        self._route_bounds = ([min(b[0] for b in boxes), min(b[1] for b in boxes),
                               max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)]
                              if boxes else None)
        self._load_models()

    def set_person_reference_transform(self, matrix, reference_size, frame_size):
        self._reference_transform_supplied = True
        self._frame_route_bounds = route_in_frame(self._route_bounds, matrix, reference_size, frame_size)

    def configure_sampling(self, options=None):
        options = options or {}
        self.pose_fps = options.get('pose_fps') or self._default_fps
        self.focus_windows = options.get('focus_windows') or []

    def _sampling_positions(self, video_info):
        from .replay_sampling import native_plan
        self._source_fps = video_info.fps
        fps, positions, self.sampling_plan = native_plan(video_info, self.pose_fps, self.focus_windows)
        return fps, positions

    def runtime_metadata(self) -> dict:
        if self._models is None:
            return {'requested_device': self.device, 'loaded': False}
        pose, detector = self._models
        return {'requested_device': self.device, 'loaded': True,
                'onnxruntime': pose.ort.__version__,
                'pose_providers': pose.session.get_providers(),
                'detector_providers': detector.session.get_providers(),
                'pose_fallback': pose.fallback_reason, 'detector_fallback': detector.fallback_reason,
                'missing_pose_reasons': dict(self.failure_counts),
                'person_selection': TRACKING_VERSION,
                'inference_counts':dict(self.inference_counts),
                'timings_ms': {key: round(value * 1000) for key, value in self.stage_timings.items()}}

    def analysis_contract(self, video_info: VideoInfo) -> dict:
        fps, positions = self._sampling_positions(video_info)
        return {
            'contract_version': 2, 'pipeline_version': REPLAY_PIPELINE_VERSION,
            'provider': {'name': 'local-rtmw', 'service': 'RTMW-L 384×288', 'region': 'local',
                         'execution': 'local', 'uploads_frames': False},
            'models': {'holds': {'name': self.hold_model, 'version': 'pending'},
                       'pose': {'name': MODEL, 'version': '20231122', 'keypoints': 133,
                                'input_size_wh': [288, 384], 'body_contract': 'coco17'},
                       'person': {'name': 'yolox-s-humanart', 'input_size_wh': [640, 640]}},
            'algorithms': {'hold_color': REPLAY_COLOUR_VERSION,
                           'contact': 'mask-contour-dwell-0.4s-v2',
                           'person_selection': TRACKING_VERSION},
            'sampling': {'source_fps': round(video_info.fps, 6), 'requested_fps': self.pose_fps,
                         'effective_fps': round(fps, 6), **self.sampling_plan},
            # planned_requests retained as a historical display alias for sample count.
            'usage': {'planned_frames': len(positions), 'planned_requests': len(positions),
                      'actual_requests': 0, 'successful_requests': 0, 'failed_requests': 0,
                      'request_image_bytes': 0, 'local_inferences': 0,
                      'successful_local_inferences': 0, 'failed_local_inferences': 0,
                      'successful_pose_frames': 0, 'responses_without_pose': 0,
                      'decode_failed_frames': 0, 'unprocessed_frames': len(positions)},
            'cost': {'currency': 'CNY', 'unit_price': 0, 'billable_requests_estimate': 0,
                     'estimated_amount': 0., 'basis': '本地 RTMW 骨架分析，无付费姿态 API 调用。'},
            'timings_ms': {key: 0 for key in ('total', 'background', 'hold_inference', 'pose',
                                             'contact', 'overlay', 'report')},
            'runtime': self.runtime_metadata(),
        }

    @staticmethod
    def _box_iou(a, b):
        intersection = max(0., min(a[2], b[2]) - max(a[0], b[0])) * max(
            0., min(a[3], b[3]) - max(a[1], b[1]))
        area = lambda box: max(0., box[2] - box[0]) * max(0., box[3] - box[1])
        return intersection / max(1e-9, area(a) + area(b) - intersection)

    def _select_box(self, boxes, width, height):
        bounds = self._frame_route_bounds if self._reference_transform_supplied else self._route_bounds
        valid = []
        for box in np.asarray(boxes).reshape(-1, 4):
            if not np.isfinite(box).all():
                continue
            box = np.clip(box, [0, 0, 0, 0], [width, height, width, height]).astype(float)
            if box[2] - box[0] > 4 and box[3] - box[1] > 4:
                valid.append(box)
        if not valid:
            self._pending_box = None
            self._challenger = None
            return None, 'person_not_detected'
        if self._previous_box is not None:
            ranked = sorted(((self._box_iou(self._previous_box, b), b) for b in valid),
                            key=lambda item: item[0], reverse=True)
            dt = ((self._current_source_frame - self._previous_source_frame) / self._source_fps
                  if self._previous_source_frame is not None else 0.)
            current_appearance = lambda b: appearance(self._current_frame, b) if self._current_frame is not None else None
            # A confirmed route conflict must persist across real observations.
            # A brief swing outside the route retains the tracked identity.
            rivals = [b for b in valid if bounds is not None and near_route(b, bounds, width, height)
                      and self._box_iou(b, ranked[0][1]) < .1]
            conflict = (bounds is not None and not near_route(ranked[0][1], bounds, width, height)
                        and len(rivals) == 1)
            if bounds is None and self._candidate_body:
                def prominence(b):
                    body = self._candidate_body.get(tuple(b), {})
                    return (b[2]-b[0])*(b[3]-b[1])/(width*height) + body.get('climbing_support',0)
                challengers = [b for b in valid if self._box_iou(b,ranked[0][1]) < .1
                               and self._candidate_body.get(tuple(b),{}).get('raised_foot',False)
                               and (b[2]-b[0])*(b[3]-b[1]) > 1.8*(ranked[0][1][2]-ranked[0][1][0])*(ranked[0][1][3]-ranked[0][1][1])
                               and prominence(b) > prominence(ranked[0][1])+.12]
                if len(challengers)==1:
                    rivals, conflict = challengers, True
            if conflict:
                rival = rivals[0]
                old = self._challenger
                consecutive = (old is not None and 0 < (self._current_source_frame-old['frame']) / self._source_fps <= .65
                               and self._box_iou(old['box'], rival) >= .3)
                count = old['count'] + 1 if consecutive else 1
                self._challenger = {'box':rival.copy(), 'frame':self._current_source_frame, 'count':count}
                self.selection_evidence = {'basis':'persistent_route_identity_conflict' if bounds is not None else 'persistent_prominent_climbing_candidate', 'observations':count,
                                           'old_box':ranked[0][1].tolist(), 'candidate_box':rival.tolist()}
                if count >= 3:
                    return rival, 'route_conflict_reselected'
            elif bounds is not None or self._candidate_body:
                self._challenger = None
            if (ranked[0][0] >= .1 and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= .05)
                    and dt <= MAX_RECOVERY_SECONDS
                    and (self._previous_appearance is None or appearance_distance(
                        self._previous_appearance, current_appearance(ranked[0][1])) <= .65)):
                self._pending_box = None
                return ranked[0][1], 'iou_follow'
            # A short detector gap / abrupt box change may recover only with
            # matching appearance, bounded movement and two real observations.
            candidates = [b for b in valid if 0 < dt <= MAX_RECOVERY_SECONDS
                          and (self._route_bounds is None or bounds is not None)
                          and near_route(b, bounds, width, height)
                          and recovery_geometry(self._previous_box, b)
                          and appearance_distance(self._previous_appearance, current_appearance(b)) <= .3]
            if len(candidates) == 1:
                box = candidates[0]
                pending_dt = ((self._current_source_frame - self._pending_source_frame) / self._source_fps
                              if self._pending_source_frame is not None else 0.)
                if (self._pending_box is not None and 0 < pending_dt <= .35
                        and self._box_iou(self._pending_box, box) >= .3):
                    self._pending_box = None
                    return box, 'appearance_reacquired'
                self._pending_box, self._pending_source_frame = box.copy(), self._current_source_frame
                return None, 'track_recovery_pending'
            self._pending_box = None
            return None, 'track_missing_or_ambiguous'
        if self._route_bounds is not None and self._reference_transform_supplied and bounds is None:
            return None, 'route_reference_unavailable'
        valid = [b for b in valid if near_route(b, bounds, width, height)]
        if not valid:
            return None, 'person_outside_confirmed_route'
        def initial_score(box):
            area = (box[2] - box[0]) * (box[3] - box[1]) / (width * height)
            body = self._candidate_body.get(tuple(box), {})
            process = body.get('climbing_support', 0.)
            if bounds is None:
                return area + process
            center = (box[:2] + box[2:]) / 2 / [width, height]
            left, top, right, bottom = bounds
            dx = max(left - center[0], 0, center[0] - right)
            dy = max(top - center[1], 0, center[1] - bottom)
            return area - 2 * (dx * dx + dy * dy) + process
        ranked = sorted(valid, key=initial_score, reverse=True)
        if len(ranked) > 1 and initial_score(ranked[0]) - initial_score(ranked[1]) < .025:
            return None, 'initial_person_ambiguous'
        if len(ranked) > 1:
            box = ranked[0]
            pending_dt = ((self._current_source_frame - self._pending_source_frame) / self._source_fps
                          if self._pending_source_frame is not None else 0.)
            if not (self._pending_box is not None and 0 < pending_dt <= .35
                    and self._box_iou(self._pending_box, box) >= .3):
                self._pending_box, self._pending_source_frame = box.copy(), self._current_source_frame
                return None, 'initial_person_pending'
            self._pending_box = None
        return ranked[0], 'route_initial_selection'

    def _pose_frame(self, frame, *, frame_id, source_frame_id, before_request=None):
        key = str(source_frame_id)
        self._current_frame, self._current_source_frame = frame, source_frame_id
        self._active_frame_cache = self._pose_cache.get(key, {})
        self.last_pose_cache_hit = 'boxes' in self._active_frame_cache
        self.last_pose_failure = None
        self.selection_evidence = {}
        record = self._infer_pose_frame(frame, frame_id=frame_id, source_frame_id=source_frame_id)
        if self.last_pose_failure:
            self.failure_counts[self.last_pose_failure] = self.failure_counts.get(self.last_pose_failure, 0) + 1
        if self._cache_path:
            self._pose_cache[key] = self._active_frame_cache
            self._cache_dirty += 1
            if self._cache_dirty >= 20:
                self.flush_pose_cache()
        return record

    def _infer_pose_frame(self, frame, *, frame_id, source_frame_id):
        pose, detector = self._load_models()
        height, width = frame.shape[:2]
        started = time.perf_counter()
        cached = self._active_frame_cache
        boxes = cached.get('boxes')
        if boxes is None:
            boxes = np.asarray(detector(frame)).reshape(-1, 4).tolist()
            cached['boxes'] = boxes
            self.inference_counts['detector'] += 1
        self.stage_timings['person'] += time.perf_counter()-started
        candidate_started = time.perf_counter()
        self._candidate_body = {}
        # At most three same-frame bodies for an uncertain initial identity.
        # These posture cues rank candidates; they do not verify a grip/contact.
        check_dt = ((source_frame_id-self._candidate_check_frame)/self._source_fps
                    if self._candidate_check_frame is not None else 1.)
        candidate_check = len(boxes)>1 and (self._previous_box is None or check_dt >= .5)
        if candidate_check:
            self._candidate_check_frame = source_frame_id
            candidates = sorted((np.asarray(b, float) for b in boxes if np.isfinite(b).all()),
                                key=lambda b: max(0,b[2]-b[0])*max(0,b[3]-b[1]), reverse=True)[:3]
            poses = cached.setdefault('poses', {})
            for candidate in candidates:
                candidate = np.clip(candidate, [0,0,0,0], [width,height,width,height])
                candidate_key = json.dumps(candidate.round(6).tolist())
                if candidate_key not in poses:
                    candidate_xy, candidate_scores = pose(frame, [candidate.tolist()])
                    self.inference_counts['pose_candidates'] += 1
                    poses[candidate_key] = [np.where(np.isfinite(a), a, None).tolist()
                                            for a in (np.asarray(candidate_xy), np.asarray(candidate_scores))]
                    self.last_pose_cache_hit = False
                points, responses = (np.asarray(a[0],float) for a in poses[candidate_key])
                if points.shape != (133,2) or responses.shape != (133,):
                    continue
                torso = points[[5,6,11,12]]
                visible = np.isfinite(torso).all() and np.all(responses[[5,6,11,12]] >= .5)
                torso_length = np.linalg.norm(torso[:2].mean(axis=0)-torso[2:].mean(axis=0))
                support = 0.
                raised_foot = False
                if visible and torso_length > 8:
                    for shoulder, elbow, wrist in ((5,7,9),(6,8,10)):
                        chain = points[[shoulder,elbow,wrist]]
                        if np.isfinite(chain).all() and np.all(responses[[shoulder,elbow,wrist]] >= .5):
                            if points[wrist,1] < points[shoulder,1] - .15*torso_length:
                                support += .18
                    for hip,knee,ankle in ((11,13,15),(12,14,16)):
                        if np.isfinite(points[[hip,knee,ankle]]).all() and np.all(responses[[hip,knee,ankle]]>=.5):
                            if points[ankle,1]-points[hip,1] < .65*torso_length:
                                support += .18
                                raised_foot = True
                self._candidate_body[tuple(candidate)] = {'torso_visible':bool(visible), 'climbing_support':support,'raised_foot':raised_foot}
            self.selection_evidence = {'basis':'same_frame_body_and_consecutive_candidate',
                'candidates':[{'box':list(key), **value} for key,value in self._candidate_body.items()]}
        self.stage_timings['candidate_pose'] += time.perf_counter()-candidate_started
        started = time.perf_counter()
        box, selection = self._select_box(boxes, width, height)
        self.stage_timings['person'] += time.perf_counter() - started
        if box is None:
            self.last_pose_failure = selection
            return None
        xy, raw_scores, initial_observation, revision = self._observe_pose_in_box(
            frame, box, source_frame_id=source_frame_id)
        finite = np.isfinite(xy).all(axis=1) & np.isfinite(raw_scores)
        inside = ((xy[:, 0] >= 0) & (xy[:, 0] < width)
                  & (xy[:, 1] >= 0) & (xy[:, 1] < height))
        scores = np.where(finite & inside, np.clip(raw_scores, 0, 1), 0.)
        coords = np.where(np.isfinite(xy), xy, 0.) / [width, height]
        if np.count_nonzero(scores[5:17] >= .15) < 6:
            self.last_pose_failure = 'insufficient_body_joints'
            return None
        if selection == 'route_conflict_reselected' and not np.all(scores[[5,6,11,12]] >= .5):
            self.last_pose_failure = 'reselected_body_incomplete'
            return None
        # An entering hand / cropped body must not establish an identity that
        # subsequent full-person detections can never recover. Wait for visible
        # shoulders and hips before committing an initial track at the edge.
        edge_partial = (box[3] >= height * .98 or box[1] <= height * .02) and box[3] - box[1] < height * .3
        if self._previous_box is None and edge_partial and not np.all(scores[[5, 6, 11, 12]] >= .2):
            self.last_pose_failure = 'initial_body_incomplete'
            return None
        self._previous_box = box.copy()
        self._previous_source_frame = source_frame_id
        self._previous_appearance = appearance(frame, box)
        points, confidence = coords.round(6).tolist(), scores.round(6).tolist()
        self._previous_pose={'source_frame_id':source_frame_id,'kpts_xy':points[:17],'kpts_score':confidence[:17],
                             'box_xyxy_px':box.tolist()}
        return {
            'frame_id': frame_id, 'source_frame_id': source_frame_id, 'track_id': 0,
            'kpts_xy': points[:17], 'kpts_score': confidence[:17],
            **({'initial_wholebody_observation':initial_observation,'pose_revision':revision} if revision else {}),
            'bbox_xywh': [round(float(box[0] / width), 6), round(float(box[1] / height), 6),
                          round(float((box[2] - box[0]) / width), 6),
                          round(float((box[3] - box[1]) / height), 6)],
            'wholebody': {'schema': 'coco-wholebody-133', 'coordinates': 'source_image_normalized',
                          'kpts_xy': points, 'kpts_score': confidence,
                          'raw_xy_px': [[float(value) if np.isfinite(value) else None for value in point]
                                        for point in xy],
                          'location_support': ['same_frame_context_consensus' if revision
                              and revision.get('status')=='accepted_experimental' and i in (5,6,9,10,11,12,15,16)
                              else 'finite_score_only_not_verified_position' for i in range(133)],
                          'joint_status': ['nonfinite' if not finite[i] else 'outside_image' if not inside[i]
                                           else 'response_saturated' if raw_scores[i]>1
                                           else 'score_eligible' if scores[i]>=.5 else 'weak_score'
                                           for i in range(133)],
                          'raw_scores': np.nan_to_num(raw_scores, nan=0., posinf=0., neginf=0.).tolist()},
            'pose_evidence': {'provider': 'local-rtmw', 'model': MODEL,
                              'source_size_wh': [width,height], 'model_input_size_wh': [288,384],
                              'person_box_xyxy_px': box.tolist(),
                              'observation_kind': 'model_observation',
                              'joint_status_basis': 'finite_in_frame_and_score_not_verified_position',
                              'score_transform': 'legacy_clip_0_1_not_calibrated_probability',
                              'selection': selection, 'person_selection_version': TRACKING_VERSION,
                              'selection_evidence': self.selection_evidence,
                              'tracking': 'heuristic_not_identity_verified'},
        }

    def _observe_pose_in_box(self, frame, box, *, source_frame_id):
        """Observe an explicitly selected source box, without person selection.

        The existing context provider remains until an independent replacement
        passes anatomical quality review. It never changes target identity.
        """
        pose, _ = self._load_models()
        height, width = frame.shape[:2]
        cached = self._active_frame_cache
        started = time.perf_counter()
        pose_key = json.dumps(box.round(6).tolist())
        poses = cached.setdefault('poses', {})
        if pose_key in poses:
            xy, raw_scores = poses[pose_key]
        else:
            self.last_pose_cache_hit = False
            xy, raw_scores = pose(frame, [box.tolist()])
            self.inference_counts['pose_primary'] += 1
            # Keep raw evidence only; do not cache a sequential tracking decision.
            poses[pose_key] = [np.where(np.isfinite(a), a, None).tolist()
                               for a in (np.asarray(xy), np.asarray(raw_scores))]
        self.stage_timings['skeleton'] += time.perf_counter() - started
        xy, raw_scores = np.asarray(xy[0], dtype=float), np.asarray(raw_scores[0], dtype=float)
        if xy.shape != (133, 2) or raw_scores.shape != (133,):
            raise RuntimeError('RTMW 模型输出格式与已核验版本不一致')
        initial_observation = None
        revision = None
        if self.context_retry and self._previous_pose:
            context_started = time.perf_counter()
            from core.replay_pose_context import context_proposal, expanded_box_proposal, consensus_retry, VERSION
            dt=(source_frame_id-self._previous_pose['source_frame_id'])/self._source_fps
            proposal=context_proposal(self._previous_pose,xy[:17]/[width,height],np.clip(raw_scores[:17],0,1),[width,height],dt)
            if proposal is None:
                proposal=expanded_box_proposal(self._previous_pose,xy[:17]/[width,height],np.clip(raw_scores[:17],0,1),[width,height],dt,box)
            if proposal is not None:
                retry_box=proposal['box']
                # A second crop adds current torso context and a distinct margin.
                torso = xy[[5,6,11,12]]
                pad = proposal['scale']*.12
                second_box = np.r_[np.maximum(np.minimum(retry_box[:2],torso.min(axis=0))-pad,0),
                                   np.minimum(np.maximum(retry_box[2:],torso.max(axis=0))+pad,[width,height])]
                observations = []
                for candidate_box in (retry_box, second_box):
                    candidate_key = json.dumps(candidate_box.round(6).tolist())
                    if candidate_key not in poses:
                        candidate_xy,candidate_score=pose(frame,[candidate_box.tolist()])
                        self.inference_counts['pose_context'] += 1
                        poses[candidate_key]=[np.where(np.isfinite(a),a,None).tolist() for a in
                                              (np.asarray(candidate_xy),np.asarray(candidate_score))]
                        self.last_pose_cache_hit=False
                    observations.append(tuple(np.asarray(a[0],float) for a in poses[candidate_key]))
                retry_xy,retry_score=observations[0]
                supported = all(a.shape==(133,2) and b.shape==(133,) for a,b in observations) and consensus_retry(
                    proposal,[(a[:17]/[width,height],np.clip(b[:17],0,1)) for a,b in observations],
                    xy[:17]/[width,height],[width,height])
                revision={'version':VERSION,'basis':'two_same_frame_contexts_and_body_chain',
                          'previous_source_frame':self._previous_pose['source_frame_id'],
                          'candidate_boxes':[retry_box.tolist(),second_box.tolist()],
                          'candidates':[{'raw_xy_px':np.where(np.isfinite(a),a,0).tolist(),
                                         'raw_scores':np.nan_to_num(b,nan=0,posinf=0,neginf=0).tolist()} for a,b in observations],
                          'suspect_joints':proposal['suspect_joints'],
                          'status':'accepted_experimental' if supported else 'rejected_no_consensus'}
                if supported:
                    initial_observation={'kpts_xy':np.where(np.isfinite(xy),xy/[width,height],0.).tolist(),
                                         'raw_xy_px':[[float(v) if np.isfinite(v) else None for v in point] for point in xy],
                                         'raw_scores':np.nan_to_num(raw_scores,nan=0.,posinf=0.,neginf=0.).tolist(),
                                         'box_xyxy_px':box.tolist(),'coordinates':'source_image_normalized'}
                    xy,raw_scores=retry_xy,retry_score
            self.stage_timings['context_pose'] += time.perf_counter()-context_started
        return xy, raw_scores, initial_observation, revision
