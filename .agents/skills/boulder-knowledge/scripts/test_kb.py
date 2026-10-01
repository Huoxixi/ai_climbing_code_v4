"""Observable validation, retrieval and safe rendering invariants."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import kb
import evaluate_kb


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.lib = kb.load_library(kb.DEFAULT_ROOT)

    def test_real_library_is_connected(self):
        report = kb.validate(self.lib)
        self.assertGreaterEqual(report["units"], 6)
        self.assertEqual(report["automatic_advice_units"], 0)

    def test_missing_evidence_rejected(self):
        self.lib["units"][0]["claims"][0]["evidence_ids"] = ["E-NOT-EXISTING"]
        with self.assertRaisesRegex(kb.InvalidKnowledge, "missing evidence"):
            kb.validate(self.lib)

    def test_ungrounded_source_summary_rejected(self):
        self.lib["units"][0]["claims"][0]["evidence_ids"] = []
        with self.assertRaisesRegex(kb.InvalidKnowledge, "needs evidence"):
            kb.validate(self.lib)

    def test_unread_source_cannot_support_claim(self):
        self.lib["sources"][0]["access_status"] = "located"
        with self.assertRaisesRegex(kb.InvalidKnowledge, "unread source"):
            kb.validate(self.lib)

    def test_duplicate_evidence_rejected(self):
        self.lib["sources"][1]["evidence"][0]["id"] = self.lib["sources"][0]["evidence"][0]["id"]
        with self.assertRaisesRegex(kb.InvalidKnowledge, "duplicate evidence"):
            kb.validate(self.lib)

    def test_automatic_use_cannot_be_enabled_by_boolean(self):
        self.lib["units"][0]["review"]["automatic_use"] = True
        with self.assertRaisesRegex(kb.InvalidKnowledge, "automatic advice disabled"):
            kb.validate(self.lib)

    def test_invented_professional_review_rejected(self):
        self.lib["units"][0]["review"]["professional"] = "approved"
        with self.assertRaisesRegex(kb.InvalidKnowledge, "professional review requires"):
            kb.validate(self.lib)

    def test_progress_cannot_reference_missing_unit(self):
        self.lib["state"]["batches"][0]["unit_ids"].append("KB-FOOT-999")
        with self.assertRaisesRegex(kb.InvalidKnowledge, "missing unit"):
            kb.validate(self.lib)

    def test_units_cannot_be_silently_lost_from_progress(self):
        self.lib["state"]["batches"][0]["unit_ids"].pop()
        with self.assertRaisesRegex(kb.InvalidKnowledge, "not assigned"):
            kb.validate(self.lib)

    def test_read_only_helpers_do_not_mutate(self):
        before = copy.deepcopy(self.lib)
        kb.validate(self.lib)
        kb.status(self.lib)
        kb.search(self.lib, "换脚")
        self.assertEqual(before, self.lib)

    def test_retrieval_supports_synonyms(self):
        queries = {"踩上点以后要挪脚": "KB-FOOT-001", "外侧踩点": "KB-FOOT-002",
                   "Smearing": "KB-FOOT-003", "换脚以后": "KB-FOOT-004",
                   "Rockover": "KB-FOOT-005", "High step": "KB-FOOT-006"}
        for query, expected in queries.items():
            with self.subTest(query=query):
                self.assertIn(expected, [r["id"] for r in kb.search(self.lib, query, limit=3)])

    def test_no_automatic_video_suggestions(self):
        self.assertEqual(kb.search(self.lib, "高抬脚", purpose="video"), [])

    def test_hand_batch_retrieval_in_chinese_and_english(self):
        queries = {
            "侧拉、反扣和 Gaston": "KB-HAND-001",
            "What is an undercling?": "KB-HAND-001",
            "并手和换手是一回事吗": "KB-HAND-002",
            "Matching hands": "KB-HAND-002",
            "Bumping 和原点调整": "KB-HAND-003",
            "Go again": "KB-HAND-003",
            "交叉手从上面过还是下面过": "KB-HAND-004",
            "Cross-through": "KB-HAND-004",
            "拇指看不到能确认捏握吗": "KB-HAND-005",
            "Pinching": "KB-HAND-005",
            "摸到点就算抓住了吗": "KB-HAND-006",
            "First contact": "KB-HAND-006",
        }
        for query, expected in queries.items():
            with self.subTest(query=query):
                result = kb.search(self.lib, query, limit=3)
                self.assertIn(expected, [r["id"] for r in result])
                self.assertTrue(all(r["use"] == "knowledge_candidate_only" for r in result))

    def test_new_hand_units_are_not_automatic_video_advice(self):
        for query in ["侧拉", "并手", "Bumping", "交叉手", "Pinch", "首次触点"]:
            with self.subTest(query=query):
                self.assertEqual(kb.search(self.lib, query, purpose="video"), [])

    def test_hand_batch_membership_matches_actual_files(self):
        expected = {f"KB-HAND-{i:03d}" for i in range(1, 7)}
        batch = next(b for b in self.lib["state"]["batches"] if b["id"] == "B002")
        self.assertEqual(set(batch["unit_ids"]), expected)
        self.assertEqual({u["id"] for u in self.lib["units"] if u["batch_id"] == "B002"}, expected)

    def test_unsupported_grip_and_training_queries_remain_empty(self):
        for query in ["half crimp", "Rose move", "每周悬挂训练几组"]:
            with self.subTest(query=query):
                self.assertEqual(kb.search(self.lib, query), [])

    def test_drafts_are_not_retrieved(self):
        # New categories can change file order: check the actual unit being edited.
        for unit in self.lib["units"]:
            with self.subTest(unit=unit["id"]):
                original = unit["review"]["content"]
                unit["review"]["content"] = "draft"
                self.assertNotIn(unit["id"], [r["id"] for r in kb.search(self.lib, unit["title"], limit=20)])
                unit["review"]["content"] = original

    def test_body_dynamic_batch_retrieval(self):
        queries = {
            "骨盆和胸廓的身体朝向": "KB-BODY-001",
            "Pelvic orientation": "KB-BODY-001",
            "旗式脚一定要悬空吗": "KB-BODY-002",
            "Outside flag": "KB-BODY-002",
            "后旗式和内侧旗式": "KB-BODY-003",
            "Back flagging": "KB-BODY-003",
            "Inside flag": "KB-BODY-003",
            "Drop knee 膝盖必须低于脚吗": "KB-BODY-004",
            "Egyptian": "KB-BODY-004",
            "Pogo 是只靠甩腿吗": "KB-DYN-001",
            "Moonkick": "KB-DYN-001",
            "回脚碰到点就算恢复支撑了吗": "KB-DYN-002",
            "Cutting loose": "KB-DYN-002",
            "Feet cut": "KB-DYN-002",
        }
        for query, expected in queries.items():
            with self.subTest(query=query):
                results = kb.search(self.lib, query, limit=3)
                self.assertIn(expected, [r["id"] for r in results])
                self.assertTrue(all(r["use"] == "knowledge_candidate_only" for r in results))

    def test_body_dynamic_batch_membership(self):
        expected = {f"KB-BODY-{i:03d}" for i in range(1, 5)} | {"KB-DYN-001", "KB-DYN-002"}
        batch = next(b for b in self.lib["state"]["batches"] if b["id"] == "B003")
        self.assertEqual(set(batch["unit_ids"]), expected)
        self.assertEqual({u["id"] for u in self.lib["units"] if u["batch_id"] == "B003"}, expected)

    def test_short_flag_names_prefer_the_specific_variant(self):
        self.assertEqual(kb.search(self.lib, "后旗和内侧旗")[0]["id"], "KB-BODY-003")

    def test_body_dynamic_automatic_advice_stays_disabled(self):
        for query in ["侧身", "外侧旗式", "后旗式", "Drop knee", "Pogo", "回脚"]:
            with self.subTest(query=query):
                self.assertEqual(kb.search(self.lib, query, purpose="video"), [])

    def test_each_checked_unit_can_be_found_by_its_title(self):
        for unit in self.lib["units"]:
            if unit["review"]["content"] == "ai_source_checked":
                with self.subTest(unit=unit["id"]):
                    self.assertIn(unit["id"], [r["id"] for r in kb.search(self.lib, unit["title"], limit=3)])

    def test_tactic_batch_retrieval_in_chinese_and_english(self):
        queries = {
            "墙下想的脚序和上墙不一样": "KB-TACTIC-001",
            "Route preview": "KB-TACTIC-001",
            "摸点次数少了就一定进步了吗": "KB-TACTIC-002",
            "Exploratory movements": "KB-TACTIC-002",
            "没有换点的几秒都算休息吗": "KB-TACTIC-003",
            "Non-movement time": "KB-TACTIC-003",
            "两段录像之间的试攀历史": "KB-TACTIC-004",
            "Route familiarity": "KB-TACTIC-004",
            "一个到顶一个没到顶，总时间能直接比吗": "KB-TACTIC-005",
            "Same-route comparison": "KB-TACTIC-005",
            "没按教练的 beta 爬就是错的吗": "KB-TACTIC-006",
            "Alternative beta": "KB-TACTIC-006",
        }
        for query, expected in queries.items():
            with self.subTest(query=query):
                results = kb.search(self.lib, query, limit=3)
                self.assertIn(expected, [r["id"] for r in results])
                self.assertTrue(all(r["use"] == "knowledge_candidate_only" for r in results))

    def test_tactic_batch_membership(self):
        expected = {f"KB-TACTIC-{i:03d}" for i in range(1, 7)}
        batch = next(b for b in self.lib["state"]["batches"] if b["id"] == "B004")
        self.assertEqual(set(batch["unit_ids"]), expected)
        self.assertEqual({u["id"] for u in self.lib["units"] if u["batch_id"] == "B004"}, expected)

    def test_tactic_automatic_advice_stays_disabled(self):
        for query in ["读线", "探索动作", "停顿", "线路熟悉度", "同线路比较", "失败归因"]:
            with self.subTest(query=query):
                self.assertEqual(kb.search(self.lib, query, purpose="video"), [])

    def test_sources_are_not_duplicated_by_url(self):
        urls = [s["url"].rstrip("/") for s in self.lib["sources"]]
        self.assertEqual(len(urls), len(set(urls)))

    def test_general_training_word_is_not_a_topic_match(self):
        for query in ["训练", "练习", "training", "practice", "每周悬挂训练几组"]:
            with self.subTest(query=query):
                self.assertEqual(kb.search(self.lib, query), [])
        self.assertIn("KB-FOOT-006", [r["id"] for r in kb.search(self.lib, "高抬脚训练", limit=3)])
        # A later, explicitly named topic is still retrievable, even if generic.
        unit = self.lib["units"][0]
        unit["aliases"].append("Training")
        self.assertIn(unit["id"], [r["id"] for r in kb.search(self.lib, "Training")])

    def test_empty_and_unrelated_queries(self):
        self.assertEqual(kb.search(self.lib, ""), [])
        self.assertEqual(kb.search(self.lib, "数据库备份"), [])

    def test_generic_question_does_not_match_on_question_words(self):
        self.assertEqual(kb.search(self.lib, "这是什么？"), [])
        self.assertEqual(kb.search(self.lib, "What is this?"), [])

    def test_alias_match_is_explained_even_without_token_overlap(self):
        result = kb.search(self.lib, "What is backstepping?")[0]
        self.assertEqual(result["id"], "KB-FOOT-002")
        self.assertIn("Backstep", result["matched_names"])

    def test_cli_outputs_utf8_even_with_ascii_process_default(self):
        result = subprocess.run([sys.executable, str(Path(kb.__file__)), "status"],
                                env={**os.environ, "PYTHONIOENCODING": "ascii"},
                                capture_output=True, check=True)
        output = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(output["units"], len(self.lib["units"]))
        self.assertIn("next_batch", output)

    def test_paths_cannot_escape_root(self):
        with self.assertRaisesRegex(kb.InvalidKnowledge, "outside knowledge"):
            kb.safe_path(kb.DEFAULT_ROOT, "../../private.json")

    def test_render_is_repeatable_and_preserves_manual_files(self):
        with tempfile.TemporaryDirectory(prefix="boulder-kb-test-") as directory:
            self.lib["root"] = Path(directory).resolve()
            dest = self.lib["root"] / "HANDBOOK.md"
            kb.render(self.lib)
            first = dest.read_bytes()
            kb.render(self.lib)
            self.assertEqual(first, dest.read_bytes())
            self.assertIn(self.lib["sources"][0]["url"], first.decode("utf-8"))
            dest.write_text("Human notes", encoding="utf-8")
            with self.assertRaisesRegex(kb.InvalidKnowledge, "refusing to overwrite"):
                kb.render(self.lib)
            self.assertEqual(dest.read_text(encoding="utf-8"), "Human notes")

    def test_english_aliases_have_word_boundaries(self):
        for name, query in [("Pause", "menopause"), ("Bump", "bumpkin"), (" - ", "anything")]:
            with self.subTest(name=name, query=query):
                self.assertFalse(kb.name_matches(name, query))
        for name, query in [("Backstep", "backstepping"), ("Back flag", "back flagging"),
                            ("Cross through", "Cross-through"), ("Foot switch", "foot switches")]:
            with self.subTest(name=name, query=query):
                self.assertTrue(kb.name_matches(name, query))

    def test_development_evaluation_covers_all_units_and_abstentions(self):
        suite = kb.load_json(self.lib["root"] / "quality/retrieval-cases.json")
        required = {uid for c in suite["cases"] for uid in c["required_units"]}
        self.assertEqual(required, {u["id"] for u in self.lib["units"]})
        report = evaluate_kb.evaluate(self.lib, suite)
        self.assertTrue(all(r["retrieval_ok"] for r in report["results"]))
        self.assertTrue(all(r["automatic_video_disabled"] for r in report["results"]))
        self.assertFalse(report["independent"])
        self.assertFalse(report["answer_quality_measured"])

    def test_evaluation_rejects_unknown_expectations(self):
        suite = kb.load_json(self.lib["root"] / "quality/retrieval-cases.json")
        suite["cases"][0]["accepted_units"].append("KB-FOOT-999")
        with self.assertRaisesRegex(kb.InvalidKnowledge, "invalid expected units"):
            evaluate_kb.evaluate(self.lib, suite)

    def test_evaluation_rejects_duplicate_cases(self):
        suite = kb.load_json(self.lib["root"] / "quality/retrieval-cases.json")
        suite["cases"].append(copy.deepcopy(suite["cases"][0]))
        with self.assertRaisesRegex(kb.InvalidKnowledge, "duplicate evaluation case"):
            evaluate_kb.evaluate(self.lib, suite)

    def test_development_set_cannot_claim_independent_validation(self):
        suite = kb.load_json(self.lib["root"] / "quality/retrieval-cases.json")
        suite["independent"] = True
        with self.assertRaisesRegex(kb.InvalidKnowledge, "provenance unsupported"):
            evaluate_kb.evaluate(self.lib, suite)

    def test_evaluation_is_read_only_and_repeatable(self):
        suite = kb.load_json(self.lib["root"] / "quality/retrieval-cases.json")
        before = copy.deepcopy((self.lib, suite))
        first = evaluate_kb.evaluate(self.lib, suite)
        self.assertEqual(first, evaluate_kb.evaluate(self.lib, suite))
        self.assertEqual(before, (self.lib, suite))

    def test_gap_register_matches_current_unit_versions(self):
        snapshot = kb.load_json(self.lib["root"] / "quality/gap-register.json")
        self.assertEqual(snapshot["scope"], "open_items_not_review_completion")
        expected = [{"unit_id": u["id"], "version": u["version"], "open_items": u["gaps"]}
                    for u in self.lib["units"]]
        self.assertEqual(snapshot["units"], expected)


if __name__ == "__main__":
    unittest.main()
