"""Actual local format conversion and prepared-copy handoff; no model calls."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from core.climb_replay import (ClimbReplayStore, ClimbReplayManager, create_climb_replay_router,
    REPLAY_CONSENT_VERSION, VideoLimits, validate_video_upload_type, convert_video_to_mp4)
from core.replay_template_renderer import _ffmpeg


def make_source(root, suffix='.mp4', codec='libx264', extra=(), duration='0.4'):
    path=root/('source'+suffix)
    command=[_ffmpeg(),'-hide_banner','-loglevel','error','-f','lavfi','-i',
             f'testsrc2=size=96x128:rate=25:duration={duration}','-an','-c:v',codec,
             '-threads','1',*extra,'-y',str(path)]
    subprocess.run(command,check=True,capture_output=True)
    return path


def app_fixture(root, limits=None):
    store=ClimbReplayStore(root/'store')
    class NoInference:
        def detect_holds(self,*a,**k):raise AssertionError('Import cannot detect holds')
        def analyze(self,*a,**k):raise AssertionError('Import cannot infer poses')
    manager=ClimbReplayManager(store,NoInference())
    app=FastAPI()
    @app.middleware('http')
    async def identity(request:Request,call_next):
        username=request.headers.get('x-user','alice')
        if username!='anonymous':request.state.pilot_user=SimpleNamespace(username=username)
        return await call_next(request)
    app.include_router(create_climb_replay_router(store,manager,limits=limits))
    return TestClient(app),store,manager


class ImportPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.environment=patch.dict(os.environ,{'LOCAL_ONLY':'true'});self.environment.start()
        self.client,self.store,self.manager=app_fixture(self.root)
    def tearDown(self):
        self.manager.close();self.environment.stop();self.temp.cleanup()
    def upload(self,source):
        return self.client.post('/api/climb-replay/preview-video',files={'video':(source.name,source.read_bytes(),'application/octet-stream')})

    def test_common_containers_are_accepted_by_suffix_without_browser_mime(self):
        for suffix in ('.MP4','.mov','.mkv','.avi','.webm','.mts','.m2ts','.ts','.mpeg','.mpg','.wmv','.asf','.flv','.vob','.ogv','.mxf','.3gp','.m4v'):
            validate_video_upload_type('clip'+suffix,'application/octet-stream')
        validate_video_upload_type('clip.unknown','video/x-private-container')
        with self.assertRaises(ValueError):validate_video_upload_type('clip.exe','application/octet-stream')

    def test_real_format_matrix_becomes_same_silent_h264_yuv420p(self):
        cases=[('.mp4','libx264',()),('.mp4','libx265',('-preset','ultrafast','-x265-params','log-level=error:pools=none:frame-threads=1')),
            ('.mp4','libx265',('-pix_fmt','yuv420p10le','-preset','ultrafast','-x265-params','log-level=error:pools=none:frame-threads=1')),
            ('.mov','prores_ks',('-profile:v','2','-pix_fmt','yuv422p10le')),
            ('.mkv','ffv1',()),('.avi','mpeg4',()),('.webm','libvpx',('-deadline','realtime')),
            ('.webm','libvpx-vp9',('-deadline','realtime','-cpu-used','8')),
            ('.mts','mpeg2video',('-f','mpegts')),('.mpg','mpeg2video',()),('.wmv','wmv2',()),
            ('.flv','flv',()),('.ogv','libtheora',())]
        for index,(suffix,codec,extra) in enumerate(cases):
            with self.subTest(codec=codec,suffix=suffix,index=index):
                source=make_source(self.root,suffix,codec,extra)
                checksum=hashlib.sha256(source.read_bytes()).digest()
                response=self.upload(source)
                self.assertEqual(response.status_code,200,response.text[:100] if response.status_code!=200 else '')
                normalized=self.root/'normalized.mp4';normalized.write_bytes(response.content)
                capture=cv2.VideoCapture(str(normalized))
                self.assertTrue(capture.isOpened())
                self.assertEqual((int(capture.get(3)),int(capture.get(4))),(96,128))
                count=0
                while True:
                    okay,_=capture.read()
                    if not okay:break
                    count+=1
                capture.release();self.assertEqual(count,10)
                streams=subprocess.run([_ffmpeg(),'-hide_banner','-i',str(normalized)],capture_output=True).stderr.decode('utf8','replace')
                self.assertIn('Video: h264',streams);self.assertIn('yuv420p',streams);self.assertNotIn('Audio:',streams)
                self.assertEqual(hashlib.sha256(source.read_bytes()).digest(),checksum)
                key=response.headers['x-prepared-video-id']
                self.assertEqual(self.client.delete('/api/climb-replay/preview-video/'+key).status_code,200)
        self.assertEqual(self.store.list('alice'),[])

    def test_start_reuses_exact_copy_and_preserves_original_without_second_conversion(self):
        source=make_source(self.root,'.mov','mpeg4')
        raw=source.read_bytes()
        with patch('core.climb_replay.convert_video_to_mp4',wraps=convert_video_to_mp4) as converted:
            response=self.upload(source);self.assertEqual(response.status_code,200)
            key=response.headers['x-prepared-video-id']
            payload={'filename':source.name,'content_type':'video/quicktime','size_bytes':len(raw),
                'route_color':'green','consent_version':REPLAY_CONSENT_VERSION,'consent_granted':True}
            self.assertEqual(self.client.post(f'/api/climb-replay/prepared-videos/{key}/start',json=payload,headers={'x-user':'bob'}).status_code,404)
            with patch.object(self.manager,'enqueue') as enqueue:
                result=self.client.post(f'/api/climb-replay/prepared-videos/{key}/start',json=payload)
                self.assertEqual(result.status_code,202,result.text)
                enqueue.assert_called_once()
            self.assertEqual(converted.call_count,1)
            job=self.store.get(result.json()['id'],'alice',private=True)
            self.assertEqual(Path(job['input_path']).read_bytes(),response.content)
            self.assertEqual((self.store._path(job['id']).parent/job['high_resolution_source']['storage_name']).read_bytes(),raw)
            self.assertEqual(job['preparation']['status'],'completed')
            self.assertEqual(self.client.post(f'/api/climb-replay/prepared-videos/{key}/start',json=payload).status_code,404)

    def test_invalid_or_audio_only_files_fail_before_any_job_and_private_details(self):
        for name,data in (('bad.mp4',b'not a video'),('empty.mkv',b'')):
            response=self.client.post('/api/climb-replay/preview-video',files={'video':(name,data,'video/mp4')})
            self.assertEqual(response.status_code,422)
            self.assertNotIn(str(self.root),response.text)
        source=self.root/'audio.mp4'
        subprocess.run([_ffmpeg(),'-v','error','-f','lavfi','-i','sine=duration=0.4','-c:a','aac',str(source)],check=True,capture_output=True)
        self.assertEqual(self.upload(source).status_code,422)
        self.assertEqual(self.store.list('alice'),[])
        self.assertEqual(self.store.prepared_previews.records,{})

    def test_local_only_gate_authentication_and_discard_ownership(self):
        source=make_source(self.root)
        self.assertEqual(self.client.get('/api/climb-replay/preview-capability',headers={'x-user':'anonymous'}).status_code,401)
        with patch.dict(os.environ,{'LOCAL_ONLY':'false'}):
            self.assertFalse(self.client.get('/api/climb-replay/preview-capability').json()['local_conversion'])
            self.assertEqual(self.upload(source).status_code,403)
        response=self.upload(source);key=response.headers['x-prepared-video-id']
        self.assertEqual(self.client.delete('/api/climb-replay/preview-video/'+key,headers={'x-user':'bob'}).status_code,404)
        record=self.store.prepared_previews.records[key]
        self.assertTrue(Path(record['work'].name).is_dir())
        self.client.delete('/api/climb-replay/preview-video/'+key)
        self.assertFalse(Path(record['work'].name).exists())

    def test_input_size_limit_and_bounded_preview_keep_original_duration(self):
        from dataclasses import replace
        source=make_source(self.root,duration='1.2')
        self.manager.close()
        self.client,self.store,self.manager=app_fixture(self.root/'bounded',VideoLimits(max_duration_seconds=.4,max_frames=10))
        response=self.upload(source);self.assertEqual(response.status_code,200)
        self.assertAlmostEqual(float(response.headers['x-source-duration']),1.2,places=1)
        self.assertEqual(self.store.prepared_previews.records[response.headers['x-prepared-video-id']]['info'].frame_count,10)
        self.manager.close()
        self.client,self.store,self.manager=app_fixture(self.root/'small',VideoLimits(max_input_bytes=16))
        self.assertEqual(self.upload(source).status_code,413)


if __name__=='__main__':unittest.main()
