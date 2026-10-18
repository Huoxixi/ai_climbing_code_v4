"""Offline replay: all-person association -> clip target -> source observations.

The default replaces legacy single-person selection. RTMW observation and its
existing bounded context provider stay until a separate model passes quality
review. Explicit local model paths are isolated heatmap comparisons only.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np

from .climb_replay import ReplayCancelled, ReplayConfigurationError
from .replay_person_tracks import (ClipPersonTracks, consolidate_bodies, VERSION as TRACK_VERSION,
                                  DETECTION_VERSION, PERSON_HIGH_SCORE, PERSON_LOW_SCORE)
from .replay_person_tracking import appearance, route_in_frame
from .replay_pose_rtmw import LocalRTMWReplayAnalyzer, MODEL as RTMW_MODEL
from .replay_pose_heatmap import HeatmapPose
from .replay_pose_observation import observation_record, VERSION as OBSERVATION_VERSION
from .replay_hold_fusion import align_to_reference
from .replay_observation_validity import registration_reason

MODEL = 'vitpose-small-wholebody-e8380527'
MODEL_DIRECTORY = Path(__file__).resolve().parents[1]/'model_assets/vitpose-small-wholebody'
MODEL_SHA256 = 'ccac893a8ad6da7d43f9655047acf48e482e66922db7f4273a3b615cea989127'


class LocalClipReplayAnalyzer(LocalRTMWReplayAnalyzer):
    pose_model = RTMW_MODEL
    pose_processing_notice = '岩点、人物轨迹与骨架均在本机分析，原视频不上传。'

    def __init__(self, *, observation_model=None, **kwargs):
        self._heatmap_comparison = observation_model is not None
        kwargs.setdefault('context_retry', not self._heatmap_comparison)
        super().__init__(**kwargs)
        self.observation_model = Path(observation_model) if observation_model else None
        self.pose_model = MODEL if self._heatmap_comparison else RTMW_MODEL
        self._observation_provider = None
        self._clip_tracks = None
        self._clip_alignments = {}

    def _load_observation_provider(self):
        if self._observation_provider is None:
            try:
                with self.observation_model.open('rb') as stream:
                    if hashlib.file_digest(stream,'sha256').hexdigest()!=MODEL_SHA256:
                        raise ValueError('Observation model checksum mismatch')
                self._observation_provider = HeatmapPose(str(self.observation_model),device=self.device)
            except Exception as exc:
                raise ReplayConfigurationError('本地骨架模型缺失或校验失败，请修复程序资源；已有复盘可继续查看。') from exc
        return self._observation_provider

    def configure_cache(self, path, binding):
        # Raw observations do not depend on target selection. Pose keys carry the
        # exact model/decoder version and box; clip decisions are never persisted
        # as raw cache entries. Keep source/sampling binding from the caller.
        super().configure_cache(path,{**binding,'clip_observation_schema':OBSERVATION_VERSION,
                                     'person_tracks':TRACK_VERSION,
                                     'person_detection':DETECTION_VERSION,
                                     'observation_model':MODEL_SHA256 if self._heatmap_comparison else RTMW_MODEL,
                                     'context_retry':self.context_retry})

    def _prepare_pose_run(self, confirmed_holds):
        super()._prepare_pose_run(confirmed_holds)
        self._clip_tracks = None
        self._clip_alignments = {}
        if self._heatmap_comparison:
            self._load_observation_provider()

    def _raw_frame(self, frame, source):
        key = str(source)
        entry = self._pose_cache.setdefault(key,{})
        if 'boxes' not in entry:
            started=time.perf_counter()
            detector = self._load_models()[1]
            # Inspect the type, not a dynamic Mock/provider attribute. Legacy
            # box-only providers retain their established path.
            if callable(getattr(type(detector), 'detect_with_scores', None)):
                boxes, scores = detector.detect_with_scores(frame, score_thr=PERSON_LOW_SCORE)
                entry['boxes'] = np.asarray(boxes).reshape(-1,4).tolist()
                entry['detector_scores'] = np.asarray(scores).tolist()
            else:
                entry['boxes'] = np.asarray(detector(frame)).reshape(-1,4).tolist()
            self.stage_timings['person'] += time.perf_counter()-started
            self.inference_counts['detector'] += 1
            self._cache_dirty += 1
        return entry

    def _observe_people(self, frame, source, *, inspect_body):
        entry = self._raw_frame(frame,source)
        h,w=frame.shape[:2]
        boxes=np.asarray(entry['boxes']).reshape(-1,4)
        observations=[]
        scores = entry.get('detector_scores', [1.]*len(boxes))
        for original, score in zip(boxes, scores, strict=True):
            if not np.isfinite(original).all():
                continue
            box=np.clip(original,[0,0,0,0],[w,h,w,h])
            if min(box[2:]-box[:2])<=4:
                continue
            body=None
            if inspect_body or len(boxes)>1:
                pose_key=json.dumps(box.round(6).tolist())
                poses=entry.setdefault('poses',{})
                if pose_key not in poses:
                    started=time.perf_counter()
                    xy,raw=self._load_models()[0](frame,[box.tolist()])
                    poses[pose_key]=[np.where(np.isfinite(v),v,None).tolist() for v in (xy,raw)]
                    self.stage_timings['candidate_pose'] += time.perf_counter()-started
                    self.inference_counts['pose_candidates'] += 1
                    self._cache_dirty += 1
                xy,raw=(np.asarray(v[0],float) for v in poses[pose_key])
                finite=np.isfinite(xy[:17]).all(axis=1)&np.isfinite(raw[:17])&(raw[:17]>0)
                finite &= (xy[:17]>0).all(axis=1)&(xy[:17]<[w,h]).all(axis=1)
                body={'response_availability':float(np.mean(finite[5:17])),
                      'visibility_semantics':'finite_positive_body_response_not_occlusion_truth',
                      'torso_xy':(xy[[5,6,11,12]]/[w,h]).tolist() if np.all(finite[[5,6,11,12]]) else None,
                      'torso_center':(xy[[5,6,11,12]].mean(axis=0)/[w,h]).tolist() if np.all(finite[[5,6,11,12]]) else None}
                body['body_xy']=np.where(finite[5:17,None],xy[5:17]/[w,h],np.nan).tolist()
                body['body_xy']=[[float(v) if np.isfinite(v) else None for v in point] for point in body['body_xy']]
            hist=appearance(frame,box)
            normalized=(box/[w,h,w,h]).tolist()
            association_box=normalized
            association_space='source'
            alignment=self._clip_alignments.get(int(source))
            route_affinity=None
            if alignment is not None and registration_reason(*alignment) is None:
                matrix=alignment[0]
                corners=np.array([[box[0],box[1]],[box[2],box[1]],[box[2],box[3]],[box[0],box[3]]])
                projected=np.c_[corners,np.ones(4)]@matrix.T
                if np.isfinite(projected).all() and np.all(np.abs(projected[:,2])>1e-8):
                    mapped=projected[:,:2]/projected[:,2:]/[w,h]
                    association_box=np.r_[mapped.min(axis=0),mapped.max(axis=0)].tolist()
                    association_space='reference'
                bounds=route_in_frame(self._route_bounds,matrix,[w,h],[w,h])
                if bounds is not None:
                    low=np.maximum(box[:2]/[w,h],bounds[:2])
                    high=np.minimum(box[2:]/[w,h],bounds[2:])
                    route_affinity=float(np.prod(np.maximum(0,high-low))/max(1e-9,np.prod(box[2:]/[w,h]-box[:2]/[w,h])))
            observations.append({'box':normalized,'box_xyxy_px':box.tolist(),
                'detector_score':float(score),
                'association_box':association_box,'association_space':association_space,
                'appearance':hist.flatten().tolist() if hist is not None else None,
                'body':body,'route_affinity':route_affinity})
        # A weak duplicate must not displace an existing high-score body context.
        high = consolidate_bodies([r for r in observations if r['detector_score'] > PERSON_HIGH_SCORE])
        low = consolidate_bodies([r for r in observations if r['detector_score'] <= PERSON_HIGH_SCORE])
        return high + low

    def _prepare_clip_observations(self, video, video_info, positions, reference, *, progress, cancelled):
        self._source_fps=video_info.fps
        self._clip_tracks=ClipPersonTracks(low_score_recovery=True)
        cap=cv2.VideoCapture(str(video))
        started=time.perf_counter()
        try:
            for index,source in enumerate(positions):
                if cancelled():
                    raise ReplayCancelled()
                source=int(source)
                cap.set(cv2.CAP_PROP_POS_FRAMES,source)
                ok,frame=cap.read()
                if not ok:
                    self._clip_tracks.add_frame(source,source/video_info.fps,[])
                    continue
                # Registration is reused by the shared analysis pass. Pure
                # skeleton clips also need camera compensation for association.
                self._clip_alignments[source]=align_to_reference(frame,reference)
                observations=self._observe_people(frame,source,inspect_body=index%max(1,round(self.pose_fps/2))==0)
                self._clip_tracks.add_frame(source,source/video_info.fps,observations)
                progress('识别整段视频中的人物',45+round(10*(index+1)/len(positions)))
                if self._cache_dirty>=20:
                    self.flush_pose_cache()
            selection=self._clip_tracks.select_target()
            if selection['status']=='ambiguous':
                raise RuntimeError('视频中有多位同样显著的人物，暂时无法确定本次攀爬目标。请使用目标清楚的片段。')
        finally:
            cap.release()
            self.stage_timings['clip_identity']=time.perf_counter()-started
            self.flush_pose_cache()

    def _person_alignment(self, source):
        return self._clip_alignments.get(int(source))

    def _pose_frame(self, frame, *, frame_id, source_frame_id, before_request=None):
        if self._clip_tracks is None:
            raise RuntimeError('Complete clip identity analysis before pose inference')
        self.last_pose_failure=None
        observation=self._clip_tracks.target_observation(source_frame_id)
        self._active_frame_cache=self._pose_cache.get(str(source_frame_id),{})
        if observation is None:
            self.last_pose_failure='target_not_observed_in_source_frame'
            self.last_pose_cache_hit=True
            self.failure_counts[self.last_pose_failure]=self.failure_counts.get(self.last_pose_failure,0)+1
            return None
        box=np.asarray(observation['box_xyxy_px'])
        if not self._heatmap_comparison:
            # Selection is already final. No previous-box lock, posture ranking,
            # challenger, edge-identity rejection or target switch runs here.
            self.last_pose_cache_hit=json.dumps(box.round(6).tolist()) in self._active_frame_cache.get('poses',{})
            xy,raw,initial,revision=self._observe_pose_in_box(frame,box,source_frame_id=source_frame_id)
            record=observation_record(xy,raw,frame_id=frame_id,source_frame_id=source_frame_id,
                track_id=observation['track_id'],size=[frame.shape[1],frame.shape[0]],box=box.tolist(),
                model=RTMW_MODEL,model_evidence={'input_size_wh':[288,384],
                    'response_semantics':'simcc_native_response_uncalibrated',
                    'context_provider':'existing_bounded_same_frame_context_not_independent_truth',
                    'context_revision':revision},selection=self._clip_tracks.selection,
                minimum_response=.5)
            record['pose_evidence']['person_detection'] = {
                'version':DETECTION_VERSION,'native_score':observation.get('detector_score'),
                'recovery':observation.get('detection_recovery'),
                'score_semantics':'detector_response_not_joint_correctness'}
            if revision:
                record.update(initial_wholebody_observation=initial,pose_revision=revision)
            self._previous_pose={'source_frame_id':source_frame_id,'kpts_xy':record['kpts_xy'],
                'kpts_score':np.where(record['joint_eligibility'],np.clip(raw[:17],0,1),0).tolist(),
                'box_xyxy_px':box.tolist()}
            self._cache_dirty+=1
            if self._cache_dirty>=20:self.flush_pose_cache()
            return record
        key=MODEL_SHA256+':'+OBSERVATION_VERSION+':'+json.dumps(box.round(6).tolist())
        poses=self._active_frame_cache.setdefault('observations',{})
        self.last_pose_cache_hit=key in poses
        if not self.last_pose_cache_hit:
            started=time.perf_counter()
            provider=self._load_observation_provider()
            xy,raw=provider(frame,[box.tolist()])
            poses[key]={'xy':np.where(np.isfinite(xy[0]),xy[0],None).tolist(),
                        'raw':np.where(np.isfinite(raw[0]),raw[0],None).tolist(),
                        'model_evidence':deepcopy(provider.last_evidence)}
            self.stage_timings['skeleton'] += time.perf_counter()-started
            self.inference_counts['pose_primary'] += 1
            self._cache_dirty += 1
        value=poses[key]
        record=observation_record(value['xy'],value['raw'],frame_id=frame_id,source_frame_id=source_frame_id,
            track_id=observation['track_id'],size=[frame.shape[1],frame.shape[0]],box=box.tolist(),
            model=MODEL,model_evidence=value['model_evidence'],selection=self._clip_tracks.selection)
        if self._cache_dirty>=20:
            self.flush_pose_cache()
        return record

    def _choose_track(self, records):
        # Empty frames remain on the same source clock. The base's legacy
        # majority-track filter would otherwise silently remove missing samples.
        return self._clip_tracks.selection['target_track_id'],records

    def runtime_metadata(self):
        result=super().runtime_metadata()
        result['person_selection']=TRACK_VERSION
        result['person_detection']=DETECTION_VERSION
        result['observation_contract']=OBSERVATION_VERSION
        result['target_selection']=self._clip_tracks.selection if self._clip_tracks is not None else None
        result['observation_model']=self.pose_model
        result['independent_hand_observation']='not_accepted'
        if self._observation_provider is not None:
            result['observation_model']=MODEL
            result['observation_providers']=self._observation_provider.session.get_providers()
        return result

    def analysis_contract(self, video_info):
        result=super().analysis_contract(video_info)
        if self._heatmap_comparison:
            result['models']['pose']={'name':MODEL,'version':MODEL_SHA256,'keypoints':133,
                                    'input_size_wh':[192,256],'body_contract':'coco17'}
        result['algorithms']['person_selection']=TRACK_VERSION
        result['algorithms']['person_detection']=DETECTION_VERSION
        result['algorithms']['pose_observation']=OBSERVATION_VERSION
        result['provider']['name']='local-clip-pose'
        result['provider']['service']=self.pose_model+' + clip person tracks'
        return result
