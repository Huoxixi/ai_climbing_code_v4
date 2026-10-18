"""One local editor model, evicted after two idle minutes. No photo defaults change."""
import hashlib
import threading

_lock = threading.RLock()
_entry = None
_timer = None


def release_local_model():
    global _entry, _timer
    with _lock:
        _entry = None
        if _timer:
            _timer.cancel()
            _timer = None


def cached_local_model(identity, load, checkpoint):
    global _entry, _timer
    with _lock:
        if _timer:
            _timer.cancel()
        if _entry is None or _entry[0] != identity:
            _entry = None
            model = load()
            digest = hashlib.sha256()
            with checkpoint.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            _entry = (identity, model, digest.hexdigest()[:12])
        _timer = threading.Timer(120, release_local_model)
        _timer.daemon = True
        _timer.start()
        return _entry[1], _entry[2]
