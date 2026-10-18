"""Public synthetic test pattern; contains no real person or private video."""
import argparse
import json
from pathlib import Path
import subprocess

parser=argparse.ArgumentParser()
parser.add_argument('destination',type=Path)
parser.add_argument('--ffmpeg',default='ffmpeg')
args=parser.parse_args()
args.destination.mkdir(parents=True,exist_ok=True)
subprocess.run([args.ffmpeg,'-nostdin','-v','error','-y','-f','lavfi','-i',
                'color=c=gray:s=720x1280:r=30:d=1.2','-c:v','libx264',
                '-pix_fmt','yuv420p','-movflags','+faststart',str(args.destination/'clip.mp4')],check=True)
points=[[.5,.2],[.475,.19],[.525,.19],[.45,.2],[.55,.2],
        [.4,.3],[.6,.3],[.32,.42],[.68,.42],[.26,.3],[.74,.3],
        [.43,.55],[.57,.55],[.36,.72],[.64,.72],[.32,.9],[.68,.9]]
(args.destination/'reference.json').write_text(json.dumps({
    'fixture_kind':'synthetic-display-only-not-model-ground-truth','width':720,'height':1280,
    'points':points,'scores':[.99]*17}),encoding='utf-8')
