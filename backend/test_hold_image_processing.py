import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi.testclient import TestClient

import main
from core.hold_image_processing import (
    HoldImageProcessingError,
    process_hold_image_bytes,
    processed_filename_for,
    resolve_local_hold_image_url,
)


def encode_image(image: np.ndarray, suffix: str = ".png") -> bytes:
    success, buffer = cv2.imencode(suffix, image)
    if not success:
        raise AssertionError("test image encoding failed")
    return buffer.tobytes()


def decode_png(image_bytes: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise AssertionError("processed PNG decoding failed")
    return image


def white_background_hold(width: int = 240, height: int = 180) -> np.ndarray:
    image = np.full((height, width, 3), (248, 249, 247), dtype=np.uint8)
    cv2.ellipse(image, (120, 92), (72, 48), -8, 0, 360, (170, 170, 170), -1)
    cv2.ellipse(image, (120, 84), (72, 48), -8, 0, 360, (20, 45, 25), 5, cv2.LINE_AA)
    cv2.ellipse(image, (120, 84), (65, 41), -8, 0, 360, (48, 158, 74), -1, cv2.LINE_AA)
    cv2.circle(image, (120, 84), 11, (24, 28, 25), -1, cv2.LINE_AA)
    cv2.circle(image, (120, 84), 5, (190, 198, 192), -1, cv2.LINE_AA)
    cv2.ellipse(image, (104, 68), (25, 9), -18, 0, 360, (220, 234, 221), -1, cv2.LINE_AA)
    return image


class HoldImageProcessingTest(unittest.TestCase):
    def test_white_background_becomes_soft_transparency_without_shadow(self):
        source = white_background_hold()
        output = decode_png(process_hold_image_bytes(encode_image(source)))
        alpha = output[:, :, 3]

        self.assertEqual(output.shape[2], 4)
        self.assertEqual(int(alpha[0, 0]), 0)
        self.assertGreater(int(np.count_nonzero(alpha == 255)), 1000)
        self.assertGreater(int(np.count_nonzero((alpha > 0) & (alpha < 255))), 20)
        self.assertLess(float(np.mean(alpha[-8:, :])), 2.0)

        visible = output[:, :, :3][alpha > 245]
        self.assertGreater(float(visible[:, 1].mean()), float(visible[:, 0].mean()))
        edge = output[:, :, :3][(alpha > 20) & (alpha < 220)]
        self.assertLess(float(edge.mean()), 235.0)

    def test_light_hold_interior_is_preserved_by_dark_outline(self):
        source = np.full((160, 220, 3), 250, dtype=np.uint8)
        cv2.ellipse(source, (110, 80), (70, 42), 0, 0, 360, (30, 30, 30), 6, cv2.LINE_AA)
        cv2.ellipse(source, (110, 80), (64, 36), 0, 0, 360, (226, 231, 224), -1, cv2.LINE_AA)

        output = decode_png(process_hold_image_bytes(encode_image(source)))
        alpha = output[:, :, 3]
        center_y, center_x = output.shape[0] // 2, output.shape[1] // 2
        self.assertGreater(int(alpha[center_y, center_x]), 245)
        self.assertGreater(int(output[center_y, center_x, :3].mean()), 205)

    def test_existing_transparency_is_preserved_without_resegmentation(self):
        source = np.zeros((100, 140, 4), dtype=np.uint8)
        cv2.rectangle(source, (25, 20), (115, 80), (35, 145, 210, 192), -1)
        cv2.circle(source, (70, 50), 18, (255, 255, 255, 255), -1)

        output = decode_png(process_hold_image_bytes(encode_image(source)))
        alpha = output[:, :, 3]
        self.assertIn(192, np.unique(alpha))
        self.assertEqual(int(alpha[0, 0]), 0)
        self.assertGreater(int(alpha[output.shape[0] // 2, output.shape[1] // 2]), 250)

    def test_non_white_background_is_rejected(self):
        source = np.full((120, 160, 3), (130, 80, 40), dtype=np.uint8)
        cv2.circle(source, (80, 60), 32, (40, 180, 70), -1)
        with self.assertRaises(HoldImageProcessingError):
            process_hold_image_bytes(encode_image(source))

    def test_local_url_resolver_reuses_versioned_png_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            output_dir = root / "processed"
            source_dir.mkdir()
            source_path = source_dir / "sample.jpg"
            source_path.write_bytes(encode_image(white_background_hold(), ".jpg"))

            first = resolve_local_hold_image_url("/images/sample.jpg", source_dir, output_dir)
            output_path = output_dir / processed_filename_for(source_path.name)
            first_mtime = output_path.stat().st_mtime_ns
            second = resolve_local_hold_image_url("/images/sample.jpg", source_dir, output_dir)

            self.assertEqual(first, "/images/processed/sample_cutout_v4.png")
            self.assertEqual(second, first)
            self.assertEqual(output_path.stat().st_mtime_ns, first_mtime)

    def test_processed_url_rebuilds_missing_ignored_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_dir = root / "source"
            output_dir = root / "processed"
            source_dir.mkdir()
            source_path = source_dir / "sample.jpg"
            source_path.write_bytes(encode_image(white_background_hold(), ".jpg"))

            resolved = resolve_local_hold_image_url(
                "/images/processed/sample_cutout_v4.png",
                source_dir,
                output_dir,
            )

            self.assertEqual(resolved, "/images/processed/sample_cutout_v4.png")
            self.assertTrue((output_dir / "sample_cutout_v4.png").is_file())


class LocalHoldUploadTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_jpeg_upload_preserves_original_and_returns_processed_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            images_dir = root / "images"
            processed_dir = root / "processed"
            mapping_path = root / "holds_mapping.json"
            vectors_path = root / "holds_vectors.json"
            image_bytes = encode_image(white_background_hold(), ".jpg")

            with (
                patch("main.HOLDS_IMAGES_DIR", str(images_dir)),
                patch("main.PROCESSED_HOLDS_IMAGES_DIR", str(processed_dir)),
                patch("main.HOLDS_MAPPING_FILE", str(mapping_path)),
                patch("main.HOLDS_VECTORS_FILE", str(vectors_path)),
                patch("main.HOLDS_METADATA_FILE", str(root / "hold_assets_meta.json")),
                patch("main.should_use_supabase", return_value=False),
            ):
                response = self.client.post(
                    "/api/holds/upload",
                    data={"hold_type": "Jug", "variant": "local-jpeg"},
                    files={"file": ("hold.jpg", image_bytes, "image/jpeg")},
                )
                mapping_response = self.client.get("/api/holds/mapping")

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["background_removed"])
            self.assertEqual(payload["processing_version"], "cutout_v4")
            self.assertTrue(payload["image_path"].startswith("/images/processed/"))
            self.assertEqual(len(list(images_dir.glob("*.jpg"))), 1)
            self.assertEqual(len(list(processed_dir.glob("*_cutout_v4.png"))), 1)
            self.assertEqual(
                mapping_response.json()["Jug"]["local-jpeg"],
                payload["image_path"],
            )
            stored_mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
            self.assertEqual(stored_mapping["Jug"]["local-jpeg"], payload["image_path"])

    def test_failed_cutout_does_not_write_files_or_mapping(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            images_dir = root / "images"
            processed_dir = root / "processed"
            mapping_path = root / "holds_mapping.json"
            vectors_path = root / "holds_vectors.json"
            source = np.full((120, 160, 3), (140, 80, 35), dtype=np.uint8)
            image_bytes = encode_image(source, ".jpg")

            with (
                patch("main.HOLDS_IMAGES_DIR", str(images_dir)),
                patch("main.PROCESSED_HOLDS_IMAGES_DIR", str(processed_dir)),
                patch("main.HOLDS_MAPPING_FILE", str(mapping_path)),
                patch("main.HOLDS_VECTORS_FILE", str(vectors_path)),
                patch("main.HOLDS_METADATA_FILE", str(root / "hold_assets_meta.json")),
                patch("main.should_use_supabase", return_value=False),
            ):
                response = self.client.post(
                    "/api/holds/upload",
                    data={"hold_type": "Jug", "variant": "bad-background"},
                    files={"file": ("hold.jpg", image_bytes, "image/jpeg")},
                )

            self.assertEqual(response.status_code, 422)
            self.assertFalse(mapping_path.exists())
            self.assertFalse(images_dir.exists())
            self.assertFalse(processed_dir.exists())


if __name__ == "__main__":
    unittest.main()
