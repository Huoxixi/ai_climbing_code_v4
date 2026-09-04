import io
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from core.photo_route_processing import (
    MAX_UPLOAD_BYTES, PhotoProcessingError, cutout, decode_photo, extract_candidates,
)
from core.photo_route_mobilesam import inspection_points, matches_route_color, separate_proposals
from core.photo_route_processing import Candidate
from scripts.evaluate_photo_routes import evaluate, result_fingerprint


def encoded(image, format="PNG", **kwargs):
    output = io.BytesIO()
    image.save(output, format=format, **kwargs)
    return output.getvalue()


class PhotoRouteProcessingTests(unittest.TestCase):
    def setUp(self):
        cv2.setNumThreads(1)
        cv2.setRNGSeed(0)

    def test_invalid_empty_oversized_and_unsupported_uploads(self):
        for data in (b"", b"invalid", b"x" * (MAX_UPLOAD_BYTES + 1), encoded(Image.new("RGB", (40, 40)), "BMP")):
            with self.subTest(length=len(data)), self.assertRaises(PhotoProcessingError):
                decode_photo(data)

    def test_pixel_limit_is_checked_before_loading_pixels(self):
        data = encoded(Image.new("RGB", (100, 100)))
        with patch("core.photo_route_processing.MAX_PIXELS", 9999), patch.object(Image.Image, "load", side_effect=AssertionError("must not decode")):
            with self.assertRaisesRegex(PhotoProcessingError, "4000"):
                decode_photo(data)

    def test_exif_orientation_is_applied_to_uploaded_photo(self):
        source = Image.new("RGB", (80, 40), "red")
        exif = source.getexif()
        exif[274] = 6
        result = decode_photo(encoded(source, "JPEG", exif=exif))
        self.assertEqual(result.shape[:2], (80, 40))

    def test_transparency_uses_white_background_and_does_not_invent_black_holds(self):
        source = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        self.assertTrue(np.all(decode_photo(encoded(source)) == 255))

    def test_animated_upload_is_rejected(self):
        source = Image.new("RGB", (40, 40), "red")
        data = encoded(source, "WEBP", save_all=True, append_images=[Image.new("RGB", (40, 40), "blue")], duration=100)
        with self.assertRaisesRegex(PhotoProcessingError, "动画"):
            decode_photo(data)

    def scene(self):
        image = np.full((300, 360, 3), 210, np.uint8)
        cv2.ellipse(image, (90, 90), (50, 35), 0, 0, 360, (220, 70, 20), -1)
        cv2.ellipse(image, (250, 210), (45, 30), 0, 0, 360, (220, 70, 20), -1)
        cv2.circle(image, (260, 75), 25, (30, 150, 30), -1)
        cv2.circle(image, (90, 90), 12, (245, 245, 245), -1)
        return image

    def test_same_color_objects_are_separate_and_chalk_inside_is_preserved(self):
        image = self.scene()
        before = image.copy()
        result = extract_candidates(image, (65 / 360, 90 / 300))
        self.assertEqual(len(result.candidates), 2)
        combined = np.maximum.reduce([c.mask for c in result.candidates])
        self.assertEqual(combined[90, 90], 255)
        self.assertEqual(combined[75, 260], 0)
        self.assertTrue(np.array_equal(image, before), "source must remain immutable")
        for candidate in result.candidates:
            rgba = cutout(result.image, candidate)
            x, y, w, h = candidate.bounds
            self.assertEqual(rgba.shape, (h, w, 4))
            self.assertTrue(np.array_equal(rgba[:, :, :3], image[y:y + h, x:x + w]))

    def test_red_hue_wrap_does_not_exclude_other_red_object(self):
        hsv = np.full((180, 240, 3), (0, 0, 210), np.uint8)
        cv2.circle(hsv, (60, 80), 25, (1, 220, 180), -1)
        cv2.circle(hsv, (180, 100), 25, (179, 220, 180), -1)
        result = extract_candidates(cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR), (.25, 80 / 180))
        self.assertEqual(len(result.candidates), 2)

    def test_background_click_requires_reselection(self):
        with self.assertRaisesRegex(PhotoProcessingError, "颜色不明显"):
            extract_candidates(self.scene(), (0, 0))

    def test_invalid_clicks_are_rejected(self):
        for seed in ((-1, .5), (.5, float("nan")), (float("inf"), .5), (1.1, .5)):
            with self.subTest(seed=seed), self.assertRaises(PhotoProcessingError):
                extract_candidates(self.scene(), seed)

    def test_cancel_and_timeout_stop_processing(self):
        with self.assertRaisesRegex(PhotoProcessingError, "取消"):
            extract_candidates(self.scene(), (.2, .3), cancelled=lambda: True)
        with self.assertRaisesRegex(PhotoProcessingError, "超过"):
            extract_candidates(self.scene(), (.2, .3), timeout_seconds=0)

    def test_disconnected_other_colors_and_duplicates_are_removed_from_model_masks(self):
        color = np.zeros((200, 200), dtype=bool)
        color[30:70, 30:70] = True
        mask = color.copy()
        mask[120:150, 120:150] = True
        proposals = [{"segmentation": mask, "predicted_iou": .95}, {"segmentation": color, "predicted_iou": .9}]
        candidates = separate_proposals(proposals, color)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].mask[130, 130], 0)
        self.assertEqual(candidates[0].mask[40, 40], 255)

    def test_nested_model_masks_preserve_only_visible_regions(self):
        volume = np.zeros((200, 200), dtype=bool)
        volume[30:120, 30:120] = True
        hold = np.zeros_like(volume)
        hold[50:80, 50:80] = True
        candidates = separate_proposals([
            {"segmentation": volume, "predicted_iou": .95},
            {"segmentation": hold, "predicted_iou": .94},
        ], volume)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(np.count_nonzero((candidates[0].mask > 0) & (candidates[1].mask > 0)), 0)
        self.assertEqual(np.count_nonzero(np.maximum.reduce([c.mask for c in candidates])), 8100)

    def test_printed_multicolor_region_is_excluded_without_dropping_chalky_hold(self):
        region = np.ones((20, 20), dtype=bool)
        saturated = np.zeros_like(region)
        saturated[:10] = True
        route_color = np.zeros_like(region)
        route_color[:8] = True
        self.assertFalse(matches_route_color(region, route_color, saturated))
        route_color[:10] = True
        self.assertTrue(matches_route_color(region, route_color, saturated))

    def test_weak_gray_pixels_cannot_mask_another_saturated_color(self):
        region = np.ones((20, 20), dtype=bool)
        saturated = np.zeros_like(region)
        saturated[:10] = True
        route_color = ~saturated
        route_color[:5] = True
        self.assertFalse(matches_route_color(region, route_color, saturated))

    def test_local_inspection_keeps_nested_gray_regions_without_scanning_wall(self):
        mask = np.zeros((200, 200), np.uint8)
        mask[40:160, 60:140] = 255
        child = np.zeros_like(mask)
        child[80:120, 80:120] = 255
        mask[child > 0] = 0
        parent = Candidate(mask, (60, 40, 80, 120), False)
        mounted = Candidate(child, (80, 80, 40, 40), False)
        before = mask.copy()
        points = inspection_points(parent, [parent, mounted], (0, 0, 200, 200))
        self.assertLess(len(points), 400)
        self.assertTrue(any(.4 < x < .6 and .4 < y < .6 for x, y in points))
        self.assertTrue(all(.3 <= x < .7 and .2 <= y < .8 for x, y in points))
        np.testing.assert_array_equal(mask, before)


