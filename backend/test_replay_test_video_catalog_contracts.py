"""Catalog configuration contracts through unchanged read route entry points."""
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import APIRouter

from core import climb_replay as replay


class ReplayTestVideoCatalogContractsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.first = self.root / 'first.MP4'
        self.second = self.root / 'second.mp4'
        self.first.write_bytes(b'first-video')
        self.second.write_bytes(b'second-video')
        self.request = SimpleNamespace(state=SimpleNamespace(pilot_user=SimpleNamespace(username='alice')))

    def router(self, *, events=None, **options):
        events = events if events is not None else []
        self.last_manager = SimpleNamespace()
        with ExitStack() as patches:
            for name, target, is_router in (
                ('coaching', 'core.replay_coaching.CoachingManager', False),
                ('coaching-router', 'core.replay_coaching.coaching_router', True),
                ('template', 'core.replay_template.TemplateVideoManager', False),
                ('template-router', 'core.replay_template.template_router', True),
                ('actions', 'core.replay_action_jobs.ActionManager', False),
                ('action-router', 'core.replay_action_jobs.action_router', True),
                ('chunks', 'core.climb_replay.ChunkUploadStore', False),
                ('preview-router', 'core.replay_preview.preview_router', True),
            ):
                def construct(*args, _name=name, _router=is_router, **kwargs):
                    events.append(_name)
                    return APIRouter() if _router else SimpleNamespace()
                patches.enter_context(patch(target, side_effect=construct))
            return replay.create_climb_replay_router(
                SimpleNamespace(root=self.root / 'store'), self.last_manager, **options)

    def endpoint(self, router, suffix):
        return next(route.endpoint for route in router.routes
                    if getattr(route, 'path', None) == '/api/climb-replay' + suffix)

    def items(self, router):
        return self.endpoint(router, '/test-videos')(self.request)['items']

    def test_catalog_import_does_not_initialize_replay_services(self):
        script = (
            'import core.replay_test_videos; import sys; '
            'assert not any(name in sys.modules for name in '
            '("core.climb_replay", "core.replay_coaching", "core.replay_template", "core.replay_action_jobs"))'
        )
        completed = subprocess.run([sys.executable, '-B', '-c', script],
                                   capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_filtering_keeps_original_index_defaults_whitespace_and_source_reference(self):
        source = {'reference': 'original'}
        cases = [
            {'id': '../invalid', 'path': self.first},
            {'id': '   ', 'path': self.first},
            {'id': 'without-path'},
            {'path': self.first},
            {'id': ' 案例_甲-1 ', 'path': self.second, 'label': ' custom ', 'description': '   ',
             'source_url': source, 'comparison_action_count': '-2', 'comparison_route_color': ' 蓝色 '},
        ]
        items = self.items(self.router(test_video_cases=cases))
        self.assertEqual([item['id'] for item in items], ['case-4', '案例_甲-1'])
        self.assertEqual(items[0], {
            'id': 'case-4', 'label': '本地案例 4', 'description': '本地验收素材',
            'filename': 'first.MP4', 'size_bytes': 11, 'comparison_available': False,
            'comparison_route_color': None, 'comparison_action_count': None,
            'source_url': None, 'usage': 'local_acceptance_only',
        })
        self.assertEqual((items[1]['label'], items[1]['description']), ('custom', ''))
        self.assertEqual((items[1]['comparison_action_count'], items[1]['comparison_route_color']), (-2, '蓝色'))
        self.assertIs(items[1]['source_url'], source)
        self.assertEqual(cases[3], {'path': self.first})

    def test_duplicate_ids_keep_configuration_order_and_first_available_selection(self):
        router = self.router(test_video_cases=[
            {'id': 'same', 'path': self.first, 'label': 'first'},
            {'id': 'same', 'path': self.second, 'label': 'second'},
        ])
        self.assertEqual([item['label'] for item in self.items(router)], ['first', 'second'])
        endpoint = self.endpoint(router, '/test-videos/{case_id}')
        self.assertEqual(endpoint('same', self.request).path, self.first.resolve())
        self.first.unlink()
        self.assertEqual(endpoint('same', self.request).path, self.second.resolve())

    def test_fallback_is_used_only_when_every_case_was_filtered_out(self):
        source = {'reference': 'fallback'}
        router = self.router(
            test_video_cases=[{'id': '/bad', 'path': self.second}, {'id': 'missing-path'}],
            test_video_path=self.first, test_video_source_url=source,
        )
        items = self.items(router)
        self.assertEqual([item['id'] for item in items], ['case-1'])
        self.assertEqual(items[0]['filename'], 'first.MP4')
        self.assertIs(items[0]['source_url'], source)

    def test_configured_unavailable_case_blocks_fallback_and_is_checked_on_each_read(self):
        missing = self.root / 'late.mp4'
        router = self.router(test_video_cases=[{'id': 'configured', 'path': missing}], test_video_path=self.first)
        self.assertEqual(self.items(router), [])
        missing.write_bytes(b'late')
        self.assertEqual([(item['id'], item['size_bytes']) for item in self.items(router)], [('configured', 4)])
        missing.write_bytes(b'changed-size')
        self.assertEqual(self.items(router)[0]['size_bytes'], 12)
        missing.unlink()
        self.assertEqual(self.items(router), [])
        wrong_suffix = self.root / 'phone.mov'
        wrong_suffix.write_bytes(b'not-listed')
        router = self.router(test_video_cases=[{'id': 'configured', 'path': wrong_suffix}], test_video_path=self.first)
        self.assertEqual(self.items(router), [])

    def test_configuration_is_captured_once_but_source_url_reference_is_retained(self):
        source = {'reference': 'before'}
        cases = [{'id': 'original', 'path': self.first, 'source_url': source}]
        router = self.router(test_video_cases=cases)
        cases[0].update(id='replaced', path=self.second)
        cases.append({'id': 'new', 'path': self.second})
        source['reference'] = 'after'
        items = self.items(router)
        self.assertEqual([(item['id'], item['filename']) for item in items], [('original', 'first.MP4')])
        self.assertIs(items[0]['source_url'], source)
        self.assertEqual(items[0]['source_url'], {'reference': 'after'})

    def test_configuration_errors_keep_service_construction_and_preview_order(self):
        for cases, error in (
            ([{'path': self.first, 'comparison_action_count': 'not-an-integer'}], ValueError),
            ([None], AttributeError),
        ):
            events = []
            with self.subTest(error=error), self.assertRaises(error):
                self.router(test_video_cases=cases, events=events)
            self.assertEqual(events, ['coaching', 'coaching-router', 'template', 'template-router',
                                      'actions', 'action-router', 'chunks'])
            self.assertIsInstance(self.last_manager.video_limits, replay.VideoLimits)


if __name__ == '__main__':
    unittest.main()
