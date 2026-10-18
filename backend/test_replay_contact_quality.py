"""Shared positive/negative and temporal contact contracts; not accuracy scores."""
import copy
import unittest
from core.climb_replay import AliyunReplayAnalyzer

HOLD={'id':1,'bbox':[.4,.4,.04,.04]}

def sequence(point=(.42,.42), seconds=.7):
    result=[]
    for i in range(round(seconds*10)):
        points=[[0.,0.] for _ in range(17)]; points[9]=list(point)
        scores=[0.]*17; scores[9]=.9
        result.append({'frame_id':i,'source_frame_id':i*3,'kpts_xy':points,'kpts_score':scores})
    return result

class ContactQualityTests(unittest.TestCase):
    def contacts(self,records,**kwargs):
        return AliyunReplayAnalyzer._contacts(records,[HOLD],10,source_fps=30,**kwargs)['contacts']

    def test_confirmed_contact_keeps_start_and_separate_confirmation(self):
        contact=self.contacts(sequence())[0]
        self.assertEqual((contact['start_frame'],contact['stable_frame'],contact['end_frame']),(0,4,6))

    def test_invalid_scores_and_display_interpolation_never_support_contact(self):
        for value in (None,float('nan'),float('inf')):
            records=sequence()
            for record in records: record['kpts_score'][9]=value
            self.assertEqual(self.contacts(records),[])
        for flag in ({'observed':False},{'interpolated':True},{'render_mode':'interpolated'},{'render_mode':'edge_hold'},
                     {'pose_evidence':{'observation_kind':'display_interpolation'}},{'pose_evidence':{'observed':False}},
                     {'observation_kind':'display_interpolation'}):
            records=sequence()
            for record in records: record.update(flag)
            self.assertEqual(self.contacts(records),[])
        records=sequence()
        for record in records: record['kpts_score']=[]
        self.assertEqual(self.contacts(records),[])

    def test_short_rule_also_admits_near_pass_so_is_not_safe_default(self):
        near=sequence((.455,.42),seconds=.3)
        self.assertEqual(self.contacts(near),[])
        self.assertEqual(len(self.contacts(near,diagnostic_policy={'duration':0})),1)
        self.assertEqual(self.contacts(near,diagnostic_policy={'duration':0,'margin':0}),[])

    def test_multiple_candidates_are_audited_and_can_be_unknown_without_mutation(self):
        records=sequence(); before=copy.deepcopy(records); trace=[]
        holds=[HOLD,{'id':2,'bbox':[.41,.4,.04,.04]}]
        result=AliyunReplayAnalyzer._contacts(records,holds,10,source_fps=30,trace=trace,
                                             diagnostic_policy={'reject_ambiguous':True})
        self.assertEqual(result['contacts'],[])
        self.assertEqual(records,before)
        self.assertTrue(any(row['reason']=='competing_holds' for row in trace))

    def test_source_gap_does_not_confirm_disconnected_candidates(self):
        records=sequence(seconds=.3)+sequence(seconds=.3)
        for i,record in enumerate(records):
            record['frame_id']=i
            if i>=3: record['source_frame_id']+=60
        self.assertEqual(self.contacts(records),[])

    def test_source_time_mapping_keeps_confirmation_and_end_without_extending_to_next_sample(self):
        from core.climb_replay import add_attempt_source_times, VideoInfo
        records=sequence(); attempt=AliyunReplayAnalyzer._contacts(records,[HOLD],10,source_fps=30)
        samples=[{'sample_index':r['frame_id'],'source_frame_id':r['source_frame_id'],
                  'time_seconds':r['source_frame_id']/30} for r in records]
        video=VideoInfo(width=720,height=1280,fps=30,frame_count=300,duration_seconds=10,size_bytes=0)
        add_attempt_source_times(attempt,samples,video)
        self.assertEqual(attempt['contacts'][0]['stable_time_seconds'],.4)
        self.assertEqual(attempt['contacts'][0]['end_time_seconds'],.6)

    def test_fingertip_diagnostic_restores_position_only_when_detail_is_available(self):
        records=sequence((.5,.5))
        for record in records:
            record['wholebody']={'kpts_xy':[[0.,0.]]*133,'kpts_score':[0.]*133}
            record['wholebody']['kpts_xy'][99]=[.42,.42]
            record['wholebody']['kpts_score'][99]=.9
        self.assertEqual(self.contacts(records),[])
        self.assertEqual(len(self.contacts(records,diagnostic_policy={'contact_part':'wholebody','margin':0})),1)
        for record in records: record['wholebody']['kpts_score'][99]=0
        self.assertEqual(self.contacts(records,diagnostic_policy={'contact_part':'wholebody','margin':0}),[])

if __name__=='__main__': unittest.main()
