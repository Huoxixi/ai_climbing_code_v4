import unittest

import cv2
import numpy as np

from experiments.hole_grid_topology import (HoleCandidate, generate_hole_candidates, map_grid_point,
                                             render_hole_grid_overlay, solve_hole_grid)


def lattice(columns=13, rows=17, missing=frozenset(), outliers=()):
    origin = np.asarray([72., 51.])
    basis = np.asarray([[31., 2.4], [-2.2, 29.]])
    values = []
    for x in range(columns):
        for y in range(rows):
            if (x, y) in missing:
                continue
            point = origin + np.asarray([x, y]) @ basis
            values.append(HoleCandidate(*point, .93, ('fixture',)))
    values.extend(HoleCandidate(float(x), float(y), .72, ('hard-negative',)) for x, y in outliers)
    return values, origin, basis


class HoleGridTopologyTests(unittest.TestCase):
    def test_unknown_extent_and_missing_cells_stay_inferred(self):
        missing = {(5, 5), (8, 11)}
        candidates, _, _ = lattice(missing=missing)
        result = solve_hole_grid(candidates, image_shape=(650, 520))
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(result['grid_extent_status'], 'unknown')
        self.assertFalse(result['diagnostics']['absolute_extent_assumed'])
        self.assertFalse(result['diagnostics']['inferred_used_for_fit'])
        self.assertFalse(result['acceptance']['passed'])
        self.assertEqual(result['acceptance']['semantic_purity'], 'unverified')
        self.assertGreaterEqual(len(result['observed']), 210)
        self.assertGreaterEqual(len(result['inferred']), 2)
        observed_cells = {tuple(item['grid']) for item in result['observed']}
        inferred_cells = {tuple(item['grid']) for item in result['inferred']}
        self.assertTrue(observed_cells.isdisjoint(inferred_cells))

    def test_hard_negatives_do_not_form_duplicate_grid_assignments(self):
        outliers = [(90, 390), (206, 205), (401, 88), (251, 501), (40, 260)]
        candidates, _, _ = lattice(missing={(2, 3), (4, 9)}, outliers=outliers)
        result = solve_hole_grid(candidates, image_shape=(650, 520))
        cells = [tuple(item['grid']) for item in result['hypotheses'][0]['assignments']]
        self.assertEqual(len(cells), len(set(cells)))
        self.assertGreaterEqual(len(result['rejected']), 4)
        self.assertTrue(all(item['determinant'] != 0 for item in result['hypotheses']))

    def test_magsac_refinement_recovers_moderate_perspective_without_foldover(self):
        matrix = np.asarray([[34., -1.5, 55.], [1.2, 31., 42.], [.0012, .0008, 1.]])
        candidates = []
        for x in range(14):
            for y in range(16):
                if 5 <= x <= 8 and 6 <= y <= 9:
                    continue
                value = matrix @ np.asarray([x, y, 1.])
                candidates.append(HoleCandidate(value[0]/value[2], value[1]/value[2], .94, ('fixture',)))
        candidates.extend(HoleCandidate(x, y, .7, ('hard-negative',)) for x, y in
                          ((31, 260), (180, 70), (390, 155), (245, 420)))
        result = solve_hole_grid(candidates, image_shape=(560, 560))
        self.assertGreaterEqual(len(result['observed']), 200)
        self.assertEqual(result['diagnostics']['foldover_count'], 0)
        self.assertIn(result['hypotheses'][0]['continuous_model']['robust_method'],
                      ('usac-magsac', 'ransac-fallback'))
        mapped = map_grid_point(result['hypotheses'][0]['continuous_model'], (3, 4))
        self.assertTrue(np.isfinite(mapped).all())

    def test_detector_merges_multiple_sources_without_fixed_dimensions(self):
        image = np.full((520, 430, 3), 190, np.uint8)
        for x in range(11):
            for y in range(14):
                point = np.asarray([45., 38.]) + np.asarray([x, y]) @ np.asarray([[33., 1.2], [-1.4, 31.]])
                cv2.circle(image, tuple(np.rint(point).astype(int)), 3, (28, 28, 28), -1)
        cv2.putText(image, 'NOTICE', (90, 260), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (30, 30, 30), 3)
        candidates = generate_hole_candidates(image)
        self.assertGreater(len(candidates), 100)
        self.assertTrue(any(len(item.sources) > 1 for item in candidates))
        result = solve_hole_grid(candidates, image_shape=image.shape[:2])
        self.assertEqual(result['grid_extent_status'], 'unknown')
        self.assertGreater(len(result['observed']), 90)
        self.assertLessEqual(len(result['hypotheses']), 20)

    def test_insufficient_evidence_is_rejected(self):
        result = solve_hole_grid([HoleCandidate(float(i), 10., .9) for i in range(5)])
        self.assertEqual(result['status'], 'insufficient_evidence')
        self.assertFalse(result['observed'])

    def test_overlay_is_a_copy_and_can_hide_rejected_candidates(self):
        source = np.zeros((40, 40, 3), np.uint8)
        result = {'observed': [{'point': [10, 10]}], 'inferred': [{'point': [20, 10]}],
                  'ambiguous': [{'point': [30, 10]}], 'rejected': [{'point': [10, 30]}]}
        hidden = render_hole_grid_overlay(source, result)
        debug = render_hole_grid_overlay(source, result, show_rejected=True)
        self.assertFalse(source.any())
        self.assertTrue(hidden[10, 10].any())
        self.assertFalse(hidden[30, 10].any())
        self.assertTrue(debug[30, 10].any())


if __name__ == '__main__':
    unittest.main()
