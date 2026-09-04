import unittest

from core.standard_board import query_standard_routes, route_tags


class StandardBoardTagTest(unittest.TestCase):
    def test_summary_includes_difficulty_and_quality_tags(self):
        response = query_standard_routes(difficulty="7A", limit=1)
        self.assertEqual(len(response.routes), 1)
        tags = response.routes[0].tags
        self.assertIn("difficulty:7a", tags)
        self.assertTrue(any(tag.startswith("quality:") for tag in tags))

        plus_route = query_standard_routes(difficulty="6B+", limit=1).routes[0]
        self.assertIn("difficulty:6b-plus", plus_route.tags)

    def test_tags_are_stable_for_the_same_query(self):
        first = query_standard_routes(difficulty="7A", limit=1).routes[0]
        second = query_standard_routes(difficulty="7A", limit=1).routes[0]
        self.assertEqual(first.tags, second.tags)

    def test_any_and_all_tag_matching(self):
        reference = query_standard_routes(difficulty="7A", limit=1).routes[0]
        tags = reference.tags
        self.assertGreaterEqual(len(tags), 2)

        all_matches = query_standard_routes(tag_ids=",".join(tags[:2]), tag_match="all", limit=100)
        self.assertTrue(all(set(tags[:2]).issubset(route.tags) for route in all_matches.routes))

        any_matches = query_standard_routes(tag_ids=f"missing:tag,{tags[0]}", tag_match="any", limit=100)
        self.assertGreater(any_matches.total, 0)
        self.assertTrue(all(tags[0] in route.tags for route in any_matches.routes))

    def test_route_tags_expose_score_driven_style_tags(self):
        response = query_standard_routes(difficulty="7A", limit=100)
        self.assertTrue(any(any(tag.startswith("style:") for tag in route.tags) for route in response.routes))


if __name__ == "__main__":
    unittest.main()
