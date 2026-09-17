import unittest
import cv2
import numpy as np
from core.photo_route_colors import classify_mask_color

class ColorTests(unittest.TestCase):
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

    def test_unknown_version_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            classify_mask_color(np.zeros((20,20,3),np.uint8),np.ones((20,20),np.uint8),version='typo')

    def test_lab_experiment_is_deterministic_and_handles_empty_masks(self):
        hsv=np.full((80,80,3),[142,110,90],np.uint8);hsv[:,40:,0]=148
        image=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR);mask=np.full((80,80),255,np.uint8)
        for _ in range(3):
            self.assertEqual(classify_mask_color(image,mask,version='lab-interior-v1'),'紫色')
        self.assertEqual(classify_mask_color(image,np.zeros_like(mask),version='lab-interior-v1'),'待确认')
