"""Serialize local photo inference across threads and worker processes."""
import functools
import os
import tempfile
import threading
import time
from pathlib import Path

_thread_lock=threading.Lock()

def serialized_inference(fn):
    @functools.wraps(fn)
    def run(*args, **kwargs):
        cancelled=kwargs.get('cancelled') or (lambda:False)
        progress=kwargs.get('progress') or (lambda stage,value:None)
        duration=max(.1,kwargs['deadline']-time.monotonic()) if kwargs.get('deadline') else None
        progress('等待全局识别队列',0)
        while not _thread_lock.acquire(timeout=.2):
            if cancelled(): raise InterruptedError('任务已取消')
        try:
            with (Path(tempfile.gettempdir())/'ai-climbing-photo-inference.lock').open('a+b') as handle:
                if handle.seek(0,2)==0: handle.write(b'0'); handle.flush()
                while True:
                    if cancelled(): raise InterruptedError('任务已取消')
                    try:
                        handle.seek(0)
                        if os.name=='nt':
                            import msvcrt
                            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                        else:
                            import fcntl
                            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        break
                    except (BlockingIOError,OSError): time.sleep(.2)
                try:
                    if duration is not None: kwargs['deadline']=time.monotonic()+duration
                    return fn(*args,**kwargs)
                finally:
                    handle.seek(0)
                    if os.name=='nt': msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                    else: fcntl.flock(handle,fcntl.LOCK_UN)
        finally: _thread_lock.release()
    return run
