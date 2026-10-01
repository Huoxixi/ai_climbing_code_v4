import copy
import math
import tempfile
import time
import unittest
from pathlib import Path

import cv2
import numpy as np

from core.replay_actions import organize, apply_local_review, motion_intervals, basic_metrics
from core.replay_action_renderer import make_plan, validate, render_actions, summary_seconds, ActionComposition, active_event, metric_text
from core.replay_action_jobs import ActionManager
from core.replay_motion_summary import enrich_motion_summary
from core.replay_route_usage import enrich_route_usage
from core.replay_action_engine import track_conflicts
from test_replay_coaching_lifecycle import ReplayCoachingLifecycleTests


def evidence():
    samples = []
    for i in range(25):
        xy = [[.2 + (i * .009 if i < 12 else .108), .2 + j * .02] for j in range(17)]
        samples.append({"time_seconds": i / 4, "observed": True, "kpts_xy": xy,
                        "kpts_score": [.9] * 17, "wall_alignment": "reference",
                        "wall_reference_transform": np.eye(3).tolist()})
    return {"video": {"width": 96, "height": 64, "fps": 4, "frame_count": 24, "duration_seconds": 6},
            "pose_samples": samples, "holds": [], "attempt": {"contacts": [
                {"limb": "left_hand", "hold_id": 1, "start_time_seconds": 0, "end_time_seconds": 1},
                {"limb": "left_hand", "hold_id": 1, "start_time_seconds": 2, "end_time_seconds": 3}]}}


