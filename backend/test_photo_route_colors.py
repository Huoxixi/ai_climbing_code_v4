import unittest
import cv2
import numpy as np
from core.photo_route_colors import COLOR_SWATCHES, ROUTE_COLOR_NAMES, TWELVE_COLOR_VERSION, classify_mask_color, lab_color_name, mask_sample_distance

class ColorTests(unittest.TestCase):
    def test_route_palette_has_twelve_unique_supported_colours(self):
        self.assertEqual(len(ROUTE_COLOR_NAMES), 12)
        self.assertEqual(len(set(ROUTE_COLOR_NAMES)), 12)
        self.assertIn('青色', ROUTE_COLOR_NAMES)
        self.assertIn('棕色', ROUTE_COLOR_NAMES)
        self.assertNotIn('待确认', ROUTE_COLOR_NAMES)
        self.assertTrue(all(COLOR_SWATCHES[name].startswith('#') for name in ROUTE_COLOR_NAMES))

    def test_blue_not_purple_with_chalk_shadow_and_wall(self):
        image=np.full((120,120,3),180,np.uint8);mask=np.zeros((120,120),np.uint8)
        mask[15:105,15:105]=255;image[15:105,15:105]=[200,70,30]
        image[20:50,20:100]=240;image[70:95,20:100]=15
        self.assertEqual(classify_mask_color(image,mask),'蓝色')
    def test_ambiguous_neutral_is_unconfirmed(self):
        self.assertEqual(classify_mask_color(np.full((80,80,3),220,np.uint8),np.full((80,80),255,np.uint8)),'待确认')
    def test_mixed_colors_need_confirmation(self):
        image=np.full((80,80,3),[190,70,30],np.uint8);image[:,40:]=[30,40,200]
        self.assertEqual(classify_mask_color(image,np.full((80,80),255,np.uint8)),'待确认')

    def test_dark_magenta_is_purple_and_bright_pink_stays_pink(self):
        mask=np.full((80,80),255,np.uint8)
        for value,expected in [(120,'紫色'),(230,'粉色')]:
            hsv=np.full((80,80,3),[155,150,value],np.uint8)
            self.assertEqual(classify_mask_color(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),mask),expected)

    def test_dark_purple_across_hue_boundary_votes_together(self):
        hsv=np.full((80,80,3),[142,110,90],np.uint8); hsv[:,40:,0]=148
        image=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR); mask=np.full((80,80),255,np.uint8)
        self.assertEqual(classify_mask_color(image,mask),'待确认')
        self.assertEqual(classify_mask_color(image,mask,version='interior-v4'),'紫色')

    def test_candidate_keeps_bright_pink_and_rejects_mixed_objects(self):
        hsv=np.full((80,80,3),[155,150,230],np.uint8); mask=np.full((80,80),255,np.uint8)
        self.assertEqual(classify_mask_color(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),mask,version='interior-v4'),'粉色')
        hsv[:,40:]=[100,150,180]
        self.assertEqual(classify_mask_color(cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR),mask,version='interior-v4'),'待确认')

    def test_candidate_distinguishes_cyan_and_brown(self):
        mask=np.full((80,80),255,np.uint8)
        for hsv_value,expected in [([90,170,190],'青色'),([15,170,120],'棕色')]:
            hsv=np.full((80,80,3),hsv_value,np.uint8)
            image=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)
            self.assertEqual(classify_mask_color(image,mask,version=TWELVE_COLOR_VERSION),expected)

    def test_twelve_colour_version_does_not_change_legacy_v4_labels(self):
        mask=np.full((80,80),255,np.uint8)
        cyan=cv2.cvtColor(np.full((80,80,3),[90,170,190],np.uint8),cv2.COLOR_HSV2BGR)
        brown=cv2.cvtColor(np.full((80,80,3),[15,170,120],np.uint8),cv2.COLOR_HSV2BGR)
        self.assertEqual(classify_mask_color(cyan,mask,version='interior-v4'),'蓝色')
        self.assertEqual(classify_mask_color(brown,mask,version='interior-v4'),'橙色')

    def test_twelve_colour_lab_fallback_supports_cyan_and_brown(self):
        for hsv_value,expected in [([90,170,190],'青色'),([15,170,120],'棕色')]:
            bgr=cv2.cvtColor(np.uint8([[hsv_value]]),cv2.COLOR_HSV2BGR)
            lab=cv2.cvtColor(bgr,cv2.COLOR_BGR2LAB)[0,0]
            self.assertEqual(lab_color_name(lab,twelve_colors=True),expected)

    def test_picked_rgb_sample_uses_mask_interior_lab_distance(self):
        image=np.full((80,80,3),[40,170,190],np.uint8)
        mask=np.full((80,80),255,np.uint8)
        rgb=cv2.cvtColor(np.uint8([[[40,170,190]]]),cv2.COLOR_BGR2RGB)[0,0].tolist()
        self.assertLess(mask_sample_distance(image,mask,rgb),1)
        self.assertGreater(mask_sample_distance(image,mask,[20,40,210]),30)

    def test_unknown_version_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            classify_mask_color(np.zeros((20,20,3),np.uint8),np.ones((20,20),np.uint8),version='typo')

    def test_lab_experiment_is_deterministic_and_handles_empty_masks(self):
        hsv=np.full((80,80,3),[142,110,90],np.uint8);hsv[:,40:,0]=148
        image=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR);mask=np.full((80,80),255,np.uint8)
        for _ in range(3):
            self.assertEqual(classify_mask_color(image,mask,version='lab-interior-v1'),'紫色')
        self.assertEqual(classify_mask_color(image,np.zeros_like(mask),version='lab-interior-v1'),'待确认')
