import unittest
from core.replay_coaching_cost import estimate_coaching_cost, estimate_ledger_cost


class CostTests(unittest.TestCase):
    def test_malformed_historic_usage_remains_unknown(self):
        for value in (None, [], {"usage": [1]}, {"stage_usage": [{"usage": "invalid"}]}):
            self.assertEqual(estimate_coaching_cost(value)["status"], "unavailable")
        self.assertEqual(estimate_ledger_cost({})["status"], "unavailable")
    def test_partial_ledger_keeps_known_charges_without_claiming_a_total(self):
        cost = estimate_ledger_cost([
            {"model": "qwen3-vl-plus", "usage_complete": True,
             "usage": {"prompt_tokens": 1000, "completion_tokens": 100}},
            {"model": "qwen3-vl-plus", "status": "failed", "usage_complete": False},
        ])
        self.assertEqual(cost["status"], "partial")
        self.assertEqual(cost["known_amount"], .002)
        self.assertEqual(cost["unknown_request_count"], 1)
        self.assertNotIn("amount_max", cost)

    def test_no_request_is_distinguished_from_unknown_charge(self):
        self.assertEqual(estimate_ledger_cost([])["status"], "not_started")
        self.assertEqual(estimate_ledger_cost([{"status": "started"}])["status"], "unavailable")

    def test_unlisted_snapshot_does_not_inherit_price_by_prefix(self):
        self.assertEqual(estimate_coaching_cost({"model": "qwen3-vl-plus-2025-fictional",
            "usage": {"prompt_tokens": 1000, "completion_tokens": 100}})["status"], "unavailable")
    def test_each_request_uses_its_own_tier(self):
        stages = [{"model": "qwen3-vl-plus", "usage": {"prompt_tokens": 40000, "completion_tokens": 1500}},
                  {"model": "qwen3-vl-plus", "usage": {"prompt_tokens": 5000, "completion_tokens": 800}}]
        cost = estimate_coaching_cost({"stage_usage": stages})
        self.assertEqual(cost["amount_min"], .0955)
        self.assertEqual(cost["amount_max"], .0955)
        self.assertEqual(cost["request_count"], 2)

    def test_historic_total_is_a_range_not_a_bill(self):
        cost = estimate_coaching_cost({"model": "qwen3-vl-plus", "usage": {"prompt_tokens": 45236, "completion_tokens": 2303}})
        self.assertEqual(cost["status"], "range")
        self.assertEqual(cost["amount_min"], .068266)
        self.assertEqual(cost["amount_max"], .102399)

    def test_missing_usage_and_unknown_model_do_not_become_free(self):
        for provenance in ({}, {"model": "qwen3-vl-plus", "usage": {"prompt_tokens": 1}},
                           {"model": "other", "usage": {"prompt_tokens": 1, "completion_tokens": 1}}):
            self.assertEqual(estimate_coaching_cost(provenance)["status"], "unavailable")

    def test_boundary_and_negative_counts(self):
        for prompt, factor in ((32000, 1), (32001, 1.5), (128000, 1.5), (128001, 3)):
            cost = estimate_coaching_cost({"stage_usage": [{"model": "qwen3-vl-plus", "usage": {"prompt_tokens": prompt, "completion_tokens": 0}}]})
            self.assertEqual(cost["amount_min"], round(prompt * factor / 1e6, 6))
        self.assertEqual(estimate_coaching_cost({"model": "qwen3-vl-plus", "usage": {"prompt_tokens": -1, "completion_tokens": 1}})["status"], "unavailable")
