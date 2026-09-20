"""Offline contracts and real ONNX execution; synthetic fixtures are NOT accuracy evidence."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from experiments.photo_routes.data import (audit_manifest, digest_file, digest_json, write_new,
                                           load_image, source_digest, write_image_new)
from experiments.photo_routes.geometry import tiles, local_mask, overlap, object_from_mask, merge_candidate
from experiments.photo_routes.appearance import assign_colors, group_routes, probability
from experiments.photo_routes.inference import run_pipeline, check_recipe, OnnxDetector
from experiments.photo_routes.evaluation import (evaluate_sample, summarize, quality_gate, compare_quantization,
                                                  rank_validation, validation_failures)
from experiments.photo_routes.training import fit_logistic, train_auxiliary, export_coco, train_quality
from experiments.photo_routes.runner import freeze_report, validate_lock, evaluate_run
from experiments.photo_routes.public_data import import_indoor
from experiments.photo_routes.acceptance import attach_service
from experiments.photo_routes.deepseek import DeepSeekReviewer


def obj(oid='a', x=10, y=10, kind='hold', color='蓝色', size=20):
    return {**object_from_mask(np.ones((size, size), np.uint8), (x, y), kind, .99),
            'id': oid, 'color_group': color, 'lab': [80., 170., 40.],
            'appearance_std': [0., 0., 0.], 'color_confidence': .99, 'stability': 1.}


def sample(root, sid='sample', split='train', wall='wall', route=True):
    image = np.full((100, 120, 3), [200, 80, 30], np.uint8)
    image[0, 0, 0] = sum(map(ord, sid)) % 255
    path = root/f'{sid}.png'
    write_image_new(path, image)
    return {'id': sid, 'image': path.name, 'image_sha256': digest_file(path), 'size': [120, 100],
            'split': split, 'wall_id': wall, 'scene_id': wall, 'source_id': sid,
            'objects': [obj('a'), obj('b', 50), obj('c', 90)],
            'routes': [{'id': 'route1', 'member_ids': ['a', 'b', 'c'], 'decidable': True}] if route else [],
            'human_reviewed': True, 'complete': True, 'route_truth_confirmed_by': 'fixture',
            'ambiguity_labeled_before_predictions': True, 'model_training_overlap': False,
            'provenance': {'source': 'synthetic-test', 'license': 'test-only', 'commercial_training_allowed': True}}


class GeometryTests(unittest.TestCase):
    def test_continuous_polygon_at_image_border_is_valid(self):
        original = {'contour': [[80, 80], [100, 80], [100, 100], [80, 100]]}
        (x, y), mask = local_mask(original, (100, 100))
        self.assertEqual((x, y), (80, 80))
        self.assertEqual(mask.shape, (20, 20))
        original['contour'][0][0] = 101
        with self.assertRaises(ValueError):
            local_mask(original, (100, 100))

    def test_tiles_cover_edges_without_allocating_slices(self):
        covered = np.zeros((701, 1001), np.uint8)
        result = tiles(1001, 701)
        self.assertNotIsInstance(result, list)
        for x, y, w, h in result:
            covered[y:y+h, x:x+w] = 1
        self.assertTrue(covered.all())
        self.assertEqual(list(tiles(100, 90)), [(0, 0, 100, 90)])

    def test_local_rle_preserves_holes_and_disconnected_components(self):
        mask = np.ones((40, 60), np.uint8)
        mask[5:15, 10:20] = 0
        mask[:, 30:35] = 0
        original = object_from_mask(mask, (100, 200), 'hold', .9)
        origin, decoded = local_mask(original, (3000, 4000))
        self.assertEqual(origin, (100, 200))
        self.assertEqual(decoded.shape, (40, 60))
        np.testing.assert_array_equal(decoded, mask)

    def test_matching_offsets_and_no_overlap(self):
        a, b = obj(), obj(x=20)
        self.assertAlmostEqual(overlap(local_mask(a, (100, 100)), local_mask(b, (100, 100))), 1/3)
        self.assertEqual(overlap(local_mask(a, (100, 100)), local_mask(obj(x=70), (100, 100))), 0)

    def test_suppression_keeps_separate_volume_and_hold(self):
        objects = []
        merge_candidate(objects, obj('hold'), (100, 100))
        merge_candidate(objects, obj('volume', kind='volume'), (100, 100))
        self.assertEqual(len(objects), 2)
        candidate = {**obj('better'), 'confidence': 1.}
        merge_candidate(objects, candidate, (100, 100))
        self.assertEqual(len(objects), 2)
        self.assertEqual(objects[0]['id'], 'better')

    def test_nested_same_kind_is_flagged_not_destroyed(self):
        objects = [obj('large', size=50)]
        merge_candidate(objects, obj('small'), (100, 100))
        self.assertEqual(len(objects), 2)
        self.assertTrue(all(o['conflict'] for o in objects))

    def test_invalid_local_rle_rejected_before_allocating(self):
        original = obj()
        original['mask_rle']['origin'] = [99999, 0]
        with self.assertRaises(ValueError):
            local_mask(original, (100, 100))


class DatasetTests(unittest.TestCase):
    def test_small_dataset_cannot_be_formal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {'schema_version': 1, 'samples': [sample(root)]}
            write_new(root/'manifest.json', manifest)
            _, report = audit_manifest(root/'manifest.json')
            self.assertFalse(report['eligible'])
            self.assertIn('train: 1/120 张', report['blockers'])

    def test_same_wall_different_images_cannot_cross_splits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {'schema_version': 1, 'samples': [sample(root, 'a'), sample(root, 'b', 'holdout')]}
            write_new(root/'manifest.json', manifest)
            with self.assertRaisesRegex(ValueError, '跨集合'):
                audit_manifest(root/'manifest.json')

    def test_unknown_route_member_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = sample(root)
            data['routes'][0]['member_ids'].append('unknown')
            write_new(root/'manifest.json', {'schema_version': 1, 'samples': [data]})
            with self.assertRaisesRegex(ValueError, '线路成员'):
                audit_manifest(root/'manifest.json')

    def test_existing_files_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'result.json'
            write_new(path, {'original': True})
            with self.assertRaises(FileExistsError):
                write_new(path, {})
            self.assertEqual(json.loads(path.read_text()), {'original': True})

    def test_public_import_removes_only_failed_output_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'source'
            (source/'bh').mkdir(parents=True)
            write_image_new(source/'bh/good.png', np.zeros((100, 120, 3), np.uint8))
            write_image_new(source/'bh/bad.png', np.zeros((100, 120, 3), np.uint8))
            def region(xs):
                return {'shape_attributes': {'name': 'polygon', 'all_points_x': xs,
                        'all_points_y': [10, 10, 30]},
                        'region_attributes': {'label_type': 'handlabeled', 'hold_type': 'hold',
                                              'route_id': 'line'}}
            annotation = {'_via_img_metadata': {
                'good': {'filename': 'good.png', 'regions': [region([10, 30, 20])]},
                'bad': {'filename': 'bad.png', 'regions': [region([10, 130, 20])]}}}
            write_new(source/'bh-annotation.json', annotation)
            report = import_indoor(source, root/'output', training_pilot=True)
            self.assertEqual(report['imported'], 1)
            self.assertTrue((root/'output/bh-good.png').is_file())
            self.assertFalse((root/'output/bh-bad.png').exists())
            self.assertTrue((source/'bh/bad.png').is_file())


class AppearanceTests(unittest.TestCase):
    def test_uncalibrated_colour_is_pending(self):
        objects = [obj()]
        assign_colors(np.full((100, 100, 3), [200, 80, 30], np.uint8), objects)
        self.assertEqual(objects[0]['color_group'], '待确认')

    def test_calibrated_neutrals_are_supported(self):
        anchors = {'黑色': [18., 128., 128.], '白色': [242., 128., 128.], '灰色': [140., 128., 128.]}
        palette = {'anchors': {k: {'lab': v, 'scale': [12., 8., 8.]} for k, v in anchors.items()}}
        for value, expected in ((20, '黑色'), (240, '白色')):
            objects = [obj()]
            assign_colors(np.full((100, 100, 3), value, np.uint8), objects, palette)
            self.assertEqual(objects[0]['color_group'], expected)

    def test_rules_never_claim_real_route_completion(self):
        routes = group_routes([obj('a'), obj('b', 30), obj('c', 50)], (1000, 1000))
        self.assertTrue(routes)
        self.assertTrue(all(r['review_status'] == 'needs_review' for r in routes))

    def test_bridge_conflict_does_not_merge_entire_chain(self):
        objects = [obj('a'), obj('b', 30), obj('c', 50)]
        # a-b and b-c look same-route; a-c does not. Complete-link refuses the chain.
        with patch('experiments.photo_routes.appearance.probability', side_effect=[.99, .1, .99]):
            routes = group_routes(objects, (1000, 1000), {'fixture': True})
        self.assertEqual(len(routes), 2)
        self.assertTrue(all(r['review_status'] == 'needs_review' for r in routes))

    def test_shared_volume_never_bridges_routes(self):
        objects = [obj('a'), obj('b', 30), obj('c', 50), obj('v', kind='volume', size=70)]
        with patch('experiments.photo_routes.appearance.probability', return_value=.999):
            routes = group_routes(objects, (1000, 1000), {'fixture': True})
        self.assertEqual(len(routes), 1)
        self.assertNotIn('v', routes[0]['member_ids'])
        self.assertEqual(routes[0]['unassigned_volume_ids'], ['v'])
        self.assertEqual(routes[0]['review_status'], 'needs_review')


class MetricsTests(unittest.TestCase):
    def example(self):
        objects = [obj('a'), obj('b', 40), obj('c', 70)]
        sample = {'id': 's', 'size': [100, 100], 'objects': objects,
                  'routes': [{'id': 'line', 'member_ids': ['a', 'b', 'c'], 'decidable': True}]}
        result = {'status': 'completed', 'objects': copy.deepcopy(objects),
                  'route_candidates': [{'id': 'r', 'member_ids': ['a', 'b', 'c'], 'review_status': 'automatic'}]}
        return sample, result

    def test_exact_route_members_are_order_independent(self):
        sample, result = self.example()
        result['route_candidates'][0]['member_ids'].reverse()
        row = evaluate_sample(sample, result)
        self.assertEqual(row['exact_routes'], 1)
        self.assertEqual(quality_gate(summarize([row])), [])

    def test_wrong_kind_cannot_receive_geometry_credit(self):
        sample, result = self.example()
        result['objects'][0]['kind'] = 'volume'
        row = evaluate_sample(sample, result)
        self.assertEqual(row['kind_counts']['hold']['matched'], 2)
        self.assertEqual(row['exact_routes'], 0)

    def test_duplicate_route_counts_against_precision(self):
        sample, result = self.example()
        result['route_candidates'].append({**result['route_candidates'][0], 'id': 'duplicate'})
        row = evaluate_sample(sample, result)
        self.assertEqual(row['exact_routes'], 1)
        self.assertEqual(summarize([row])['route_precision'], .5)

    def test_missing_or_extra_member_is_not_exact(self):
        sample, result = self.example()
        result['route_candidates'][0]['member_ids'].pop()
        self.assertEqual(evaluate_sample(sample, result)['exact_routes'], 0)

    def test_failed_result_cannot_be_automatic_success(self):
        sample, result = self.example()
        result['status'] = 'incomplete'
        self.assertEqual(evaluate_sample(sample, result)['exact_routes'], 0)

    def test_pending_colour_is_in_denominator(self):
        sample, result = self.example()
        result['objects'][0]['color_group'] = '待确认'
        metrics = summarize([evaluate_sample(sample, result)])
        self.assertAlmostEqual(metrics['color_accuracy'], 2/3)

    def test_shared_member_can_match_two_exact_routes(self):
        sample, result = self.example()
        sample['routes'].append({'id': 'second', 'member_ids': ['a', 'b'], 'decidable': True})
        result['route_candidates'].append({'id': 'r2', 'member_ids': ['a', 'b'], 'review_status': 'automatic'})
        self.assertEqual(evaluate_sample(sample, result)['exact_routes'], 2)

    def test_freeze_binds_source_and_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sample, result = self.example()
            report = {'split': 'validation', 'sample_ids': ['a'],
                      'recipe': {'scheme': 'A', 'precision': 'fp32'},
                      'source_sha256': source_digest(), 'recipe_sha256': digest_json({'scheme': 'A'}),
                      'manifest_sha256': 'dataset', 'runtime_sha256': 'runtime',
                      'dataset_audit': {'eligible': True},
                      'metrics': summarize([evaluate_sample(sample, result)]),
                      'performance': {'all_successful': True, 'peak_bytes': 100, 'p95_seconds': 1}}
            report['recipe_sha256'] = digest_json(report['recipe'])
            write_new(root/'report.json', report)
            lock = freeze_report(root/'report.json', root/'lock.json')
            with self.assertRaises(ValueError):
                validate_lock(root/'lock.json', {'recipe_sha256': 'changed'})
            identity = {k: lock[k] for k in ('recipe_sha256', 'source_sha256', 'manifest_sha256', 'runtime_sha256')}
            validate_lock(root/'lock.json', identity)

    def test_failed_validation_cannot_be_frozen_or_ranked(self):
        sample, result = self.example()
        metrics = summarize([evaluate_sample(sample, result)])
        report = {'split': 'validation', 'sample_ids': ['a'], 'recipe': {'scheme': 'A', 'precision': 'fp32'},
                  'source_sha256': source_digest(), 'manifest_sha256': 'dataset', 'runtime_sha256': 'runtime',
                  'dataset_audit': {'eligible': False}, 'metrics': metrics,
                  'performance': {'all_successful': True, 'peak_bytes': 100, 'p95_seconds': 1}}
        report['recipe_sha256'] = digest_json(report['recipe'])
        self.assertIn('数据集尚未满足正式训练/验证/留出要求', validation_failures(report))
        self.assertEqual(rank_validation([report]), [])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_new(root/'report.json', report)
            with self.assertRaisesRegex(ValueError, '未达到冻结条件'):
                freeze_report(root/'report.json', root/'lock.json')

    def test_validation_ranking_prefers_more_exact_routes_then_resources(self):
        sample, result = self.example()
        metrics = summarize([evaluate_sample(sample, result)])
        base = {'split': 'validation', 'sample_ids': ['a'], 'manifest_sha256': 'dataset',
                'dataset_audit': {'eligible': True}, 'metrics': metrics,
                'performance': {'all_successful': True, 'peak_bytes': 200, 'p95_seconds': 2}}
        a = {**base, 'recipe': {'scheme': 'A', 'precision': 'fp32'}}
        b = copy.deepcopy(a)
        b['recipe']['scheme'] = 'B'
        b['performance']['peak_bytes'] = 100
        self.assertEqual(rank_validation([a, b])[0]['recipe']['scheme'], 'B')

    def test_quantization_cannot_change_other_thresholds(self):
        sample, result = self.example()
        metrics = summarize([evaluate_sample(sample, result)])
        report = {'manifest_sha256': 'd', 'split': 'validation', 'source_sha256': 's', 'sample_ids': ['a'],
                  'metrics': metrics, 'recipe': {'scheme': 'A', 'precision': 'fp32',
                                               'detector': {'path': 'a', 'sha256': 'f'}, 'route_threshold': .95}}
        quantized = copy.deepcopy(report)
        quantized['recipe']['precision'] = 'int8'
        quantized['recipe']['detector'].update(path='b', sha256='i', quantized_from='f')
        self.assertTrue(compare_quantization(report, quantized)['passed'])
        quantized['recipe']['route_threshold'] = .8
        with self.assertRaises(ValueError):
            compare_quantization(report, quantized)


class AcceptanceTests(unittest.TestCase):
    def evidence(self, report):
        runs = [{'request_id': f'run-{i:03d}', 'seconds': 1.0, 'peak_bytes': 500_000_000,
                 'completed': True, 'measurement_complete': True, 'cold_start': i == 0,
                 'series_id': 'continuous-50', 'sequence_index': i,
                 'pixels': 12_000_000 if i == 0 else 1_000_000,
                 'ground_truth_objects': 300 if i == 1 else 20} for i in range(50)]
        return {'schema_version': 1, 'scope': 'api-inference-images-cache',
                'target_hardware': 'test-cpu', 'synthetic': False,
                'recipe_sha256': report['recipe_sha256'],
                'manifest_sha256': report['manifest_sha256'],
                'source_sha256': report['source_sha256'], 'runs': runs,
                'queue_requests': [
                    {'request_id': 'q1', 'owner_alias': 'a', 'queued_at': 0, 'started_at': 0, 'finished_at': 10},
                    {'request_id': 'q2', 'owner_alias': 'b', 'queued_at': 5, 'started_at': 10, 'finished_at': 20}],
                'human_member_edits': 0}

    def test_service_evidence_is_measured_and_bound_to_holdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = {'offline_passed': True, 'split': 'holdout', 'recipe': {'scheme': 'A', 'precision': 'fp32'},
                      'recipe_sha256': 'recipe', 'manifest_sha256': 'manifest',
                      'source_sha256': source_digest(), 'metrics': {'exact_routes': 1}}
            write_new(root/'report.json', report)
            evidence = self.evidence(report)
            write_new(root/'evidence.json', evidence)
            accepted = attach_service(root/'report.json', root/'evidence.json', root/'accepted.json')
            self.assertTrue(accepted['passed'])
            self.assertTrue(accepted['performance']['queue_verified'])
            incomplete = copy.deepcopy(evidence)
            incomplete['runs'][49]['sequence_index'] = 48
            write_new(root/'incomplete-series.json', incomplete)
            with self.assertRaisesRegex(ValueError, '连续 50'):
                attach_service(root/'report.json', root/'incomplete-series.json', root/'incomplete.json')
            evidence['synthetic'] = True
            write_new(root/'synthetic.json', evidence)
            with self.assertRaisesRegex(ValueError, '合成测试'):
                attach_service(root/'report.json', root/'synthetic.json', root/'rejected.json')

class TrainingTests(unittest.TestCase):
    def test_logistic_training_separates_classes(self):
        model = fit_logistic([[-2], [-1], [1], [2]], [0, 0, 1, 1])
        self.assertLess(probability(model, [-1]), .2)
        self.assertGreater(probability(model, [1]), .8)

    def test_validation_is_not_used_for_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = sample(root, split='validation')
            write_new(root/'manifest.json', {'schema_version': 1, 'samples': [data]})
            with self.assertRaisesRegex(ValueError, '没有训练集'):
                train_auxiliary(root/'manifest.json', root/'models')

    def test_coco_export_never_reads_holdout_into_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = [sample(root), sample(root, 'held', 'holdout', 'different-wall')]
            write_new(root/'manifest.json', {'schema_version': 1, 'samples': data})
            report = export_coco(root/'manifest.json', root/'coco')
            self.assertEqual(report['train']['images'], 1)
            self.assertEqual(report['validation']['images'], 0)
            exported = json.loads((root/'coco/train.json').read_text())
            self.assertEqual(exported['annotations'][0]['segmentation']['size'], [100, 120])


def onnx_fixture(path, segmenter=False):
    import onnx
    from onnx import helper, numpy_helper, TensorProto
    shape = [1, 4, 256, 256] if segmenter else [1, 3, 640, 640]
    if segmenter:
        mask = np.zeros((1, 1, 256, 256), np.float32)
        mask[:, :, 32:224, 32:224] = 1
        values = {'probability': mask}
    else:
        masks = np.zeros((1, 1, 640, 640), np.float32)
        masks[:, :, 100:160, 100:160] = 1
        values = {'dets': np.array([[[100, 100, 160, 160, .99]]], np.float32),
                  'labels': np.array([[0]], np.int64), 'masks': masks}
    nodes = [helper.make_node('Identity', [name+'_value'], [name]) for name in values]
    outputs = [helper.make_tensor_value_info(name, TensorProto.INT64 if value.dtype == np.int64 else TensorProto.FLOAT,
                                            list(value.shape)) for name, value in values.items()]
    graph = helper.make_graph(nodes, 'synthetic-contract-fixture', [helper.make_tensor_value_info('image', TensorProto.FLOAT, shape)],
                              outputs, [numpy_helper.from_array(v, name+'_value') for name, v in values.items()])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 17)], ir_version=9)
    onnx.save(model, str(path))


class OnnxIntegrationTests(unittest.TestCase):
    def setUp(self):
        try:
            import onnx, onnxruntime
        except ImportError:
            self.skipTest('安装独立 ONNX 实验依赖后运行此集成测试')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        onnx_fixture(self.root/'detector.onnx')
        onnx_fixture(self.root/'roi.onnx', True)
        write_image_new(self.root/'image.png', np.full((640, 640, 3), [200, 80, 30], np.uint8))

    def recipe(self, scheme):
        artifact = lambda name: {'path': name, 'sha256': digest_file(self.root/name),
                                 'source': 'synthetic-test-only', 'license': 'test', 'commercial_use_allowed': True}
        detector = {**artifact('detector.onnx'), 'class_mapping': {'0': 'hold', '1': 'volume'},
                    'architecture': 'rtmdet-tiny' if scheme == 'B' else 'rtmdet-ins-tiny',
                    'resize': 'stretch-640', 'color_order': 'bgr', 'mean': [0, 0, 0], 'std': [1, 1, 1],
                    'mask_values': 'probability'}
        return {'schema_version': 1, 'scheme': scheme, 'precision': 'fp32', 'detector': detector,
                'segmenter': artifact('roi.onnx'), 'color_mode': 'hsv'}

    def test_real_onnx_contract_runs_all_three_schemes(self):
        for scheme in ('A', 'B', 'C'):
            recipe = self.recipe(scheme)
            check_recipe(recipe, self.root)
            result = run_pipeline(self.root/'image.png', recipe, self.root)
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(len(result['objects']), 1)
            self.assertEqual(result['objects'][0]['source_bbox_px'], [100, 100, 60, 60]) if scheme != 'B' else None
            self.assertTrue(all(r['review_status'] == 'needs_review' for r in result['route_candidates']))

    def test_onnx_remaps_nonsquare_box_and_mask(self):
        recipe = self.recipe('A')
        model = OnnxDetector(self.root/'detector.onnx', recipe['detector'])
        try:
            result = list(model.predict(np.ones((320, 640, 3), np.uint8), .4))
            self.assertEqual(result[0]['source_bbox_px'], [100, 50, 60, 30])
        finally:
            model.close()

    def test_wrong_checkpoint_hash_fails_without_fallback(self):
        recipe = self.recipe('A')
        recipe['detector']['sha256'] = 'wrong'
        with self.assertRaises(ValueError):
            check_recipe(recipe, self.root)

    def test_deepseek_postprocessor_is_part_of_same_pipeline_contract(self):
        recipe = self.recipe('A')
        recipe['deepseek'] = {'provider': 'DeepSeek', 'model': 'vision-fixture',
                              'prompt_version': 'semantic-review-v1',
                              'allowed_colors': ['蓝色', '黄色'], 'max_objects': 100,
                              'automatic_threshold': .95}
        check_recipe(recipe, self.root)
        events = []
        class Reviewer:
            def __init__(self, spec):
                events.append(('open', spec['model']))
            def review(self, image, objects, routes):
                events.append(('review', len(objects)))
                return {'objects': objects, 'routes': [], 'missing_centers': [],
                        'evidence': {'provider': 'DeepSeek', 'model': 'vision-fixture',
                                     'prompt_version': 'semantic-review-v1', 'seconds': .1,
                                     'request_sha256': 'request', 'response_sha256': 'response', 'rejected': 0}}
            def close(self):
                events.append(('close', None))
        result = run_pipeline(self.root/'image.png', recipe, self.root, reviewer_factory=Reviewer)
        self.assertEqual(events, [('open', 'vision-fixture'), ('review', 1), ('close', None)])
        self.assertEqual(result['deepseek']['response_sha256'], 'response')
        self.assertEqual(result['stages']['deepseek_seconds'], .1)

    def test_deepseek_response_cannot_invent_or_drop_candidate_ids(self):
        objects = [obj('a'), obj('b', 40), obj('c', 70)]
        spec = {'model': 'vision-fixture', 'prompt_version': 'semantic-review-v1',
                'allowed_colors': ['蓝色'], 'automatic_threshold': .95}
        reviewer = DeepSeekReviewer(spec, client=object(), key='test-secret')
        valid = {'objects': [{'id': oid, 'decision': 'keep', 'kind': 'hold',
                              'color': '蓝色', 'confidence': .99} for oid in ('a', 'b', 'c')],
                 'routes': [{'member_ids': ['a', 'b', 'c'], 'confidence': .99, 'reasons': []}],
                 'missing_centers': []}
        reviewed = reviewer._validate(valid, objects, .1, {'fixture': True})
        self.assertEqual(reviewed['routes'][0]['review_status'], 'automatic')
        invalid = copy.deepcopy(valid)
        invalid['objects'].pop()
        with self.assertRaisesRegex(ValueError, '全部候选'):
            reviewer._validate(invalid, objects, .1, {'fixture': True})

    def test_c_refines_only_after_detector_closed(self):
        events = []
        class Detector:
            def __init__(self, *args):
                events.append('detector-open')
            def predict(self, *args, **kwargs):
                yield {**obj(), 'stability': .4}
            def close(self):
                events.append('detector-close')
        class Segmenter:
            def __init__(self, *args):
                self.assertion = events[-1] == 'detector-close'
                if not self.assertion:
                    raise AssertionError('models overlap')
                events.append('segmenter-open')
            def refine(self, *args):
                return {**obj(), 'refined': True}
            def close(self):
                events.append('segmenter-close')
        result = run_pipeline(self.root/'image.png', self.recipe('C'), self.root,
                              detector_factory=Detector, segmenter_factory=Segmenter)
        self.assertTrue(result['objects'][0]['refined'])
        self.assertEqual(events, ['detector-open', 'detector-close', 'segmenter-open', 'segmenter-close'])

    def test_empty_b_segmentation_is_incomplete_not_box_mask(self):
        class Segmenter:
            def __init__(self, *args): pass
            def refine(self, *args): return None
            def close(self): pass
        result = run_pipeline(self.root/'image.png', self.recipe('B'), self.root, segmenter_factory=Segmenter)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['objects'], [])
        self.assertEqual(result['unsegmented_candidates'], 1)

    def test_supervised_cli_and_evaluator_do_not_claim_server_acceptance(self):
        from experiments.photo_routes.runner import run_dataset
        data = sample(self.root, split='validation')
        write_new(self.root/'manifest.json', {'schema_version': 1, 'samples': [data]})
        write_new(self.root/'recipe.json', self.recipe('A'))
        run_dataset(self.root/'manifest.json', self.root/'recipe.json', self.root/'run')
        report = evaluate_run(self.root/'manifest.json', self.root/'run/run.json', self.root/'evaluation.json')
        self.assertFalse(report['passed'])
        self.assertFalse(report['performance']['full_service_verified'])
        self.assertGreater(report['performance']['peak_bytes'], 0)


if __name__ == '__main__':
    unittest.main()
