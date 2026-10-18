"""Local-only import preview; no replay job, inference, or original-file replacement."""
import os
from pathlib import Path
import tempfile
import threading
import uuid

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

class PreparedPreviews:
    """Short-lived owner-scoped originals and canonical copies, reused at start."""
    def __init__(self):
        self.records = {}
        self.lock = threading.RLock()

    def add(self, owner, work, *, filename, content_type, info):
        key = uuid.uuid4().hex
        timer = threading.Timer(1800, lambda: self.discard(key))
        timer.daemon = True
        with self.lock:
            self.records[key] = {'owner': owner, 'work': work, 'filename': filename,
                'content_type': content_type, 'info': info, 'timer': timer}
        timer.start()
        return key

    def take(self, key, owner):
        with self.lock:
            record = self.records.get(key)
            if record is None or record['owner'] != owner:
                raise HTTPException(404, '视频准备记录不存在或已过期，请重新导入。')
            self.records.pop(key)
            record['timer'].cancel()
            return record

    def discard(self, key, owner=None):
        with self.lock:
            record = self.records.get(key)
            if record is None:
                return
            if owner is not None and record['owner'] != owner:
                raise HTTPException(404, '未找到视频准备记录。')
            self.records.pop(key)
        record['timer'].cancel()
        record['work'].cleanup()

    def close(self):
        for key in list(self.records):
            self.discard(key)


def preview_router(store, owner, limits):
    router = APIRouter()
    prepared = getattr(store, 'prepared_previews', None) or PreparedPreviews()
    store.prepared_previews = prepared

    def require_local(request):
        owner(request)
        return (os.getenv('LOCAL_ONLY', '').lower() in {'1', 'true', 'yes'}
                and request.client is not None and request.client.host in {'127.0.0.1', '::1', 'testclient'})

    @router.get('/preview-capability')
    def capability(request: Request):
        return {'local_conversion': require_local(request)}

    @router.post('/preview-video')
    def preview(request: Request, video: UploadFile = File(...)):
        if not require_local(request):
            raise HTTPException(403, '兼容预览仅可在本机生成，视频不会发送到外部服务。')
        from .climb_replay import convert_video_to_mp4, probe_video, validate_video_upload_type
        try:
            validate_video_upload_type(video.filename or '', video.content_type or '')
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        work = tempfile.TemporaryDirectory(prefix='climb-import-preview-')
        try:
            source = Path(work.name) / 'source.mp4'
            target = Path(work.name) / 'preview.mp4'
            size = 0
            with source.open('xb') as stream:
                while chunk := video.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > limits.max_input_bytes:
                        raise HTTPException(413, '视频不能超过 500 MB。')
                    stream.write(chunk)
            if not size:
                raise HTTPException(422, '视频文件为空，请重新选择。')
            info = probe_video(source)
            # Match the analysis copy exactly: upright, silent, at most the first
            # allowed interval. Report the original duration for the existing trim UI.
            convert_video_to_mp4(source, target, limits=limits)
            canonical_info = probe_video(target)
            from .climb_replay import validate_video
            validate_video(canonical_info, limits)
            key = prepared.add(owner(request), work, filename=video.filename or 'video.mp4',
                content_type=video.content_type or 'application/octet-stream', info=canonical_info)
            return FileResponse(target, media_type='video/mp4',
                headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
                         'X-Source-Duration': str(info.duration_seconds), 'X-Prepared-Video-Id': key})
        except HTTPException:
            work.cleanup()
            raise
        except (ValueError, OSError, RuntimeError):
            work.cleanup()
            raise HTTPException(422, '本机未能生成兼容预览，请重新选择视频后重试。') from None
        finally:
            video.file.close()

    @router.delete('/preview-video/{key}')
    def discard_preview(key: str, request: Request):
        prepared.discard(key, owner(request))
        return {'discarded': True}

    return router
