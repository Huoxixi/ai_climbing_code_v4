"""Local heatmap observation provider; no network, target selection or joint correction.

Decoding uses the attributed rtmlib DARK/UDP helper. Response and spatial spread
are diagnostics, not calibrated probabilities of anatomical correctness.
"""
import cv2
import numpy as np

from vendor.rtmlib.tools.base import BaseTool
from vendor.rtmlib.tools.pose_estimation.post_processings import post_dark_udp


class HeatmapPose(BaseTool):
    def __init__(self, path, *, device='cpu', input_size=(192, 256)):
        super().__init__(path, input_size, device=device)
        self.last_evidence = None

    def __call__(self, frame, boxes):
        results, responses = [], []
        for box in boxes:
            # Follow easy_ViTPose RGB / black aspect padding / resize / ImageNet
            # normalization. Detector margins are deliberately outside this adapter
            # so model comparisons can hold the input person context fixed.
            left, top, right, bottom = np.rint(box).astype(int)
            left, top = max(left, 0), max(top, 0)
            right, bottom = min(right, frame.shape[1]), min(bottom, frame.shape[0])
            if right <= left or bottom <= top:
                raise ValueError('Empty person context')
            raw_crop = frame[top:bottom, left:right]
            h, w = raw_crop.shape[:2]
            pad_x = max(0, int((h*.75-w)/2))
            pad_y = max(0, int((w/.75-h)/2))
            crop = cv2.copyMakeBorder(raw_crop, pad_y, pad_y, pad_x, pad_x,
                                      cv2.BORDER_CONSTANT, value=(0,0,0))
            rgb = cv2.cvtColor(cv2.resize(crop, self.model_input_size), cv2.COLOR_BGR2RGB)
            value = (rgb.astype(np.float32)/255 - [.485, .456, .406]) / [.229, .224, .225]
            heatmaps = self.inference(value)[0]
            if (heatmaps.ndim != 4 or heatmaps.shape[0] != 1
                    or heatmaps.shape[1] not in (17,133)
                    or min(heatmaps.shape[2:]) < 2 or not np.isfinite(heatmaps).all()):
                raise ValueError('Invalid native pose heatmap contract')
            n, k, hh, ww = heatmaps.shape
            flat = heatmaps.reshape(n, k, -1)
            index = flat.argmax(axis=-1)
            points = np.stack((index % ww, index // ww), axis=-1).astype(np.float32)
            response = flat.max(axis=-1)
            points = post_dark_udp(points, heatmaps.copy(), kernel=11)
            points = points / [ww-1, hh-1] * [crop.shape[1], crop.shape[0]] + [left-pad_x, top-pad_y]
            results.append(points)
            responses.append(response)
            self.last_evidence = {'crop_xyxy_px': [int(left), int(top), int(right), int(bottom)],
                                  'input_size_wh': list(self.model_input_size), 'color': 'RGB',
                                  'black_padding_xy': [pad_x, pad_y],
                                  'source_to_input_transform': [
                                      [self.model_input_size[0]/crop.shape[1],0,
                                       (pad_x-left)*self.model_input_size[0]/crop.shape[1]],
                                      [0,self.model_input_size[1]/crop.shape[0],
                                       (pad_y-top)*self.model_input_size[1]/crop.shape[0]],
                                      [0,0,1]],
                                  'decoder': 'DARK_UDP', 'response_semantics': 'heatmap_peak_uncalibrated',
                                  'location_uncertainty': 'not_calibrated'}
        return np.concatenate(results), np.concatenate(responses)
