"""Paid-response durability and zero-network local recovery contracts."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

import test_replay_actions as lifecycle
import test_replay_professional as professional
from core.replay_commentary import VERSION
from core.replay_vision_provider import VisionAPIError
from core.replay_vision_settings import save_settings, VisionSettings


class CommentaryRecoveryTests(unittest.TestCase):
    def helper(self):
        helper = professional.CommentaryTests()
        self.addCleanup(helper.doCleanups)
        return helper

    def test_response_survives_invalid_json_and_retry_does_not_charge_again(self):
        provider = Mock(return_value={'content':'invalid-json', 'usage':{}})
        engine, path, ledger, _, _ = self.helper().run_engine(provider=provider)
        responses = {}
        kwargs = dict(cancelled=lambda:False, usage_callback=ledger.append,
                      previous_responses=responses,
                      response_callback=lambda key,value:responses.update({key:value}))
        for _ in range(2):
            with self.assertRaises(json.JSONDecodeError):
                engine.run(path, {}, professional.action_fixture(), **kwargs)
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(ledger[-1]['status'], 'succeeded')
        self.assertEqual(len(responses), 1)

    def test_partial_failure_reuses_successful_batch_after_restart(self):
        helper = self.helper()
        engine, path, ledger, calls, response = helper.run_engine()
        data = professional.action_fixture()
        seeds = data['action_evidence']['actions']
        actions = [{**copy.deepcopy(seeds[i%2]), 'id':f'action-{i}'} for i in range(4)]
        data['action_evidence']['actions'] = actions
        for group in data['groups']:
            group['action_features'] = [a for a in actions if a['group_id'] == group['id']]
        responses = {}
        def first_attempt(**kwargs):
            if len(calls) == 1:
                raise VisionAPIError('synthetic failure')
            return response(**kwargs)
        engine.provider = first_attempt
        kwargs = dict(cancelled=lambda:False, usage_callback=ledger.append,
            response_callback=lambda key,value:responses.update({key:value}))
        with self.assertRaises(VisionAPIError):
            engine.run(path, {}, data, **kwargs)
        self.assertEqual(len(responses), 1)
        from core.replay_commentary import LegacyVisionCommentaryEngine as VisionCommentaryEngine
        restarted = VisionCommentaryEngine(engine.config, provider=response)
        result = restarted.run(path, {}, data, previous_responses=responses, **kwargs)
        self.assertEqual(len(calls), 2)  # two successful batches total
        self.assertEqual(result['commentary_status']['accepted_comments'], 4)

    def test_successful_vision_survives_budget_and_model_setting_changes(self):
        engine, path, ledger, calls, _ = self.helper().run_engine()
        responses = {}
        kwargs = dict(cancelled=lambda:False, usage_callback=ledger.append,
            previous_responses=responses,
            response_callback=lambda key,value:responses.update({key:value}))
        data = professional.action_fixture()
        engine.run(path, {}, data, **kwargs)
        engine.run(path, {}, data, **kwargs)
        self.assertEqual(len(calls), 1)
        engine.config['budget_cny'] = 2
        engine.run(path, {}, data, **kwargs)
        self.assertEqual(len(calls), 1)
        engine.config['model'] = 'different-model'
        engine.run(path, {}, data, **kwargs)
        self.assertEqual(len(calls), 1)

    def fixture(self):
        fixture = lifecycle.ActionLifecycleTests()
        fixture.setUp()
        professional.prepare_paid_fixture(fixture)
        self.addCleanup(fixture.tearDown)
        save_settings(fixture.store.root.parent, 'alice', VisionSettings(**professional.config()))
        return fixture

    def test_commentary_is_saved_without_render_and_local_recovery_never_calls_model(self):
        fixture = self.fixture()
        def run(source, job, result, **kwargs):
            kwargs['usage_callback']({'request_id':'paid-once', 'stage':'action_commentary',
                'status':'succeeded','usage_complete':True,'amount_cny':.1})
            kwargs['vision_complete_callback']()
            result['commentary_version'] = VERSION
            return result
        engine = Mock(); engine.run.side_effect = run
        fixture.render_failure = True
        with patch('core.replay_action_jobs.VisionCommentaryEngine', return_value=engine):
            fixture.client.post(fixture.url, json={'cloud_consent':True,
                'consent_version':VERSION,'budget_confirmed':True})
            failed = fixture.wait()
            self.assertTrue(failed['saved_commentary_available'])
            self.assertEqual(failed['task']['status'], 'succeeded')
            self.assertEqual(fixture.calls, [])
            self.assertNotIn('action_commentary_checkpoint', fixture.store.get(fixture.id, 'alice'))
            # Local recovery works after disabling the paid provider too.
            save_settings(fixture.store.root.parent, 'alice', VisionSettings())
            fixture.render_failure = False
            response = fixture.client.post(fixture.url, json={'reuse_saved_commentary':True})
            self.assertEqual(response.status_code, 202)
            recovered = fixture.wait()
            self.assertEqual(recovered['task']['status'], 'succeeded')
            self.assertEqual(recovered['result']['commentary_version'], VERSION)
            self.assertEqual(recovered['task']['usage'], [])
            self.assertEqual(engine.run.call_count, 1)

    def test_missing_checkpoint_cannot_claim_free_recovery(self):
        fixture = self.fixture()
        response = fixture.client.post(fixture.url, json={'reuse_saved_commentary':True})
        self.assertEqual(response.status_code, 409)


if __name__ == '__main__':
    unittest.main()
