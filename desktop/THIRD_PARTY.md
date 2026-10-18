# Third-party resources and distribution review

Python distribution metadata and original license files are retained in
`runtime/Lib/site-packages/*.dist-info`, along with `dependencies.json` and
`file-manifest.json`. CPython retains its PSF LICENSE.txt. Frontend font notices
are retained under `frontend/dist/fonts`. Noto retains the SIL OFL 1.1 notice.
Do not remove these materials when sharing a build.

* Pywebview 6.1: BSD-3-Clause, https://github.com/r0x0r/pywebview
* Python.NET / clr-loader: original distribution licenses retained.
* Torch 2.8.0+cpu and torchvision 0.23.0+cpu: original BSD notices and native
  third-party licenses retained in their packages. CPU only; no CUDA runtime.
* Detectron2: Apache-2.0, commit a2f4a877, license and corresponding native csrc
  retained with the compiled Windows cp312 CPU extension. Official source:
  https://github.com/facebookresearch/detectron2/tree/a2f4a877
* Model: Tomáš Sláma, Indoor Climbing Gym Hold And Route Segmentation,
  Kaggle dataset version 4. Source:
  https://www.kaggle.com/datasets/tomasslama/indoor-climbing-gym-hold-segmentation
  Local source metadata states CC BY-SA 4.0. The verified model is copied
  unchanged; filename changed from model_final.pth to verified-model_final.pth.
  License: https://creativecommons.org/licenses/by-sa/4.0/
  The author does not endorse this application. The research repository's
  GPL-3.0 license is distinct from the dataset metadata; redistribution approval
  must confirm that the dataset license covers this exact weight artifact.
  This preview is not evidence that all model redistribution terms are cleared.
* Imageio-ffmpeg 0.6.0 wrapper: BSD-2-Clause. Its Windows executable is FFmpeg
  7.1 with GPL components. https://github.com/imageio/imageio-ffmpeg and
  https://ffmpeg.org/legal.html . The wrapper license alone does not license
  the executable. Before public distribution, retain the GPL notices and
  provide the complete corresponding source/build materials for the exact
  executable and linked libraries, or a valid compliant source offer.
  That complete redistribution source bundle has not yet been assembled here.
* WebView2 Evergreen Runtime is an external Microsoft prerequisite, not copied
  from a development browser profile. Download/install under Microsoft's terms:
  https://learn.microsoft.com/microsoft-edge/webview2/concepts/distribution

This build is an internal desktop migration preview pending the model artifact
and FFmpeg redistribution gates. Noncommercial use does not waive these gates.

RTMW preview additions:
* ONNX Runtime DirectML 1.20.1: MIT; original package licenses retained.
  https://github.com/microsoft/onnxruntime
* rtmlib preprocessing/decoding subset: Apache-2.0; original LICENSE and
  source archive SHA-256 attribution retained under backend/vendor/rtmlib.
  https://github.com/Tau-J/rtmlib
* RTMW-L 384x288 cocktail14 20231122 and YOLOX-S HumanArt ONNX exports:
  official OpenMMLab downloads; exact filenames, size and SHA-256 fixed by
  backend/model_assets/rtmw-l-384x288/manifest.json. MMPose source is Apache-2.0:
  https://github.com/open-mmlab/mmpose . Source code license alone is not a
  separate assertion about every training dataset or weight redistribution term.
* The full FreeMoCap application is not bundled. No Aliyun pose SDK is included
  in the current desktop dependency closure; historical results need no SDK.
