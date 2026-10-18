"""Full-frame RTMO observation adapter, independent of a top-down person crop.

Follows attributed rtmlib RTMO preprocessing/NMS. All person proposals and body
responses are retained, including the actual detector boxes from this model.
"""
import cv2
import numpy as np
from vendor.rtmlib.tools.base import BaseTool
from vendor.rtmlib.tools.object_detection.post_processings import multiclass_nms


class OneStagePose(BaseTool):
    def __init__(self,path,*,device='cpu'):
        super().__init__(path,(640,640),device=device)
        self.last_evidence=None
        self.last_boxes=None

    def __call__(self,frame):
        h,w=frame.shape[:2]
        ratio=min(640/h,640/w)
        image=np.full((640,640,3),114,np.uint8)
        resized=cv2.resize(frame,(int(w*ratio),int(h*ratio)))
        image[:resized.shape[0],:resized.shape[1]]=resized
        detections,poses=self.inference(image)
        boxes=detections[0,:,:4]/ratio
        det_scores=detections[0,:,4]
        _,keep=multiclass_nms(boxes,det_scores[:,None],nms_thr=.45,score_thr=.7)
        if keep is None:
            self.last_boxes=np.empty((0,4))
            return np.empty((0,17,2)),np.empty((0,17))
        self.last_boxes=boxes[keep]
        self.last_evidence={'input_size_wh':[640,640],'letterbox_ratio':ratio,
                            'source_size_wh':[w,h],'person_boxes_xyxy_px':self.last_boxes.tolist(),
                            'observation_kind':'full_frame_body17','response_semantics':'native_keypoint_response_uncalibrated'}
        return poses[0,keep,:,:2]/ratio,poses[0,keep,:,2]
