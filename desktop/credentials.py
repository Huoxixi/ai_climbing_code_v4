"""Current-Windows-user DPAPI credentials; no plaintext file or returned keys."""
import ctypes
from ctypes import wintypes
import json
import os
import uuid

KEYS = {"ALIBABA_CLOUD_ACCESS_KEY_ID", "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
        "DASHSCOPE_API_KEY"}


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data, decrypt=False):
    if os.name != "nt":
        raise RuntimeError("云配置仅支持 Windows 当前用户加密。")
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    library = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    method = library.CryptUnprotectData if decrypt else library.CryptProtectData
    method.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    method.restype = wintypes.BOOL
    if not method(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise RuntimeError("无法读取或保存当前用户云配置。")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def load(config):
    path = config / "cloud.dpapi"
    if not path.is_file():
        return {}
    try:
        value = json.loads(crypt(path.read_bytes(), decrypt=True))
        return {key: val for key, val in value.items() if key in KEYS and isinstance(val, str)}
    except Exception:
        raise RuntimeError("当前 Windows 用户无法解密云配置，请在设置中重新保存。") from None


def save(config, values):
    if set(values) - KEYS or any(not isinstance(v, str) or len(v) > 512 for v in values.values()):
        raise ValueError("请输入有效的云服务配置。")
    values = {key: value.strip() for key, value in values.items()}
    if bool(values.get("ALIBABA_CLOUD_ACCESS_KEY_ID")) != bool(values.get("ALIBABA_CLOUD_ACCESS_KEY_SECRET")):
        raise ValueError("阿里云 AccessKey ID 与 Secret 需要一起填写。")
    # The current form updates only Bailian. Keep historical encrypted entries.
    if 'DASHSCOPE_API_KEY' in values and not ({'ALIBABA_CLOUD_ACCESS_KEY_ID', 'ALIBABA_CLOUD_ACCESS_KEY_SECRET'} & values.keys()):
        values = {**load(config), **values}
    config.mkdir(parents=True, exist_ok=True)
    temporary = config / (uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(crypt(json.dumps(values).encode()))
        os.replace(temporary, config / "cloud.dpapi")
    finally:
        temporary.unlink(missing_ok=True)
