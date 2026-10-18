import copy
import unittest
import numpy as np
from core.replay_pose_start import pose_climbing_window
from core.replay_torso_trajectory import center_of_mass_trajectory
from core.replay_analysis_view import visual_evidence
from core.replay_action_renderer import make_plan


def clip(kind='climb'):
    poses = []
    base = [[.5,.16],[.48,.15],[.52,.15],[.46,.16],[.54,.16],
            [.42,.35],[.58,.35],[.39,.27],[.61,.27],[.4,.2],[.6,.2],
            [.44,.55],[.56,.55],[.43,.68],[.57,.68],[.42,.82],[.58,.82]]
    for i in range(17):
        xy = copy.deepcopy(base)
        for j in range(17):
            if kind == 'walk':
                xy[j][0] += i*.012
                if j in (9,10): xy[j][1] = .57
            elif kind == 'climb' and j not in (9,10):
                xy[j][1] -= max(0, i-4)*.012
        poses.append({'observed':True,'time_seconds':i/4,'source_frame_id':i*6,
                      'kpts_xy':xy,'kpts_score':[.9]*17,'wall_alignment':'reference',
                      'wall_reference_transform':np.eye(3).tolist()})
    return {'video':{'width':640,'height':480,'fps':24,'frame_count':96,'duration_seconds':4},
            'source_duration_seconds':4,'skeleton_only':True,'pose_samples':poses,'groups':[], 'metrics':[]}


class PoseStartTests(unittest.TestCase):
    def test_walk_and_standing_raised_hands_do_not_start(self):
        for kind in ('walk','stand'):
            raw = clip(kind)
            original = copy.deepcopy(raw)
            self.assertIsNone(pose_climbing_window(raw)['start_seconds'])
            self.assertEqual(center_of_mass_trajectory(raw)['segments'], [])
            self.assertEqual(raw, original)

    def test_sustained_climbing_can_start_without_any_holds(self):
        window = pose_climbing_window(clip())
        self.assertEqual(window['status'], 'pose_start_observed')
        self.assertLess(window['start_seconds'], 2)
        self.assertFalse(window['finish_confirmed'])
        self.assertTrue(center_of_mass_trajectory(clip())['segments'])

    def test_user_mark_works_and_survives_export_plan(self):
        raw = clip('walk'); raw['trajectory_start_seconds'] = 1.25
        route = center_of_mass_trajectory(raw)
        self.assertEqual(route['climbing_window']['status'], 'user_confirmed')
        self.assertTrue(all(p['time_seconds'] >= 1.25 for run in route['segments'] for p in run))
        plan = make_plan(raw, summary=False, analysis_right=True)
        rendered = visual_evidence({'video':plan['source_video'], 'pose_samples':raw['pose_samples'],
                    'skeleton_only':plan['skeleton_only'], 'trajectory_start_seconds':plan['trajectory_start_seconds']})
        self.assertEqual(rendered['center_of_mass_trajectory']['segments'], route['segments'])

    def test_missing_pose_breaks_path_and_blocks_automatic_onset(self):
        raw = clip(); raw['pose_samples'][6]['observed'] = False
        raw['trajectory_start_seconds'] = .5
        route = center_of_mass_trajectory(raw)
        self.assertGreaterEqual(len(route['segments']), 2)
        self.assertFalse(any(p['time_seconds'] == 1.5 for run in route['segments'] for p in run))
        for p in raw['pose_samples']: p['kpts_score'][15] = .1
        raw.pop('trajectory_start_seconds')
        self.assertIsNone(pose_climbing_window(raw)['start_seconds'])

    def test_clear_mark_returns_to_auto(self):
        raw = clip('stand'); raw['trajectory_start_seconds'] = 1
        self.assertEqual(pose_climbing_window(raw)['status'], 'user_confirmed')
        raw['trajectory_start_seconds'] = None
        self.assertIsNone(pose_climbing_window(raw)['start_seconds'])


class PoseStartApiTests(unittest.TestCase):
    def setUp(self):
        from test_replay_actions import ActionLifecycleTests
        self.fixture = ActionLifecycleTests(); self.fixture.setUp()
        self.manager, self.store, self.id = self.fixture.manager, self.fixture.store, self.fixture.id
        self.store.update(self.id, skeleton_only=True, result=clip('stand'))

    def tearDown(self): self.fixture.tearDown()

    def test_owner_validation_persistence_and_clear(self):
        from core.replay_action_jobs import TrajectoryStart
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            self.manager.set_trajectory_start(self.id, 'bob', TrajectoryStart(start_seconds=1))
        with self.assertRaises(HTTPException):
            self.manager.set_trajectory_start(self.id, 'alice', TrajectoryStart(start_seconds=4))
        data = self.manager.set_trajectory_start(self.id, 'alice', TrajectoryStart(start_seconds=1))
        route = data['result']['center_of_mass_trajectory']
        self.assertEqual(route['climbing_window']['start_seconds'], 1)
        self.assertTrue(route['segments'])
        self.assertEqual(self.store.get(self.id, 'alice', private=True)['trajectory_start_seconds'], 1)
        cleared = self.manager.set_trajectory_start(self.id, 'alice', TrajectoryStart())
        self.assertIsNone(cleared['result']['center_of_mass_trajectory']['climbing_window']['start_seconds'])
        self.assertEqual(self.fixture.calls, [])

    def test_change_versions_invalidates_export_but_preserves_original_and_paid_checkpoint(self):
        from core.replay_action_jobs import TrajectoryStart
        from core.replay_actions import organize
        job = self.store.get(self.id, 'alice', private=True)
        record = {'id':'old', 'fingerprint':self.manager.fingerprint(job), 'result':organize(job)}
        self.store.update(self.id, action_result=record, action_export_media={'id':'previous-export'},
                          action_commentary_checkpoint={'responses':{'retained':True}})
        self.manager.set_trajectory_start(self.id, 'alice', TrajectoryStart(start_seconds=1))
        saved = self.store.get(self.id, 'alice', private=True)
        self.assertNotEqual(saved['action_result']['id'], 'old')
        self.assertEqual(saved['action_result_history'][-1], record)
        self.assertIsNone(saved['action_export_media'])
        self.assertEqual(saved['action_commentary_checkpoint']['responses'], {'retained':True})
        self.assertEqual(saved['result'], job['result'])

    def test_busy_and_hold_mode_are_rejected(self):
        from core.replay_action_jobs import TrajectoryStart
        from fastapi import HTTPException
        self.store.update(self.id, action_export={'status':'running'})
        with self.assertRaises(HTTPException):
            self.manager.set_trajectory_start(self.id, 'alice', TrajectoryStart(start_seconds=1))
        raw = clip('stand');raw['skeleton_only'] = False
        self.store.update(self.id, action_export=None, skeleton_only=False, result=raw)
        with self.assertRaises(HTTPException):
            self.manager.set_trajectory_start(self.id, 'alice', TrajectoryStart(start_seconds=1))

    def test_http_validation_and_owner_checks(self):
        url = self.fixture.url + '/trajectory-start'
        for value in (-1, 4):
            self.assertEqual(self.fixture.client.put(url, json={'start_seconds':value}).status_code, 422)
        self.assertEqual(self.fixture.client.put(url, json={'start_seconds':1}, headers={'x-user':'bob'}).status_code, 404)
        response = self.fixture.client.put(url, json={'start_seconds':1})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['result']['center_of_mass_trajectory']['climbing_window']['status'], 'user_confirmed')