class ActionEvidenceTests(unittest.TestCase):
    def test_displayed_percentage_preserves_export_unit(self):
        self.assertEqual(metric_text({'value':88.9,'display_value':'88.9','unit':'%'}),'88.9 %')
        self.assertEqual(metric_text({'value':None,'display_value':'尚未确认','unit':''}),'尚未确认')
    def test_route_usage_unions_limbs_and_excludes_unrelated_holds(self):
        source=evidence()
        source['holds']=[{'id':1,'route_candidate':True},{'id':2,'route_candidate':True},{'id':3,'route_candidate':True},{'id':4,'route_candidate':False}]
        source['attempt']['contacts'] += [
            {'limb':'right_foot','hold_id':1,'start_time_seconds':0,'end_time_seconds':1},
            {'limb':'left_hand','hold_id':2,'start_time_seconds':3,'end_time_seconds':4},
            {'limb':'right_hand','hold_id':4,'start_time_seconds':4,'end_time_seconds':5}]
        original=copy.deepcopy(source)
        result=enrich_route_usage(organize({'result':source}),source)
        self.assertEqual(result['route_usage']['total'],3)
        self.assertEqual(result['route_usage']['used'],2)
        self.assertEqual(result['route_usage']['percent'],66.7)
        self.assertEqual([m['key'] for m in result['metrics'][:3]],['route_total','route_used','route_usage'])
        self.assertEqual(source,original)
        self.assertEqual(enrich_route_usage(result,source)['metrics'],result['metrics'])

    def test_route_usage_missing_contacts_and_zero_denominator_stay_unknown(self):
        source=evidence()
        source['holds']=[{'id':1}]
        del source['attempt']['contacts']
        result=enrich_route_usage(organize({'result':source}),source)
        self.assertIsNone(result['route_usage']['used'])
        self.assertIsNone(result['route_usage']['percent'])
        source['holds']=[]
        source['attempt']['contacts']=[]
        result=enrich_route_usage(organize({'result':source}),source)
        self.assertIsNone(result['route_usage']['percent'])

    def test_rhythm_accounts_for_gaps_without_bridging_posture_stops(self):
        raw = {'source_duration_seconds': 6., 'metrics': [], 'motion_intervals': [
            {'start_seconds':0.,'end_seconds':1.5,'kind':'relative_still'},
            {'start_seconds':2.,'end_seconds':3.,'kind':'relative_still'},
            {'start_seconds':3.,'end_seconds':5.5,'kind':'moving'}]}
        original = copy.deepcopy(raw)
        result = enrich_motion_summary(raw)
        self.assertEqual(raw, original)
        motion = result['motion_summary']
        self.assertEqual(motion['longest_still']['value'],1.5)
        self.assertEqual(motion['longest_still']['end_seconds'],1.5)
        self.assertAlmostEqual(sum(r['percent'] for r in motion['totals']),100)
        self.assertEqual(motion['totals'][2]['seconds'],1.)
        self.assertEqual(motion['segments'][-1]['end_seconds'],6.)
        self.assertEqual(result['metrics'][-1]['start_seconds'],0.)

    def test_missing_or_short_pose_evidence_never_produces_a_zero_stop(self):
        for intervals in [[],[{'start_seconds':0.,'end_seconds':.25,'kind':'relative_still'}]]:
            result = enrich_motion_summary({'source_duration_seconds':4.,'metrics':[], 'motion_intervals':intervals})
            self.assertIsNone(result['motion_summary']['longest_still'])
            self.assertIsNone(result['metrics'][-1]['value'])
            self.assertEqual('尚未确认',result['metrics'][-1]['display_value'])

    def test_rhythm_export_uses_source_clock_at_both_speeds(self):
        result = enrich_motion_summary(organize({'result':evidence()}))
        for speed in (1,.75,.5):
            plan=make_plan(result,speed=speed)
            self.assertEqual(plan['motion_summary']['duration_seconds'],6)
            self.assertEqual(plan['summary_seconds'],0)
            self.assertFalse(plan['annotations'])
            self.assertEqual(validate(plan), math.ceil(24/speed))

    def test_verified_caption_window_and_sequential_summary_timing(self):
        event = {"limb": "left_foot", "action": "move_up", "start_seconds": 2., "end_seconds": 3., "evidence_status": "locally_verified"}
        groups = [{"events": [event]}]
        self.assertIsNone(active_event(groups, 1.9))
        self.assertEqual(active_event(groups, 2.4)['limb'], 'left_foot')
        self.assertIsNone(active_event(groups, 4.))
        self.assertEqual(summary_seconds([]), 0)
        self.assertAlmostEqual(summary_seconds([{}] * 5), 6.8)

    def test_base_movie_layout_survives_without_extra_skeleton_or_cropping(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'base.mp4'
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'mp4v'), 4, (96,64))
            pixels = np.zeros((64,96,3), dtype=np.uint8)
            pixels[:, :64] = [50,90,160]
            pixels[:, 64:] = [140,180,40]
            pixels[48:] = [20,140,190]
            for _ in range(24): writer.write(pixels)
            writer.release()
            cap = cv2.VideoCapture(str(source)); _, original = cap.read(); cap.release()
            result = organize({'result': evidence()})
            plan = make_plan(result, base_video=result['video'], summary=False)
            composition = ActionComposition(plan, source)
            base = composition.raw(0)
            rendered = composition.overlay(base, 0)
            np.testing.assert_array_equal(np.asarray(rendered)[:, :96, :3], cv2.cvtColor(original, cv2.COLOR_BGR2RGB))
            self.assertEqual(rendered.size[1], 64)
            composition.video.close()

    def test_model_agreement_cannot_override_visible_track_conflict(self):
        result = evidence()
        for s in result["pose_samples"]:
            s["kpts_xy"][16] = [.8, .7]
        organized = organize({"result": result})
        frames = [{"frame_id": f"frame-{i}", "time_seconds": i} for i in (0, 1, 2)]
        event = {"limb": "right_foot", "action": "move_up", "frame_ids": [f["frame_id"] for f in frames]}
        checked = {"events": [dict(event, verified=True, conflict=False)]}
        checked = track_conflicts({"events": [event]}, checked, organized, frames)
        self.assertFalse(checked["events"][0]["verified"])
        self.assertTrue(checked["events"][0]["conflict"])

    def test_no_mutation_no_coaching_counts_and_motion_independent(self):
        result = evidence()
        original = copy.deepcopy(result)
        organized = organize({"result": result})
        self.assertEqual(result, original)
        metrics = {m["key"]: m for m in organized["metrics"]}
        self.assertEqual(metrics["left_hand"]["value"], 1)
        self.assertNotIn("right_foot", metrics)
        self.assertEqual(metrics["duration"]["label"], "视频记录时长")
        self.assertGreater(metrics["moving"]["value"], 0)
        self.assertEqual(metrics["moving"]["basis"], "registered_body_and_limbs")
        self.assertTrue(all(g["description"] == "动作片段" for g in organized["groups"]))

    def test_camera_movement_is_removed_and_missing_contact_does_not_hide_motion(self):
        result = evidence()
        for sample in result["pose_samples"]:
            dx = sample["kpts_xy"][0][0] - .2
            sample["wall_reference_transform"][0][2] = -dx * 96
        self.assertTrue(all(row["kind"] == "relative_still" for row in motion_intervals(result)))
        result["pose_samples"][8]["wall_alignment"] = "unknown"
        self.assertTrue(any(row["kind"] == "unknown" for row in motion_intervals(result)))

    def test_every_named_side_requires_its_own_local_chain_check(self):
        group = {"id": "a", "start_seconds": 0., "end_seconds": 2., "description": "动作片段", "events": []}
        frames = [{"frame_id": f"frame-{i}", "time_seconds": i} for i in range(3)]
        event = {"limb": "right_foot", "action": "move_up", "frame_ids": [f["frame_id"] for f in frames]}
        check = dict(event, verified=True, chain_continuous=True, conflict=False, occluded=False)
        clean = apply_local_review(group, {"events": [event]}, {"events": [check]}, frames)
        self.assertEqual(clean["description"], "右脚抬脚")
        for field, value in [("verified", False), ("conflict", True), ("chain_continuous", False), ("limb", "left_foot"), ("occluded", True)]:
            invalid = dict(check, **{field: value})
            self.assertEqual(apply_local_review(group, {"events": [event]}, {"events": [invalid]}, frames)["description"], "动作片段")
        partial = apply_local_review(group, {"events": [event, event]}, {"events": [check]}, frames)
        self.assertEqual(partial["description"], "右脚抬脚")
        self.assertEqual(partial["coverage_status"], "partial")

    def test_source_gap_does_not_generate_unknown_chapters(self):
        result = evidence()
        result["pose_samples"] = []
        out = organize({"result": result})
        self.assertEqual(out["groups"], [])
        plan = make_plan(out)
        self.assertEqual(validate(plan), 32)
        self.assertEqual(plan["caption"], "")

    def test_group_export_exact_native_range_speed_and_no_summary(self):
        out = organize({"result": evidence()})
        full = make_plan(out, speed=1)
        self.assertEqual(validate(full), 24)
        group = out["groups"][0]
        plan = make_plan(out, scope="group", group_id=group["id"], speed=.5)
        self.assertEqual(validate(plan), (plan["source_stop_frame"] - plan["source_start_frame"]) * 2)
        self.assertEqual(plan["summary_seconds"], 0)
        with self.assertRaises(ValueError):
            make_plan(out, scope="group", group_id="missing")

    def test_real_encoder_full_decode_native_last_frame_and_atomic_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 4, (96, 64))
            for i in range(24):
                writer.write(np.full((64, 96, 3), i * 10, dtype=np.uint8))
            writer.release()
            result = evidence(); result["pose_samples"] = []
            plan = make_plan(organize({"result": result}), summary=False, annotations=False)
            target = root / "result.mp4"
            render_actions(source, plan, target)
            cap = cv2.VideoCapture(str(target)); frames = []
            while True:
                ok, frame = cap.read()
                if not ok: break
                frames.append(frame)
            cap.release()
            self.assertEqual(len(frames), 32)
            self.assertEqual(frames[-1].shape[:2], (64,96))
            self.assertGreater(frames[-1].mean(), 220)
            with self.assertRaises(ValueError): render_actions(source, plan, target)

    def test_page_presentation_never_burns_descriptions_or_summary(self):
        result = organize({'result': evidence()})
        plan = make_plan(result, summary=True, annotations=True)
        self.assertEqual(plan['speed'], .75)
        self.assertEqual(plan['width'], plan['base_width'])
        self.assertEqual(plan['summary_seconds'], 0)
        self.assertFalse(plan['annotations'])
        changed = dict(plan, annotations=True)
        with self.assertRaises(ValueError): validate(changed)


class ActionLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ReplayCoachingLifecycleTests(); self.fixture.setUp()
        self.store = self.fixture.store
        self.calls = []
        def renderer(source, plan, target, **kwargs):
            self.calls.append(plan)
            if getattr(self, "render_failure", False): raise RuntimeError("private error")
            target.write_bytes(b"synthetic-mp4-0123456789")
        # Router already owns the manager; inject only the local renderer.
        self.manager = self.store.action_manager
        self.manager.renderer = renderer
        self.id = self.fixture.job_id
        self.store.update(self.id, result=evidence())
        # The approved base movie is real media; the inherited coaching fixture
        # used a placeholder because it did not decode the overlay.
        job = self.store.get(self.id, 'alice', private=True)
        overlay, _ = self.store.media_file(self.id, 'alice', 'overlay_video')
        temporary = overlay.with_name('fixture-base.mp4')
        writer = cv2.VideoWriter(str(temporary), cv2.VideoWriter_fourcc(*'mp4v'), 4, (96,64))
        for _ in range(24): writer.write(np.full((64,96,3), 110, dtype=np.uint8))
        writer.release()
        overlay.write_bytes(temporary.read_bytes())
        self.url = f"/api/climb-replay/jobs/{self.id}/actions"
        self.client = self.fixture.client

    def tearDown(self): self.fixture.tearDown()

    def wait(self, key="task"):
        for _ in range(200):
            result = self.client.get(self.url).json()
            if result[key]["status"] not in {"queued", "running"}: return result
            time.sleep(.01)
        self.fail("action task did not finish")

    def test_owner_cache_export_and_range(self):
        self.assertEqual(self.client.get(self.url, headers={"x-user": "bob"}).status_code, 404)
        self.assertEqual(self.client.post(self.url, json={}).status_code, 202)
        data = self.wait(); version = data["result_version"]
        self.assertEqual(data["task"]["status"], "succeeded")
        self.assertTrue(self.calls[-1]['preserve_base'])
        self.assertFalse(self.calls[-1]['annotations'])
        self.assertEqual(self.calls[-1]['speed'], 1)
        self.assertEqual(self.calls[-1]['summary_seconds'], 0)
        self.assertEqual(self.client.post(self.url, json={}).status_code, 202)
        self.assertEqual(len(self.calls), 1)
        media = self.client.get(self.url + "/media", params={"version": version}, headers={"Range": "bytes=0-4"})
        self.assertEqual(media.status_code, 206)
        self.assertNotIn("storage_name", self.client.get(self.url).text)
        self.assertNotIn("action_result", self.client.get(f"/api/climb-replay/jobs/{self.id}").json())
        response = self.client.post(self.url + "/export", json={"result_version": version, "scope": "group", "group_id": "action-001", "speed": .5})
        self.assertEqual(response.status_code, 202, response.text)
        exported = self.wait("export")
        self.assertEqual(exported["export"]["status"], "succeeded")
        self.assertEqual(self.calls[-1]["summary_seconds"], 0)
        self.assertEqual(len(self.fixture.engine.calls), 0)

    def test_default_export_is_three_quarter_speed_and_history_is_private(self):
        self.client.post(self.url, json={})
        data = self.wait()
        self.store.update(self.id, action_revisions=[{'result': {'internal': True}}],
                          action_revision_audit=[{'previous_result': {'internal': True}}])
        public = self.client.get(f'/api/climb-replay/jobs/{self.id}').json()
        self.assertNotIn('action_revisions', public)
        self.assertNotIn('action_revision_audit', public)
        response = self.client.post(self.url + '/export', json={'result_version': data['result_version']})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(self.wait('export')['export']['status'], 'succeeded')
        self.assertEqual(self.calls[-1]['speed'], .75)
        self.assertEqual(self.calls[-1]['summary_seconds'], 0)
        self.assertFalse(self.calls[-1]['annotations'])

    def test_retained_burned_text_video_does_not_replace_base_presentation(self):
        self.client.post(self.url, json={})
        self.wait()
        job = self.store.get(self.id, 'alice', private=True)
        self.store.update(self.id, action_result=dict(job['action_result'],
                          presentation_version='base-replay-fine-action-captions-v5'))
        current = self.client.get(self.url).json()
        self.assertIsNotNone(current['result'])
        self.assertFalse(current['media_ready'])
        self.assertFalse(current['stale'])

    def test_changed_evidence_invalidates_old_version_and_failure_keeps_movie(self):
        self.client.post(self.url, json={}); old = self.wait()
        self.render_failure = True
        # Different cloud choice cannot bypass explicit consent or unavailable config.
        self.assertEqual(self.client.post(self.url, json={"cloud_consent": True}).status_code, 400)
        result = evidence(); result["holds"] = [{"id": 1}]
        self.store.update(self.id, result=result)
        self.assertTrue(self.client.get(self.url).json()["stale"])
        self.assertEqual(self.client.get(self.url + "/media", params={"version": old["result_version"]}).status_code, 409)
        self.client.post(self.url, json={}); failed = self.wait()
        self.assertEqual(failed["task"]["status"], "failed")
        self.assertTrue((self.store._path(self.id).parent / f'actions-{old["result_version"]}.mp4').exists())


if __name__ == "__main__": unittest.main()
