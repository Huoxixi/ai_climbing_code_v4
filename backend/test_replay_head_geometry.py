"""Artwork must not alter the evidence used by the climbing algorithms."""
import copy
import unittest
from unittest.mock import patch
import numpy as np
from core.replay_head_geometry import head_geometry, project_head, draw_head
from core.replay_analysis_view import AnalysisView, visual_evidence
from test_replay_segments_and_analysis_view import scene


def pose():
    xy = [[.5,.6] for _ in range(17)]
    for i,p in {0:[.5,.37],1:[.48,.36],2:[.52,.36],3:[.46,.38],4:[.54,.38],
                5:[.43,.5],6:[.57,.5],11:[.44,.75],12:[.56,.75]}.items():
        xy[i] = p
    return dict(observed=True,kpts_xy=xy,kpts_score=[.9]*17)


class HeadArtworkTests(unittest.TestCase):
    def test_head_is_round_in_source_pixels_for_landscape_and_portrait(self):
        for width,height in ((1000,800),(720,1280)):
            geometry=head_geometry(pose(),width,height)
            center=np.array(geometry['center'])*[width,height]
            radii=np.linalg.norm(np.array(geometry['outline'])*[width,height]-center,axis=1)
            self.assertLess(np.ptp(radii),1e-10)

    def test_head_remains_round_after_perspective_projection(self):
        geometry=head_geometry(pose(),1000,800)
        project=lambda p:[p[0]*1000/(1+p[0]*.2),p[1]*800/(1+p[0]*.2)]
        art=project_head(geometry,project)
        radii=np.linalg.norm(np.array(art['outline'])-project(geometry['center']),axis=1)
        self.assertLess(np.ptp(radii),1e-10)

    def test_geometry_and_paint_do_not_change_any_observation(self):
        p=pose(); before=copy.deepcopy(p)
        image=np.zeros((800,1000,3),np.uint8)
        draw_head(image,p,1000,800,lambda xy:(xy[0]*1000,xy[1]*800))
        self.assertEqual(p,before)
        self.assertTrue(image.any())
        self.assertFalse(image[410:].any())  # shoulders and entire body unchanged

    def test_missing_uncertain_and_placeholder_faces_are_not_invented(self):
        for change in ('missing','one','duplicate','far','flags','nan'):
            p=pose()
            if change=='missing': p['observed']=False
            if change=='one': p['kpts_score'][1:5]=[0]*4
            if change=='duplicate': p['kpts_xy'][:5]=[[.5,.37]]*5
            if change=='far': p['kpts_xy'][:5]=[[.1+i*.01,.9] for i in range(5)]
            if change=='flags': p['joint_eligibility']=[False]*17
            if change=='nan': p['kpts_xy'][5]=[float('nan'),.5]
            with self.subTest(change=change): self.assertIsNone(head_geometry(p,1000,800))

    def test_explicit_eligibility_preserves_raw_response_contract(self):
        p=pose(); p['kpts_score']=[2.3]*17
        self.assertIsNone(head_geometry(p,1000,800))
        p['joint_eligibility']=[True]*17
        self.assertIsNotNone(head_geometry(p,1000,800))

    def test_side_view_uses_torso_scale(self):
        a=pose(); b=copy.deepcopy(a)
        b['kpts_xy'][5]=[.49,.5]; b['kpts_xy'][6]=[.51,.5]
        self.assertEqual(head_geometry(a,1000,800),head_geometry(b,1000,800))

    def test_display_minimum_is_capped_and_does_not_move_center(self):
        geometry=head_geometry(pose(),1000,800)
        projection=lambda p:[p[0]*50,p[1]*40]
        art=project_head(geometry,projection)
        center=projection(geometry['center'])
        radius=lambda points:min(np.linalg.norm(np.array(p)-center) for p in points)
        self.assertAlmostEqual(radius(art['outline'])/radius(list(map(projection,geometry['outline']))),1.6)
        self.assertLess(np.linalg.norm(np.mean(art['outline'],axis=0)-center),1e-10)

    def test_clipped_head_never_paints_outside_scene_or_into_other_pane(self):
        raw=scene(); raw['video'].update(width=1000,height=800)
        p=pose()
        # Move the whole torso close to the right edge; outline may cross it.
        p['kpts_xy']=[[x+.47,y] for x,y in p['kpts_xy']]
        for sample in raw['pose_samples']: sample.update(copy.deepcopy(p))
        view=AnalysisView(raw); image=np.full((800,1000,3),50,np.uint8)
        frame=view.compose(image,0,(2000,800),show_skeleton=True)
        with patch('core.replay_analysis_view.draw_head'):
            baseline=view.compose(image,0,(2000,800),show_skeleton=True)
        self.assertTrue(np.array_equal(frame[:,:900],baseline[:,:900]))

    def test_all_picture_combinations_leave_timeline_contacts_and_metrics_unchanged(self):
        raw=scene()
        for sample in raw['pose_samples']: sample.update(pose())
        before=copy.deepcopy(raw); evidence=visual_evidence(raw); view=AnalysisView(raw)
        timeline=copy.deepcopy(view.timeline); contacts=copy.deepcopy(view.contacts)
        image=np.zeros((64,96,3),np.uint8)
        for sk,hu,di in ((1,1,1),(1,1,0),(1,0,1),(1,0,0),(0,1,1),(0,1,0),(0,0,1)):
            view.compose(image,0,(96*(bool(sk or hu)+di),64),show_skeleton=sk,show_human=hu,
                         show_diagram=di,background=image,reference_to_background=np.eye(3))
        self.assertEqual(raw,before)
        self.assertEqual(visual_evidence(raw),evidence)
        self.assertEqual(view.timeline,timeline)
        self.assertEqual(view.contacts,contacts)
