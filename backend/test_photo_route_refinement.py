import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import HTTPException

from core.photo_route_analysis import _candidate_masks, analyze_board_photo
from core.photo_route_v2 import ColorRefinement
from test_photo_route_v2 import PhotoRouteV2Tests, photo_bytes


class RefinementStoreTests(PhotoRouteV2Tests):
    def test_refine_creates_isolated_version_and_preserves_source(self):
        initial = self.create_board()
        source = self.seed_analysis(initial['board']['id'])
        with patch('core.photo_route_v2.mobilesam_paths', return_value=(Path('.'), Path('weights.pt'))):
            response = self.client.post(f"/api/photo-routes/v2/boards/{source['id']}/refine", json={
                'expected_version':source['version'], 'color_group':'黄色', 'seed':[.25,.375]})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertNotEqual(result['board']['id'], source['id'])
        self.assertEqual(result['board']['board_key'], source['board_key'])
        self.assertEqual(result['board']['board_version_no'], 2)
        self.assertEqual(result['board']['status'], 'processing')
        self.assertEqual(self.store.get_board(source['id'], 'owner'), source)
        self.assertEqual(result['job']['payload']['seed'], [.25,.375])
        self.assertIn(result['job']['id'], self.jobs.enqueued)

    def test_missing_model_never_creates_fake_refinement(self):
        source = self.seed_analysis(self.create_board()['board']['id'])
        with patch.dict('os.environ', {'PHOTO_ROUTE_MOBILESAM_REPO':'', 'PHOTO_ROUTE_MOBILESAM_CHECKPOINT':''}):
            response = self.client.post(f"/api/photo-routes/v2/boards/{source['id']}/refine", json={
                'expected_version':source['version'], 'color_group':'黄色', 'seed':[.25,.375]})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(self.store.list_boards('owner')), 1)

    def test_refinement_rejects_foreign_and_stale_boards_and_invalid_seed(self):
        source = self.seed_analysis(self.create_board()['board']['id'])
        payload = {'expected_version':source['version'], 'color_group':'黄色', 'seed':[.25,.375]}
        url = f"/api/photo-routes/v2/boards/{source['id']}/refine"
        self.assertEqual(self.client.post(url, json=payload, headers={'x-test-owner':'other'}).status_code, 404)
        self.assertEqual(self.client.post(url, json={**payload, 'seed':[2,0]}).status_code, 422)
        with patch('core.photo_route_v2.mobilesam_paths', return_value=(Path('.'), Path('weights.pt'))):
            self.assertEqual(self.client.post(url, json={**payload, 'expected_version':99}).status_code, 409)


class CandidateTests(unittest.TestCase):
    def test_touching_different_colours_do_not_merge(self):
        image = np.full((600,800,3), 160, np.uint8)
        cv2.rectangle(image, (200,200), (260,260), (0,220,250), -1)
        cv2.rectangle(image, (261,200), (321,260), (220,70,20), -1)
        masks = _candidate_masks(image)
        self.assertEqual(len(masks), 2)
        self.assertFalse(any(mask[230,230] and mask[230,290] for mask in masks))

    def test_automatic_geometry_never_confirms_review_or_calibration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            photo = root/'photo.jpg'; photo.write_bytes(photo_bytes())
            with patch('core.photo_route_analysis._mobilesam_masks', return_value=None):
                result = analyze_board_photo(photo, root)
            self.assertTrue(result['objects'])
            self.assertEqual(result['calibration']['status'], 'needs_review')
            self.assertTrue(all(obj['review_status']=='needs_review' for obj in result['objects']))
            self.assertFalse(any(anchor['confirmed'] for obj in result['objects'] for anchor in obj['anchors']))


if __name__ == '__main__': unittest.main()
