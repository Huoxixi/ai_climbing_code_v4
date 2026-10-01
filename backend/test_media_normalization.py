import io
import unittest

from PIL import Image
from pillow_heif import register_heif_opener

from core.media_normalization import normalize_photo_bytes
from core.photo_route_processing import decode_photo


class PhonePhotoNormalizationTests(unittest.TestCase):
    def test_heic_is_decoded_on_server_as_jpeg(self):
        register_heif_opener()
        original = io.BytesIO()
        Image.new('RGB', (96, 64), (120, 30, 20)).save(original, format='HEIF')
        converted, filename, mime = normalize_photo_bytes(
            original.getvalue(), 'phone.heic', 'image/heic',
        )
        self.assertEqual((filename, mime), ('phone.jpg', 'image/jpeg'))
        self.assertEqual(Image.open(io.BytesIO(converted)).format, 'JPEG')
        self.assertEqual(decode_photo(converted).shape[:2], (64, 96))

    def test_invalid_heic_explains_the_failure(self):
        with self.assertRaisesRegex(ValueError, 'HEIC/HEIF|HEIC 照片'):
            normalize_photo_bytes(b'invalid', 'broken.heic', 'image/heic')

    def test_ordinary_photo_is_not_changed(self):
        data = b'photo bytes'
        self.assertEqual(normalize_photo_bytes(data, 'x.jpg', 'image/jpeg'),
                         (data, 'x.jpg', 'image/jpeg'))
