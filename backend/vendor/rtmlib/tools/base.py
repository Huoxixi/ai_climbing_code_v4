"""Local ONNX adapter for the attributed rtmlib inference helpers.

No URL resolution, weight download, network API or global session monkeypatch.
"""
from pathlib import Path

import numpy as np


class BaseTool:
    def __init__(self, onnx_model, model_input_size=None, mean=None, std=None,
                 backend='onnxruntime', device='cpu'):
        if backend != 'onnxruntime' or device not in {'cpu', 'dml', 'auto'}:
            raise ValueError('Local replay supports CPU or DirectML ONNX only')
        if not Path(onnx_model).is_file():
            raise FileNotFoundError('Local ONNX model is missing')
        import onnxruntime as ort
        ort.disable_telemetry_events()
        self.ort = ort
        self.onnx_model = str(onnx_model)
        self.model_input_size = model_input_size
        self.mean, self.std = mean, std
        self.backend, self.device = backend, device
        self.fallback_reason = None
        available = ort.get_available_providers()
        providers = (['DmlExecutionProvider', 'CPUExecutionProvider']
                     if device != 'cpu' and 'DmlExecutionProvider' in available
                     else ['CPUExecutionProvider'])
        if device == 'dml' and 'DmlExecutionProvider' not in available:
            self.fallback_reason = 'directml_unavailable'
        try:
            self.session = self._session(providers)
        except Exception as exc:
            if providers == ['CPUExecutionProvider']:
                raise
            self.fallback_reason = 'directml_init_' + type(exc).__name__
            self.session = self._session(['CPUExecutionProvider'])

    def _session(self, providers):
        options = self.ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        options.enable_mem_pattern = 'DmlExecutionProvider' not in providers
        options.execution_mode = self.ort.ExecutionMode.ORT_SEQUENTIAL
        options.log_severity_level = 3
        return self.ort.InferenceSession(self.onnx_model, sess_options=options,
                                        providers=providers)

    def inference(self, img):
        value = np.ascontiguousarray(img.transpose(2, 0, 1), dtype=np.float32)[None]
        try:
            return self.session.run(None, {self.session.get_inputs()[0].name: value})
        except Exception as exc:
            if 'DmlExecutionProvider' not in self.session.get_providers():
                raise
            # A local CPU fallback is allowed; there is no cloud fallback.
            self.fallback_reason = 'directml_run_' + type(exc).__name__
            self.session = self._session(['CPUExecutionProvider'])
            return self.session.run(None, {self.session.get_inputs()[0].name: value})
