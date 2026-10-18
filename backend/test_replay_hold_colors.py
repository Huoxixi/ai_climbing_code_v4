import unittest
import cv2
import numpy as np

from core.replay_hold_colors import colour_region, observe_hold_colour, region_sample_distance, sample_clicked_hold


class VideoColourRegionTests(unittest.TestCase):
    def test_clicked_component_excludes_disconnected_green_object(self):
        image=np.full((90,150,3),180,np.uint8)
        image[10:45,10:60]=[26,29,37];image[50:85,70:145]=[43,162,133]
        mask=np.zeros((90,150),np.uint8);mask[10:45,10:60]=1;mask[50:85,70:145]=1
        component,rgb,info=sample_clicked_hold(image,[mask],(30,25))
        self.assertEqual(rgb,[37,29,26])
        self.assertFalse(component[60,100])
        self.assertEqual(info['mask_index'],0)

    def test_overlap_uses_click_support_without_smallest_mask_bias(self):
        image=np.full((100,100,3),[26,29,37],np.uint8)
        larger=np.zeros((100,100),np.uint8);larger[10:90,10:90]=1
        fragment=np.zeros_like(larger);fragment[40:60,40:60]=1
        _,rgb,info=sample_clicked_hold(image,[fragment,larger],(50,50))
        self.assertEqual(info['mask_index'],1)
        self.assertEqual(rgb,[37,29,26])

    def test_conflicting_similar_overlap_stays_unresolved(self):
        image=np.full((100,100,3),[20,150,30],np.uint8)
        image[20:80,20:50]=[26,29,37]
        left=np.zeros((100,100),np.uint8);left[20:80,15:60]=1
        right=np.zeros_like(left);right[20:80,40:85]=1
        with self.assertRaisesRegex(ValueError,'重叠'):
            sample_clicked_hold(image,[left,right],(50,50))

    def test_thin_mask_keeps_region_without_area_deletion(self):
        mask=np.zeros((20,20),np.uint8);mask[8:10,4:13]=1
        image=np.full((20,20,3),[10,100,180],np.uint8)
        _,interior,info=colour_region(mask)
        self.assertTrue(info['interior_fallback'])
        self.assertEqual(int(interior.sum()),18)
        self.assertLess(region_sample_distance(image,interior,[180,100,10]),1.)

    def test_empty_or_outside_click_does_not_invent_sample(self):
        image=np.zeros((30,30,3),np.uint8);mask=np.zeros((30,30),np.uint8)
        with self.assertRaises(ValueError):sample_clicked_hold(image,[mask],(15,15))
        _,region,info=colour_region(mask)
        self.assertEqual(info['pixels'],0)
        self.assertIsNone(region_sample_distance(image,region,[0,0,0]))

    def test_warm_black_body_survives_chalk_and_orange_reflection(self):
        image=np.full((100,100,3),[26,29,37],np.uint8)
        image[10:25,10:90]=[30,90,150];image[65:80,10:90]=220
        name,_,info=observe_hold_colour(image,np.ones((100,100),np.uint8))
        self.assertEqual(name,'黑色')
        self.assertGreater(info['neutral_fractions']['黑色'],.55)

    def test_dark_chromatic_colours_are_not_black(self):
        mask=np.ones((60,60),np.uint8)
        for hsv_value in [[110,220,65],[55,220,65],[15,220,65]]:
            image=cv2.cvtColor(np.full((60,60,3),hsv_value,np.uint8),cv2.COLOR_HSV2BGR)
            self.assertNotEqual(observe_hold_colour(image,mask)[0],'黑色',hsv_value)

    def test_neutral_body_is_classified_without_chromatic_fallback(self):
        mask=np.ones((60,60),np.uint8)
        for value,name in [(30,'黑色'),(130,'灰色'),(230,'白色')]:
            self.assertEqual(observe_hold_colour(np.full((60,60,3),value,np.uint8),mask)[0],name)

    def test_boundary_mixture_does_not_gain_label_from_median_fallback(self):
        hsv=np.full((80,80,3),[5,180,200],np.uint8);hsv[:,40:]=[55,180,200]
        image=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)
        self.assertEqual(observe_hold_colour(image,np.ones((80,80),np.uint8))[0],'待确认')

    def test_yellow_hue_stays_yellow_across_shadow_without_brown_pixel_vote(self):
        hsv=np.full((80,80,3),[23,220,130],np.uint8);hsv[:,40:,2]=220
        image=cv2.cvtColor(hsv,cv2.COLOR_HSV2BGR)
        self.assertEqual(observe_hold_colour(image,np.ones((80,80),np.uint8))[0],'黄色')


if __name__=='__main__':unittest.main()
