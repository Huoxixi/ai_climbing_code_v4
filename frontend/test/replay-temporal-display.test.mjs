import test from 'node:test'
import assert from 'node:assert/strict'
import {temporalDisplaySample,TEMPORAL_DISPLAY_VERSION} from '../src/services/replayTemporalDisplay.js'
import {registeredDisplayPoses,displayPoseAt} from '../src/services/replayAnalysisView.js'

function sample() {
  return {source_frame_id:3,observed:true,wall_alignment:'reference',
    wall_reference_transform:[[1,0,0],[0,1,0],[0,0,1]],joint_eligibility:Array(17).fill(true),
    kpts_xy:Array.from({length:17},()=>[.5,.5]),kpts_score:Array(17).fill(.9),
    wholebody:{coordinates:'source_image_normalized',schema:'coco-wholebody-133',
      kpts_xy:Array.from({length:133},()=>[.5,.5]),kpts_score:Array(133).fill(.9),joint_eligibility:Array(133).fill(true)},
    temporal_display:{version:TEMPORAL_DISPLAY_VERSION,source_frame_id:3,coordinates:'source_image_normalized',
      kind:'image_supported_temporal_inference',updates:[{joint:15,xy:[.51,.52]},{joint:17,xy:[.53,.54]}]}}
}
test('raw data stays immutable while body and foot drawing share source coordinates',()=>{
  const s=sample(),before=structuredClone(s),display=temporalDisplaySample(s)
  assert.deepEqual(s,before);assert.deepEqual(display.kpts_xy[15],[.51,.52])
  assert.deepEqual(display.wholebody.kpts_xy[17],[.53,.54]);assert.equal(display.display_basis.contact_evidence,false)
  const poses=registeredDisplayPoses({video:{width:720,height:1280},pose_samples:[s]})
  assert.deepEqual(poses[0].source_kpts_xy[15],[.51,.52]);assert.deepEqual(poses[0].source_feet.kpts_xy[1],[.53,.54])
  assert.deepEqual(displayPoseAt(poses,3,30),poses[0]);assert.deepEqual(s,before)
})
test('wrong source clock, weak points and illegal coordinates cannot be promoted',()=>{
  for(const mutator of [s=>s.temporal_display.source_frame_id=4,s=>s.temporal_display.version='unverified',
    s=>s.temporal_display.updates=[{joint:15,xy:[NaN,.5]}],s=>s.temporal_display.updates=[{joint:5,xy:[.1,.2]}],
    s=>s.wholebody.joint_eligibility[15]=false]) {
    const s=sample();mutator(s);assert.deepEqual(temporalDisplaySample(s).kpts_xy[15],[.5,.5])
  }
})
