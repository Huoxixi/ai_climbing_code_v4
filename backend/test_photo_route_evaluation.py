import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from core.photo_route_evaluation import evaluate_objects, match_instances, mask_for, boundary_f1, summarize
from core.photo_route_analysis import (PRODUCTION_CLIMBING_CANDIDATE_CAP,
    PRODUCTION_CLIMBING_MIN_SIZE, _apply_production_climbing_profile, analyze_board_photo)
from core.photo_route_processing import PhotoProcessingError
from scripts.evaluate_photo_route_v2 import evaluate, validate_manifest
from scripts.create_photo_route_evaluation_manifest import create_manifest
from test_photo_route_v2 import photo_bytes


def obj(x=10, kind='hold', color='紫色'):
    return {'kind':kind, 'color_group':color, 'contour':[[x,10],[x+20,10],[x+20,30],[x,30]]}


class EvaluationTests(unittest.TestCase):
    def test_production_climbing_profile_is_always_1200_300(self):
        class Value: pass
        cfg=Value();cfg.INPUT=Value();cfg.TEST=Value()
        cfg.INPUT.MIN_SIZE_TEST=960;cfg.INPUT.MAX_SIZE_TEST=1000
        cfg.TEST.DETECTIONS_PER_IMAGE=200
        _apply_production_climbing_profile(cfg)
        self.assertEqual(cfg.INPUT.MIN_SIZE_TEST,PRODUCTION_CLIMBING_MIN_SIZE)
        self.assertEqual(cfg.INPUT.MAX_SIZE_TEST,PRODUCTION_CLIMBING_MIN_SIZE)
        self.assertEqual(cfg.TEST.DETECTIONS_PER_IMAGE,PRODUCTION_CLIMBING_CANDIDATE_CAP)

    def test_manifest_skeleton_hashes_without_copying_or_overwriting_images(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);validation=[];holdout=[]
            for index in range(5):
                path=root/f'{index}.jpg';path.write_bytes(f'photo-{index}'.encode())
                (validation if index<3 else holdout).append(path)
            output=root/'manifest.json'
            manifest=create_manifest(output,validation,holdout)
            self.assertEqual([s['split'] for s in manifest['samples']],
                             ['validation']*3+['holdout']*2)
            self.assertTrue(all(len(s['image_sha256'])==64 for s in manifest['samples']))
            with self.assertRaises(FileExistsError):create_manifest(output,validation,holdout)

    def test_matching_does_not_lose_second_object_to_greedy_choice(self):
        scores=np.array([[.9,.7],[.8,.1]])
        self.assertEqual(len(match_instances(scores)),2)

    def test_duplicate_is_not_a_second_true_positive(self):
        row=evaluate_objects([obj()],[obj(),obj()],(100,100))
        report=summarize([row])
        self.assertEqual(report['object_recall'],1)
        self.assertEqual(report['object_precision'],.5)
        self.assertEqual(row['duplicate_predictions'],1)
        self.assertEqual(row['severe_contour_failures'],1)
        self.assertEqual(row['severe_contour_breakdown']['duplicates'],1)

    def test_unmatched_partial_object_is_a_severe_contour_failure(self):
        partial={'kind':'hold','color_group':'紫色','contour':[[10,10],[18,10],[18,30],[10,30]]}
        row=evaluate_objects([obj()],[partial],(100,100))
        self.assertEqual(row['matched'],0)
        self.assertEqual(row['severe_contour_breakdown']['unmatched_partial_objects'],1)
        self.assertEqual(row['severe_contour_failures'],1)

    def test_pending_wrong_missing_and_kind_metrics(self):
        truth=[obj(),obj(40),obj(70)]
        row=evaluate_objects(truth,[obj(color='待确认'),obj(40,kind='volume',color='粉色')],(100,100))
        report=summarize([row])
        self.assertEqual(report['pending_color_rate'],.5)
        self.assertEqual(report['wrong_color_rate'],.5)
        self.assertEqual(report['correct_group_recall'],0)
        self.assertEqual(report['per_kind']['hold']['recall'],1/3)

    def test_boundaries_measure_geometry_not_vertices(self):
        a=mask_for(obj()['contour'],(100,100)); b=mask_for(obj(15)['contour'],(100,100))
        self.assertEqual(boundary_f1(a,a),1)
        self.assertLess(boundary_f1(a,b),1)

    def test_color_conditions_are_reported_separately(self):
        truth=[{**obj(), 'conditions':['low_saturation','chalk']},
               {**obj(40), 'conditions':['shadow']}]
        report=summarize([evaluate_objects(truth,[obj(),obj(40,color='待确认')],(100,100))])
        self.assertEqual(report['color_by_condition']['low_saturation']['accuracy'],1)
        self.assertEqual(report['color_by_condition']['chalk']['correct_group_recall'],1)
        self.assertEqual(report['color_by_condition']['shadow']['accuracy'],0)

    def test_disputed_instances_are_counted_but_excluded(self):
        disputed={**obj(),'disputed':True}
        row=evaluate_objects([disputed],[obj()],(100,100))
        self.assertEqual((row['excluded_truth'],row['excluded_predictions']),(1,1))
        self.assertEqual(row['predictions'],0)

    def test_merge_flag_and_nested_parent_are_distinct(self):
        merged={'kind':'hold','contour':[[10,10],[60,10],[60,30],[10,30]]}
        row=evaluate_objects([obj(),obj(40)],[merged],(100,100))
        self.assertEqual(row['merge_flags'],1)
        parent={**merged,'kind':'volume'}
        self.assertEqual(evaluate_objects([obj(),parent],[parent],(100,100))['merge_flags'],0)

    def test_leaked_scene_or_duplicate_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'a').write_bytes(b'a');(root/'b').write_bytes(b'b')
            samples=[{'image':'a','scene_id':'same','objects':[]},
                     {'image':'b','scene_id':'same','holdout':True,'objects':[]}]
            with self.assertRaises(ValueError):validate_manifest({'samples':samples},root)
            samples[1]['scene_id']='other';samples[1]['image']='a'
            with self.assertRaises(ValueError):validate_manifest({'samples':samples},root)

    def test_default_evaluator_requires_climbing_model_and_never_passes_unreviewed_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'a.jpg').write_bytes(photo_bytes())
            (root/'manifest.json').write_text(json.dumps({'samples':[{'image':'a.jpg','objects':[obj()]}]}))
            with patch('scripts.evaluate_photo_route_v2.analyze_board_photo',return_value={'objects':[obj()],'model_version':'test'}) as infer:
                report=evaluate(root/'manifest.json')
            self.assertTrue(infer.call_args.kwargs['require_climbing_model'])
            self.assertFalse(infer.call_args.kwargs['require_mobilesam'])
            self.assertFalse(infer.call_args.kwargs['coarse_only'])
            self.assertFalse(infer.call_args.kwargs['boundary_refinement'])
            self.assertEqual(infer.call_args.kwargs['color_version'],'interior-v4')
            self.assertEqual(report['config']['mode'],'climbing')
            self.assertEqual(report['config']['color_version'],'interior-v4')
            self.assertNotIn('anchor_accuracy',report['quality_gates'])
            self.assertIn('peak_process_bytes',report['performance'])
            self.assertFalse(report['passed'])

    def test_five_image_manifest_keeps_holdout_independent_and_can_pass_recognition_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);samples=[]
            for index in range(5):
                image=np.full((100,100,3),40+index,np.uint8)
                ok,encoded=__import__('cv2').imencode('.png',image);self.assertTrue(ok)
                name=f'image-{index}.png';(root/name).write_bytes(encoded.tobytes())
                digest=hashlib.sha256((root/name).read_bytes()).hexdigest()
                split='validation' if index<3 else 'holdout'
                samples.append({'image':name,'image_sha256':digest,'split':split,
                    'scene_id':f'scene-{index}','source_id':f'source-{index}',
                    'human_reviewed':True,'complete':True,
                    'model_training_overlap':False if split=='holdout' else None,
                    'algorithm_tuning_overlap':False if split=='holdout' else None,
                    'objects':[obj()]})
            manifest=root/'manifest.json';manifest.write_text(json.dumps({'samples':samples}),encoding='utf-8')
            prediction={'objects':[obj()],'model_version':'climbing-test'}
            with patch('scripts.evaluate_photo_route_v2.analyze_board_photo',return_value=prediction):
                validation=evaluate(manifest,max_peak_memory_bytes=16*1024**3)
                holdout=evaluate(manifest,split='holdout',locked_config=validation['config'],
                                 max_peak_memory_bytes=16*1024**3)
            self.assertTrue(holdout['dataset_audit']['eligible'])
            self.assertTrue(validation['validation_ready_to_lock'],(validation['gate_blockers'],validation['performance']))
            self.assertTrue(holdout['passed'],holdout['gate_blockers'])
            self.assertEqual(holdout['quality_gates']['boundary_f1'],True)
            self.assertEqual(holdout['color_by_condition']['chalk']['truth'],0)

    def test_holdout_needs_locked_config_before_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'manifest.json';path.write_text('{"samples":[]}')
            with self.assertRaisesRegex(ValueError,'锁定配置'):evaluate(path,split='holdout')

    def test_saved_predictions_require_matching_photo_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'a.jpg').write_bytes(photo_bytes())
            (root/'prediction.json').write_text(json.dumps({'objects':[],'input_fingerprint':'wrong','model_version':'test'}))
            (root/'manifest.json').write_text(json.dumps({'samples':[{'image':'a.jpg','prediction':'prediction.json','objects':[]}]}))
            with self.assertRaisesRegex(ValueError,'原图'):evaluate(root/'manifest.json',mode='saved')

    def test_boundary_ablation_and_color_version_are_explicit(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'image.jpg';path.write_bytes(photo_bytes())
            mask=np.zeros((800,1200),np.uint8);mask[260:340,260:340]=255
            with patch('core.photo_route_analysis._mobilesam_masks',return_value=([mask],'mobilesam-test')), \
                 patch('core.photo_route_analysis.refine_boundary') as refine, \
                 patch('core.photo_route_analysis.detect_photo_hole_grid',return_value=None):
                result=analyze_board_photo(path,root,require_mobilesam=True,boundary_refinement=False,color_version='interior-v4')
            refine.assert_not_called()
            self.assertEqual(result['processing_config']['boundary_version'],'off')
            self.assertEqual(result['processing_config']['color_version'],'interior-v4')
            self.assertIn('boundary-off',result['model_version'])

    def test_missing_required_model_never_falls_back(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'image.jpg';path.write_bytes(photo_bytes())
            with patch('core.photo_route_analysis._mobilesam_masks',return_value=None):
                with self.assertRaises(PhotoProcessingError):analyze_board_photo(path,root,require_mobilesam=True)

    def test_climbing_model_path_skips_hole_grid_detection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'image.jpg';path.write_bytes(photo_bytes())
            mask=np.zeros((800,1200),np.uint8);mask[260:340,260:340]=255
            with patch('core.photo_route_analysis.detect_photo_hole_grid',side_effect=AssertionError('grid is not part of climbing recognition')), \
                 patch('core.photo_route_analysis._climbing_model_masks',return_value=([mask],[.97],'climbing-test')):
                result=analyze_board_photo(path,root,require_climbing_model=True,color_version='interior-v4')
            self.assertEqual(result['model_version'],'climbing-test+interior-v4+boundary-off')
            self.assertEqual(len(result['objects']),1)
            self.assertEqual(result['objects'][0]['anchors'],[])

    def test_match_indices_still_refer_to_original_truth_after_exclusion(self):
        truth=[{**obj(),'disputed':True},obj(40)]
        self.assertEqual(evaluate_objects(truth,[obj(40)],(100,100))['matches'][0]['truth_index'],1)

    def test_per_kind_matching_is_not_decided_by_cross_kind_ties(self):
        truth=[obj(kind='hold'),obj(kind='volume')]
        row=evaluate_objects(truth,[obj(kind='hold'),obj(kind='volume')],(100,100))
        self.assertEqual(row['kind_matches'],{'hold':1,'volume':1})