class PhotoRouteEvaluationTests(unittest.TestCase):
    def fixtures(self):
        report = {"source_sha256": "sha", "algorithm": "test", "objects": [{"id": "1"}, {"id": "2"}]}
        review = {"source_sha256": "sha", "algorithm": "test", "reviewer": "test", "human_confirmed": False,
                  "target_ids": ["A", "B"], "judgments": [
                      {"candidate_id": "1", "target_ids": ["A"]},
                      {"candidate_id": "2", "target_ids": ["B"]}]}
        return report, review

    def test_unconfirmed_inventory_cannot_pass_even_with_perfect_counts(self):
        report, review = self.fixtures()
        result = evaluate(report, review)
        self.assertTrue(result["count_threshold_met"])
        self.assertFalse(result["gate_passed"])

    def test_confirmed_extra_hold_remains_a_miss_until_independently_extracted(self):
        report, review = self.fixtures()
        review["target_ids"].append("C")
        result = evaluate(report, review)
        self.assertEqual(result["unmatched_target_ids"], ["C"])
        self.assertEqual(result["reference_target_count"], 3)
        self.assertEqual(result["recall"], .6667)

    def test_duplicate_and_merged_objects_do_not_inflate_recall(self):
        report, review = self.fixtures()
        review["judgments"][1]["target_ids"] = ["A"]
        result = evaluate(report, review)
        self.assertEqual(result["recall"], .5)
        self.assertEqual(result["precision"], .5)
        self.assertEqual(result["duplicate_target_ids"], ["A"])
        review["judgments"][1]["target_ids"] = ["A", "B"]
        result = evaluate(report, review)
        self.assertEqual(result["recall"], .5)
        self.assertEqual(result["merged_candidate_ids"], ["2"])

    def test_contour_errors_block_gate_independently_of_counts(self):
        report, review = self.fixtures()
        review.update(human_confirmed=True, production_timing_verified=True)
        review["judgments"][0]["major_contour_error"] = True
        self.assertFalse(evaluate(report, review)["gate_passed"])

    def test_incomplete_or_mismatched_review_is_rejected(self):
        report, review = self.fixtures()
        review["judgments"].pop()
        with self.assertRaises(ValueError):
            evaluate(report, review)
        report, review = self.fixtures()
        review["source_sha256"] = "other-image"
        with self.assertRaises(ValueError):
            evaluate(report, review)

    def test_new_masks_cannot_reuse_review_with_same_candidate_numbers(self):
        report, review = self.fixtures()
        report["objects"][0]["mask_sha256"] = "original-mask"
        review["result_sha256"] = result_fingerprint(report)
        report["objects"][0]["mask_sha256"] = "changed-mask"
        with self.assertRaisesRegex(ValueError, "different extraction"):
            evaluate(report, review)

    def test_gate_requires_explicit_contours_and_measured_deployment_time(self):
        report, review = self.fixtures()
        for obj in report["objects"]:
            obj["mask_sha256"] = obj["id"]
        fingerprint = result_fingerprint(report)
        review.update(human_confirmed=True, production_timing_verified=True,
                      result_sha256=fingerprint)
        self.assertFalse(evaluate(report, review)["gate_passed"])
        for judgment in review["judgments"]:
            judgment["major_contour_error"] = False
        self.assertFalse(evaluate(report, review)["gate_passed"])
        review["production_measurement"] = {
            "result_sha256": fingerprint, "evidence_path": "performance.json",
            "hardware": "fixture-server", "wall_seconds": 119, "status": "completed"}
        self.assertTrue(evaluate(report, review)["gate_passed"])
        review["production_measurement"]["wall_seconds"] = 121
        self.assertFalse(evaluate(report, review)["gate_passed"])


if __name__ == "__main__":
    unittest.main()
