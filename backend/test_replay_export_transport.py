import io
import json
import unittest
import zipfile
import tempfile
from pathlib import Path
import cv2
import numpy as np
import httpx
from core.replay_vision_provider import CompatibleVisionProvider, VisionAPIError
from core.replay_vision_settings import VisionSettings
from core.replay_export import build_bundle
from test_replay_segments_and_analysis_view import scene


class TransportTests(unittest.TestCase):
    def request(self, mode, body, status=200):
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(status, json=body)
        cfg = {'base_url': 'https://api.openai.com/v1', 'api_key': 'fake-secret',
               'model': 'gpt-6-sol', 'api_mode': mode}
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            result = CompatibleVisionProvider(cfg, client)(messages=[{'role': 'system', 'content': '输出 JSON'},
                {'role': 'user', 'content': [{'type': 'text', 'text': '{"time_seconds":1,"degrees":90}'},
                    {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,ZmFrZQ=='}}]}],
                max_tokens=1800, cancelled=lambda: False)
        return calls, result

    def test_responses_maps_frames_data_output_and_billing(self):
        body = {'id': 'r1', 'output': [{'type': 'reasoning'}, {'type': 'message',
            'content': [{'type': 'output_text', 'text': '{"comments":[]}'}]}],
            'usage': {'input_tokens': 123, 'output_tokens': 40}}
        calls, result = self.request('auto', body)
        payload = json.loads(calls[0].content)
        self.assertEqual(str(calls[0].url), 'https://api.openai.com/v1/responses')
        self.assertEqual(payload['model'], 'gpt-6-sol')
        self.assertEqual(payload['input'][1]['content'][1]['type'], 'input_image')
        self.assertEqual(result['content'], '{"comments":[]}')
        self.assertEqual(result['usage']['prompt_tokens'], 123)
        self.assertEqual(result['raw_response'], body)
        self.assertFalse(payload['store'])

    def test_chat_uses_supported_token_field_and_json_output(self):
        calls, result = self.request('chat_completions', {'choices': [{'message': {'content': '{"comments":[]}'}}]})
        payload = json.loads(calls[0].content)
        self.assertIn('max_completion_tokens', payload)
        self.assertNotIn('max_tokens', payload)
        self.assertEqual(payload['messages'][1]['content'][1]['type'], 'image_url')
        self.assertEqual(payload['response_format']['type'], 'json_object')

    def test_incomplete_response_is_retained_for_local_recovery(self):
        body = {'status': 'incomplete', 'output': [], 'usage': {'input_tokens': 2, 'output_tokens': 1800}}
        calls, result = self.request('responses', body)
        self.assertEqual(result['raw_response'], body)
        self.assertEqual(result['content'], '')
        self.assertEqual(len(calls), 1)

    def test_errors_do_not_echo_secrets_or_retry(self):
        with self.assertRaises(VisionAPIError) as error:
            self.request('responses', {'error': {'message': 'fake-secret'}}, 400)
        self.assertIn('HTTP 400', str(error.exception))
        self.assertNotIn('fake-secret', str(error.exception))

    def test_endpoint_suffix_normalized(self):
        for ending in ('/responses', '/chat/completions'):
            self.assertEqual(VisionSettings(base_url='https://api.openai.com/v1' + ending).base_url,
                             'https://api.openai.com/v1')
        self.assertEqual(VisionSettings(base_url='https://gateway.invalid/v1/responses').api_mode, 'responses')

    def test_successful_http_with_unreadable_body_is_not_safe_to_resend(self):
        def handle(request):return httpx.Response(200,text='unreadable return')
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            provider=CompatibleVisionProvider({'base_url':'https://gateway.invalid/v1','model':'test','api_key':'fake'},client)
            with self.assertRaises(VisionAPIError) as error:
                provider(messages=[{'role':'user','content':'test'}],max_tokens=20,cancelled=lambda:False)
        self.assertTrue(error.exception.uncertain)


class ExportTests(unittest.TestCase):
    def test_cited_original_frames_are_excluded_from_materials(self):
        result=scene()
        result['ai_analysis']={'actions':[{'evidence':[{'frame_id':'frame-3','time_seconds':.75}]}]}
        with tempfile.TemporaryDirectory() as folder:
            video=Path(folder)/'source.mp4'
            writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),4,(96,64))
            for _ in range(8):writer.write(np.zeros((64,96,3),np.uint8))
            writer.release()
            stream=build_bundle(result,mapping=None,source_path=video)
            try:
                with zipfile.ZipFile(stream) as bundle:
                    self.assertFalse(any(name.startswith('evidence_frames/') for name in bundle.namelist()))
                    self.assertNotIn('source.mp4',bundle.namelist())
            finally:stream.close()

    def test_data_only_contains_full_pose_angles_missingness_and_prompt(self):
        result = scene()
        result['pose_samples'][0]['kpts_score'][7] = .1
        result['source_duration_seconds'] = 2
        stream = build_bundle(result, mapping=None)
        self.addCleanup(stream.close)
        with zipfile.ZipFile(stream) as bundle:
            self.assertNotIn('replay.mp4', bundle.namelist())
            data = json.loads(bundle.read('analysis.json'))
            self.assertEqual(data['pose_samples'], result['pose_samples'])
            self.assertEqual(data['center_of_mass_trajectory']['segments'], result['center_of_mass_trajectory']['segments'])
            self.assertNotIn('version',data['center_of_mass_trajectory'])
            poses = bundle.read('pose_samples.csv').decode('utf-8-sig')
            self.assertIn('0,0,left_elbow,,,0.1,False,reference', poses)
            angles = bundle.read('joint_angles.csv').decode('utf-8-sig')
            self.assertIn('left_knee', angles)
            self.assertIn('torso_lean_from_vertical', angles)
            self.assertNotIn('0,frame-0,left_elbow', angles)
            self.assertIn('二维', bundle.read('prompt_constraints.txt').decode())
            manifest = json.loads(bundle.read('manifest.json'))
            self.assertEqual(set(manifest['files']), set(bundle.namelist()))

    def test_selected_video_has_time_mapping_without_original_or_frames(self):
        result = scene()
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / 'source.mp4'
            writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), 4, (96, 64))
            for _ in range(8):
                writer.write(np.full((64,96,3), 110, dtype=np.uint8))
            writer.release()
            mapping = {'source_start_seconds': .5, 'speed': .75,
                'formula': 'analysis_time_seconds = source_start_seconds + replay_time_seconds * speed'}
            stream = build_bundle(result, mapping=mapping, source_path=video, video_path=video)
            try:
                with zipfile.ZipFile(stream) as bundle:
                    self.assertNotIn('source.mp4',bundle.namelist())
                    self.assertEqual(bundle.read('replay.mp4'), video.read_bytes())
                    self.assertFalse(any(name.startswith('evidence_frames/') for name in bundle.namelist()))
                    manifest = json.loads(bundle.read('manifest.json'))
                    self.assertEqual(manifest['video_time_mapping'], mapping)
            finally:
                stream.close()

    def test_route_requires_owner_and_supports_commentary_without_video(self):
        import test_replay_actions as lifecycle
        fixture = lifecycle.ActionLifecycleTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.client.post(fixture.url, json={})
        state = fixture.wait()
        self.assertEqual(state['task']['status'], 'succeeded')
        path = fixture.url + '/package'
        query = {'version': state['result_version'], 'data_only': True}
        response = fixture.client.get(path, params=query)
        self.assertEqual(response.status_code, 200, response.text[:100] if response.status_code != 200 else '')
        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
            self.assertIn('joint_angles.csv', bundle.namelist())
        self.assertEqual(fixture.client.get(path, params={**query, 'version': 'stale'}).status_code, 409)


if __name__ == '__main__':
    unittest.main()
