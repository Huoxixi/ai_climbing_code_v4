import copy
import unittest
from core.replay_action_evaluation import evaluate
from core.replay_action_naming import NAMING_VERSION


class EvaluationTests(unittest.TestCase):
    def fixture(self):
        event = {"code": "HAND_MOVE", "limb": "left_hand", "start_seconds": 1, "end_seconds": 2,
                 "target_hold_id": "1", "conditions_met": True, "eligible": True, "status": "locally_verified"}
        return {"naming_version": NAMING_VERSION, "protocol_frozen": False, "attempts": [
            {"attempt_id": "constructed-1", "participant_group": "p1", "route_group": "r1", "split": "holdout",
             "real_video": False, "authorized": False, "references": [event], "predictions": [copy.deepcopy(event)], "negative_codes": ["FOOT_SWAP"]}]}

    def test_constructed_success_does_not_pass(self):
        result = evaluate(self.fixture())
        self.assertEqual(result['classes']['HAND_MOVE']['precision'], 1)
        self.assertFalse(result['classes']['HAND_MOVE']['meets_proposed_gate'])
        self.assertFalse(result['automatic_confirmation_granted'])

    def test_abstention_is_not_success(self):
        dataset = self.fixture(); dataset['attempts'][0]['predictions'] = []
        result = evaluate(dataset)['classes']['HAND_MOVE']
        self.assertIsNone(result['precision'])
        self.assertEqual(result['recall'], 0)

    def test_wrong_side_contact_and_time_are_errors(self):
        for patch in ({'limb': 'right_hand'}, {'target_hold_id': '2'}, {'end_seconds': 4}):
            dataset = self.fixture(); dataset['attempts'][0]['predictions'][0].update(patch)
            self.assertEqual(evaluate(dataset)['classes']['HAND_MOVE']['precision'], 0)

    def test_connected_user_route_leakage_is_detected(self):
        dataset = self.fixture()
        dataset['attempts'] += [{"attempt_id": "dev", "participant_group": "p2", "route_group": "r1", "split": "development"},
                                {"attempt_id": "dev2", "participant_group": "p2", "route_group": "r2", "split": "development"}]
        self.assertTrue(evaluate(dataset)['development_holdout_leakage'])

    def test_personal_corrections_are_not_algorithm_predictions(self):
        dataset = self.fixture(); dataset['attempts'][0]['predictions'][0]['status'] = 'human_confirmed'
        self.assertIsNone(evaluate(dataset)['classes']['HAND_MOVE']['precision'])


if __name__ == '__main__':
    unittest.main()
