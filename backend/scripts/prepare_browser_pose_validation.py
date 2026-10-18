"""Create private, local browser/native comparison fixtures from a supplied clip.

Never places a video or frame in public assets. Serve fixtures only through the
local test runner. Existing input, models and saved analysis remain unchanged.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from vendor.rtmlib import RTMPose, YOLOX


def prepare(source, output, frame):
    output.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(source))
    fps = cap.get(cv2.CAP_PROP_FPS)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
    ok, image = cap.read()
    if not ok:
        raise RuntimeError('Cannot decode the requested source frame')
    h, w = image.shape[:2]
    models = ROOT / 'backend/model_assets/rtmw-l-384x288'
    detector = YOLOX(str(models/'detector.onnx'), model_input_size=(640,640), score_thr=.3, device='cpu')
    pose = RTMPose(str(models/'rtmw.onnx'), model_input_size=(288,384), device='cpu')
    boxes, scores = detector.detect_with_scores(image)
    if not len(boxes):
        raise RuntimeError('No person detected in the selected validation frame')
    box = boxes[np.argmax(scores)]
    pixels = cv2.cvtColor(image, cv2.COLOR_BGR2RGBA)
    pixels.tofile(output/'frame.rgba')
    det_input, ratio = detector.preprocess(image)
    pose_input, center, scale = pose.preprocess(image, box)
    np.asarray(det_input.transpose(2,0,1), np.float32).tofile(output/'detector-input.f32')
    np.asarray(pose_input.transpose(2,0,1), np.float32).tofile(output/'pose-input.f32')
    xy, confidence = pose(image, [box.tolist()])
    reference = dict(width=w,height=h,box=box.tolist(),boxes=boxes.tolist(),detector_scores=scores.tolist(),
                     points=(xy[0]/[w,h]).tolist(),scores=confidence[0].tolist(),
                     center=center.tolist(),scale=scale.tolist(),ratio=float(ratio),source_frame=frame,
                     native_runtime=pose.ort.__version__,native_provider=pose.session.get_providers())
    (output/'reference.json').write_text(json.dumps(reference,ensure_ascii=False,indent=2),encoding='utf-8')
    # Short lossless-in-time clip for actual file-picker -> decode -> infer tests.
    # mp4v is not supported in every browser; convert using the existing local ffmpeg.
    import imageio_ffmpeg
    import subprocess
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-y','-loglevel','error','-ss',str(frame/fps),
                    '-i',str(source),'-t','1.2','-an','-c:v','libx264','-pix_fmt','yuv420p',
                    str(output/'clip.mp4')],check=True)
    cap.release()
    print(json.dumps({'fixture_ready':True,'width':w,'height':h,'detections':len(boxes),'keypoints':len(xy[0])}))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--frame',type=int,default=315)
    args=parser.parse_args()
    prepare(args.source,args.output,args.frame)
