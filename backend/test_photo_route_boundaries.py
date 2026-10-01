import unittest
import cv2
import numpy as np
from core.photo_route_boundaries import refine_boundary, separate_mask_components


class BoundaryTests(unittest.TestCase):
    def test_disconnected_holds_are_separate(self):
        mask=np.zeros((100,100),np.uint8)
        mask[10:30,10:30]=255; mask[60:80,60:80]=255; mask[1,1]=255
        parts=separate_mask_components(mask,45)
        self.assertEqual(len(parts),2)
        self.assertTrue(all(np.count_nonzero(part)==400 for part in parts))

    def test_original_resolution_refinement_tracks_visible_edge(self):
        image=np.full((160,200,3),190,np.uint8)
        truth=np.zeros((160,200),np.uint8); cv2.circle(truth,(100,80),30,255,-1)
        image[truth>0]=(30,80,220)
        mask=np.zeros((80,100),np.uint8); cv2.circle(mask,(50,40),16,255,-1)
        x,y,refined=refine_boundary(image,mask)
        actual=np.zeros_like(truth); actual[y:y+refined.shape[0],x:x+refined.shape[1]]=refined
        before=cv2.resize(mask,(200,160),interpolation=cv2.INTER_NEAREST)>0
        iou=lambda a: np.count_nonzero(a & (truth>0))/np.count_nonzero(a | (truth>0))
        self.assertGreater(iou(actual>0),iou(before))
        self.assertGreater(iou(actual>0),.95)

    def test_edge_crop_and_tiny_mask_stay_in_image(self):
        image=np.full((101,151,3),128,np.uint8)
        mask=np.zeros((50,75),np.uint8); mask[:2,:2]=255
        x,y,refined=refine_boundary(image,mask)
        self.assertEqual((x,y),(0,0)); self.assertGreater(np.count_nonzero(refined),0)
        self.assertLessEqual(refined.shape[0],101); self.assertLessEqual(refined.shape[1],151)
