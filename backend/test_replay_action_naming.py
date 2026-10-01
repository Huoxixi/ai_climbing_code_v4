import copy
import tempfile
import unittest
import json
from pathlib import Path
import cv2
import numpy as np
from core.replay_action_naming import enrich_names, caption_entries, CONDITIONS
from core.replay_actions import apply_local_review
from core.replay_action_engine import sample_action_frames, bounded_events, ActionEngine
from core.replay_action_review import revise_result, corrected_contact_evidence
from core.replay_route_usage import enrich_route_usage
from test_replay_actions import ActionLifecycleTests


def frame_rows():
    return [{"frame_id": f"frame-{i}", "time_seconds": i / 4,
             "hold_regions": [{"hold_id": "1"}, {"hold_id": "2"}]} for i in range(9)]


def named_event(limb="left_hand", action="reach", start=0., end=2., facts=None):
    return {"limb": limb, "action": action, "start_seconds": start, "end_seconds": end,
            "facts": facts or [], "evidence_status": "locally_verified"}


def fact(kind, hold, start, end):
    return {"kind": kind, "hold_id": str(hold), "start_seconds": start, "end_seconds": end, "status": "locally_verified"}


def organized(events):
    return enrich_names({"groups": [{"id": "g", "start_seconds": 0., "end_seconds": 4., "events": events}],
                         "source_duration_seconds": 4, "holds": [{"id": 1}, {"id": 2}], "video": {"fps": 30, "frame_count": 120}})


class NamingTests(unittest.TestCase):
    def test_malformed_model_fields_are_not_facts(self):
        output = bounded_events({'events':[{'limb':{},'action':[],'frame_ids':None,'facts':{},'techniques':'CROSS'}]})
        self.assertEqual(output['events'][0]['facts'],[])
        self.assertEqual(output['events'][0]['frame_ids'],[])
        self.assertEqual(output['events'][0]['action'],None)

    def test_direction_needs_registered_continuous_points(self):
        event={'limb':'left_hand','action':'reach','direction':'up','frame_ids':['frame-0','frame-4','frame-8']}
        self.assertIsNone(self.check_event(event,{'direction_state':'satisfied'})['events'][0]['direction'])
        frames=frame_rows()
        for i,row in enumerate(frames):row['wall_limb_points']={'left_hand':[.5,.8-i*.05]}
        self.assertEqual(self.check_event(event,{'direction_state':'satisfied'},frames)['events'][0]['direction'],'up')
        for row in frames:row['wall_limb_points']={'left_hand':[.5,.8]}
        self.assertIsNone(self.check_event(event,{'direction_state':'satisfied'},frames)['events'][0]['direction'])

    def check_event(self, event, check=None, frames=None):
        verified = {**copy.deepcopy(event), "verified": True, "chain_continuous": True, "conflict": False, "occluded": False}
        if check:
            verified.update(check)
        return apply_local_review({"id": "g", "start_seconds": 0, "end_seconds": 2, "events": [], "description": "动作片段"},
                                  {"events": [event]}, {"events": [verified]}, frames or frame_rows(), [{"id": 1}, {"id": 2}])

    def test_new_motion_is_not_promoted_to_a_contact(self):
        out = self.check_event({"limb": "left_foot", "action": "lift", "frame_ids": ["frame-0", "frame-4", "frame-8"]})
        self.assertEqual(out["events"][0]["facts"], [])
        self.assertNotIn("落", out["events"][0]["display_name"])

    def test_contact_requires_independent_fact_proof(self):
        event = {"limb": "right_hand", "action": "contact", "frame_ids": ["frame-0", "frame-4", "frame-8"],
                 "facts": [{"kind": "target_contact", "hold_id": 2, "frame_ids": ["frame-6", "frame-8"], "state": "satisfied"}]}
        out = self.check_event(event, {"facts": []})
        self.assertEqual(out["events"][0]["action"], "move")
        good = self.check_event(event)
        self.assertEqual(good["events"][0]["target_hold_id"], "2")
        self.assertNotIn("接触", caption_entries([good], .5)[0]["text"])
        self.assertIn("接触", caption_entries([good], 1.75)[0]["text"])

    def test_unknown_hold_and_missing_reference_fail_closed(self):
        for hold, frames in [(99, frame_rows()), (2, [{"frame_id": f"frame-{i}", "time_seconds": i/4} for i in range(9)])]:
            event = {"limb": "left_hand", "action": "contact", "frame_ids": ["frame-0", "frame-4", "frame-8"],
                     "facts": [{"kind": "target_contact", "hold_id": hold, "frame_ids": ["frame-6", "frame-8"], "state": "satisfied"}]}
            self.assertEqual(self.check_event(event, frames=frames)["events"][0]["facts"], [])

    def test_model_cannot_approve_a_technique(self):
        conditions = {k: "satisfied" for k in CONDITIONS["CROSS"][3]}
        event = {"limb": "right_hand", "action": "reach", "frame_ids": ["frame-0", "frame-4", "frame-8"],
                 "techniques": [{"code": "CROSS", "frame_ids": ["frame-0", "frame-4", "frame-8"], "conditions": conditions,
                                 "status": "human_confirmed", "conflict": False, "occluded": False}]}
        output = self.check_event(event)
        self.assertEqual(output["events"][0]["technique_tags"][0]["status"], "candidate")
        self.assertNotIn("交叉", output["description"])
        for invalid in (None, [], "satisfied", {**conditions, "path_visible": "unknown"}):
            checked = copy.deepcopy(event["techniques"])
            checked[0]["conditions"] = invalid
            self.assertEqual(self.check_event(event, {"techniques": checked})["events"][0]["technique_tags"], [])

    def test_simultaneous_events_are_not_rewritten_as_then(self):
        output = organized([named_event(), named_event("right_foot", "lift", .5, 1.5)])
        self.assertIn("同时", output["groups"][0]["description"])
        self.assertNotIn("随后", output["groups"][0]["description"])
        self.assertEqual(len(caption_entries(output["groups"], 1.)), 2)
        self.assertEqual(len(caption_entries(output["groups"], 2.)), 1)

    def test_match_requires_overlap_and_does_not_imply_swap(self):
        output = organized([named_event(facts=[fact("source_contact", 1, 0, 1.), fact("release", 1, .8, 1.)]),
                            named_event("right_hand", start=.5, end=2., facts=[fact("target_contact", 1, .5, 2.)])])
        codes = [r["code"] for r in output["relations"]]
        self.assertIn("HAND_MATCH", codes)
        self.assertNotIn("HAND_SWAP", codes)

    def test_swap_requires_release_not_just_two_contacts(self):
        first = named_event("left_foot", "release", 0, 1., [fact("source_contact", 1, 0, .8)])
        second = named_event("right_foot", "contact", 1.2, 2., [fact("target_contact", 1, 1.2, 2.)])
        self.assertEqual(organized([first, second])["relations"], [])
        first["facts"].append(fact("release", 1, .8, 1.))
        self.assertEqual(organized([first, second])["relations"][0]["code"], "FOOT_SWAP")

    def test_manual_revision_is_bounded_and_preserves_input(self):
        original = organized([named_event()]); before = copy.deepcopy(original)
        payload = {"group_id": "g", "event_id": original["groups"][0]["events"][0]["id"], "limb": "right_hand",
                   "action": "contact", "start_seconds": 0., "end_seconds": 2., "contact_seconds": 1.5,
                   "target_hold_id": "2", "technique_codes": ["CROSS"]}
        output = revise_result(original, payload, "owner")
        self.assertEqual(original, before)
        self.assertEqual(output["groups"][0]["events"][0]["event_status"], "human_confirmed")
        self.assertIn("人工确认", caption_entries(output["groups"], 1.75)[0]["text"])
        for patch in ({"end_seconds": 5}, {"target_hold_id": "999"}, {"technique_codes": ["fake"]}, {"start_seconds": float('nan')}):
            with self.assertRaises(ValueError):
                revise_result(original, {**payload, **patch}, "owner")

    def test_corrected_side_and_point_replace_counts_without_changing_source(self):
        original=organized([named_event()])
        source={'holds':[{'id':1},{'id':2}], 'video':{'duration_seconds':4,'fps':30},
                'attempt':{'contacts':[{'limb':limb,'hold_id':1,'start_time_seconds':0.,'end_time_seconds':2.}
                                       for limb in ('left_hand','right_hand')]}}
        before=copy.deepcopy(source)
        payload={'group_id':'g','event_id':original['groups'][0]['events'][0]['id'],'limb':'right_hand',
                 'action':'contact','start_seconds':0.,'end_seconds':2.,'contact_seconds':1.5,'target_hold_id':'2'}
        reviewed=revise_result(original,payload,'owner')
        corrected=corrected_contact_evidence(reviewed,source)
        usage=enrich_route_usage({**reviewed,'metrics':[]},corrected)['route_usage']
        self.assertEqual(usage['used_hold_ids'],['2'])
        self.assertEqual(usage['percent'],50.)
        self.assertEqual(source,before)

    def test_native_sampling_is_bounded_preserves_endpoints_and_cancels(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "video.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 30, (96, 64))
            for i in range(90):
                writer.write(np.full((64, 96, 3), i, np.uint8))
            writer.release()
            frames, sampling = sample_action_frames(source, {}, {"start_seconds": 0., "end_seconds": 2.9}, lambda: False, 30)
            self.assertLessEqual(len(frames), 32)
            self.assertEqual(frames[0]["frame_index"], 0)
            self.assertEqual(frames[-1]["frame_index"], 87)
            self.assertFalse(sampling["dense_source_frames"])
            with self.assertRaises(InterruptedError):
                sample_action_frames(source, {}, {"start_seconds": 0., "end_seconds": 2.9}, lambda: True)

    def test_engine_uses_blind_windows_and_rejects_sparse_dynamic_claims(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'video.mp4'
            writer=cv2.VideoWriter(str(source),cv2.VideoWriter_fourcc(*'mp4v'),10,(96,64))
            for i in range(30):writer.write(np.full((64,96,3),i,np.uint8))
            writer.release()
            calls=[]
            def provider(**kwargs):
                content=kwargs['messages'][1]['content']
                payload=json.loads(content[0]['text']);calls.append((kwargs['stage'],payload))
                ids=[json.loads(item['text'])['frame_id'] for item in content[1:] if 'text' in item]
                anchors=[ids[0],ids[len(ids)//2],ids[-1]]
                event={'limb':'left_hand','action':'reach','frame_ids':anchors,'facts':[],
                       'techniques':[{'code':'DYNO','frame_ids':anchors,'conditions':{k:'satisfied' for k in CONDITIONS['DYNO'][3]},'conflict':False,'occluded':False}]}
                if kwargs['stage']=='action_verify':
                    self.assertNotIn('limb',payload['event_windows'][0])
                    event.update(verified=True,chain_continuous=True,conflict=False,occluded=False)
                return {'content':{'events':[event]},'usage':{'prompt_tokens':1,'completion_tokens':1}}
            result={'groups':[{'id':'g','start_seconds':0.,'end_seconds':2.,'events':[],'description':'动作片段'}],
                    'video':{'fps':10.,'frame_count':30,'width':96,'height':64},'pose_samples':[],'holds':[]}
            ledger=[]
            reviews=ActionEngine(provider).run(source,{},result,cancelled=lambda:False,usage_callback=ledger.append)
            group=apply_local_review(result['groups'][0],reviews['g']['proposed'],reviews['g']['checked'],reviews['g']['frames'])
            self.assertEqual(group['events'][0]['technique_tags'],[])
            self.assertEqual([c[0] for c in calls],['action_observe','action_verify'])
            self.assertFalse(reviews['g']['sampling'][0]['dense_source_frames'])
            self.assertEqual(ledger[-1]['status'],'responded')


class RevisionLifecycleTests(ActionLifecycleTests):
    def test_review_version_ownership_undo_and_export_invalidation(self):
        self.client.post(self.url, json={}); data = self.wait()
        group = data["result"]["groups"][0]
        original = copy.deepcopy(self.store.get(self.id, 'alice', private=True)["result"])
        payload = {"result_version": data["result_version"], "group_id": group["id"], "limb": "left_foot", "action": "lift",
                   "start_seconds": group["start_seconds"], "end_seconds": group["end_seconds"], "technique_codes": ["HIGH_STEP"]}
        self.assertEqual(self.client.post(self.url + '/review', headers={"x-user": "bob"}, json=payload).status_code, 404)
        response = self.client.post(self.url + '/review', json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        updated = response.json()
        self.assertNotEqual(updated["result_version"], data["result_version"])
        self.assertEqual(updated["revision_count"], 1)
        self.assertEqual(self.store.get(self.id, 'alice', private=True)["result"], original)
        self.assertEqual(self.client.post(self.url + '/review', json=payload).status_code, 409)
        self.client.post(self.url + '/export', json={"result_version": updated["result_version"]})
        exported = self.wait('export')
        self.assertEqual(exported['export']['status'], 'succeeded')
        undo = self.client.post(self.url + '/review/undo', json={"result_version": updated["result_version"]})
        self.assertEqual(undo.status_code, 200)
        self.assertEqual(undo.json()["revision_count"], 0)
        self.assertEqual(undo.json()['result']['metrics'],data['result']['metrics'])
        audit=self.store.get(self.id,'alice',private=True)['action_revision_audit']
        self.assertEqual([r['kind'] for r in audit],['review','undo'])
        self.assertIsNone(undo.json()["export_media"])
        self.assertEqual(self.client.get(self.url + '/media', params={"version": exported['export_media']['id'], "exported": 'true'}).status_code, 409)


if __name__ == '__main__':
    unittest.main()
