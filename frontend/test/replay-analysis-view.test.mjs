import test from 'node:test'
import assert from 'node:assert/strict'
import { analysisFrame,registeredDisplayPoses,displayPoseAt,displayedHoldColors,currentVisualization,VISUAL_VERSION,limbBadges } from '../src/services/replayAnalysisView.js'

test('anatomical labels survive crossings, separate overlap and omit unavailable joints without mutation',()=>{
  const pose={kpts_xy:Array.from({length:17},()=>[.5,.5]),kpts_score:Array(17).fill(1)}
  pose.kpts_xy[9]=[.8,.4];pose.kpts_xy[10]=[.2,.4]
  const before=JSON.stringify(pose),badges=limbBadges(pose,720,1280)
  assert.deepEqual(badges.map(b=>[b.joint,b.text]),[[9,'左'],[10,'右'],[15,'左'],[16,'右']])
  assert.ok(Math.hypot(...badges[2].center.map((v,i)=>v-badges[3].center[i]))>=20)
  assert.equal(JSON.stringify(pose),before)
  pose.kpts_score[15]=0
  assert.equal(limbBadges(pose,720,1280).length,3)
  assert.deepEqual(limbBadges(null,720,1280),[])
})

const video={width:100,height:200,fps:10}
const sample=frame=>({source_frame_id:frame,time_seconds:frame/10,observed:true,wall_alignment:'reference',
  wall_reference_transform:[[1,0,10],[0,1,0],[0,0,1]],kpts_xy:Array.from({length:17},()=>[.4,.5]),kpts_score:Array(17).fill(.9)})
test('invalid event times never light playback or historical summary',()=>{
  for(const [start,end] of [[-1,2],[-Infinity,2],[0,Infinity],[2,1],[NaN,2]]){
    const contacts=[{limb:'left_hand',hold_id:1,start_source_frame:start,end_source_frame:end}]
    assert.equal(displayedHoldColors(contacts,0).size,0)
    assert.equal(displayedHoldColors(contacts,7,true).size,0)
  }
})
test('foot forks register toes and never fill missing detail from the ankle',()=>{
  const footSample=frame=>({...sample(frame),wholebody:{schema:'coco-wholebody-133',coordinates:'source_image_normalized',
    kpts_xy:Array.from({length:133},()=>[.3,.7]),kpts_score:Array(133).fill(.9)}})
  const source=footSample(0),before=JSON.stringify(source)
  const poses=registeredDisplayPoses({video,pose_samples:[source,footSample(2)]})
  assert.deepEqual(poses[0].feet.kpts_xy[1],[.4,.7])
  assert.deepEqual(poses[0].feet.kpts_xy[0],[.5,.5])
  assert.equal(JSON.stringify(source),before)
  assert.equal(displayPoseAt(poses,1,10).feet.basis,'display_interpolation')
  const weak=footSample(2);weak.wholebody.kpts_score[17]=.2
  const weakPoses=registeredDisplayPoses({video,pose_samples:[source,weak]})
  assert.equal(displayPoseAt(weakPoses,1,10).feet.kpts_score[1],0)
  assert.equal(registeredDisplayPoses({video,pose_samples:[sample(0)]})[0].feet,null)
})
test('final frame lights every used hold, seeking back restores current contacts only',()=>{
  const contacts=[{limb:'left_hand',hold_id:1,start_source_frame:0,end_source_frame:1},
    {limb:'right_foot',hold_id:2,start_source_frame:3,end_source_frame:4},
    {limb:'unknown',hold_id:3,start_source_frame:0,end_source_frame:4},
    {limb:'left_foot',hold_id:4,start_source_frame:8,end_source_frame:9}]
  assert.deepEqual([...displayedHoldColors(contacts,5,true).keys()],['1','2'])
  assert.equal(displayedHoldColors(contacts,5).size,0)
  assert.deepEqual([...displayedHoldColors(contacts,0).keys()],['1'])
})
test('both panes preserve original proportions and transforms register source joints',()=>{
  const f=analysisFrame(video)
  assert.deepEqual(f.video,[0,0,100,200]);assert.deepEqual(f.panel,[100,0,100,200])
  const poses=registeredDisplayPoses({video,pose_samples:[sample(2),sample(0)]})
  assert.deepEqual(poses.map(p=>p.source_frame_id),[0,2])
  assert.deepEqual(poses[0].kpts_xy[0],[.5,.5])
})
test('invalid or unstable registration blanks the analysis pose',()=>{
  for(const patch of [{wall_alignment:'failed'},{wall_reference_transform:[[0,0,0],[0,0,0],[0,0,0]]},
    {wall_alignment_diagnostics:{median_error_px:4}},{wall_alignment_diagnostics:{inliers:11}}]){
    const poses=registeredDisplayPoses({video,pose_samples:[{...sample(0),...patch}]})
    assert.equal(displayPoseAt(poses,0,10),null)
  }
})
test('no pose extrapolation, missing observation bridge or long-gap smoothing',()=>{
  const poses=registeredDisplayPoses({video,pose_samples:[sample(0),{...sample(2),observed:false},sample(4)]})
  assert.equal(displayPoseAt(poses,1,10),null);assert.equal(displayPoseAt(poses,5,10),null)
  assert.equal(displayPoseAt(registeredDisplayPoses({video,pose_samples:[sample(0),sample(10)]}),5,10),null)
  assert.ok(displayPoseAt(registeredDisplayPoses({video,pose_samples:[sample(0),sample(2)]}),1,10))
})

test('old visualization derives observed feet in memory and preserves saved data',()=>{
  const raw={video,pose_samples:[sample(0)]}
  const saved={version:'split_analysis_right_v11',pose_samples:[{old:true}]}
  const before=structuredClone(saved)
  const updated=currentVisualization(saved,raw,null)
  assert.equal(updated.version,VISUAL_VERSION)
  assert.equal(updated.pose_samples[0].kpts_score[9],.9)
  assert.equal(updated.pose_samples[0].feet,null)
  assert.deepEqual(saved,before)
  assert.equal(currentVisualization(saved,{video},null),saved)
  assert.equal(currentVisualization(updated,raw,null),updated)
})

test('audit 3.2 pixel and 0.2 score boundaries cannot display contact endpoints',()=>{
  for(const [error,score,expected] of [[3.2,.9,0],[0,.2,0],[3,.9,.9]]){
    const poses=registeredDisplayPoses({video,pose_samples:[{...sample(0),kpts_score:Array(17).fill(score),
      wall_alignment_diagnostics:{median_error_px:error,inliers:20}}]})
    assert.equal(poses[0].kpts_score[9],expected)
  }
})

test('new observation flags remain separate from raw responses and legacy thresholds',()=>{
  const source={...sample(0),kpts_score:Array(17).fill(.19),joint_eligibility:Array(17).fill(true)}
  const before=JSON.stringify(source)
  let display=registeredDisplayPoses({video,pose_samples:[source]})[0]
  assert.equal(display.kpts_score[10],1)
  assert.equal(JSON.stringify(source),before)
  source.joint_eligibility[10]=false
  display=registeredDisplayPoses({video,pose_samples:[source]})[0]
  assert.equal(display.kpts_score[10],0)
  source.joint_eligibility[10]=1
  assert.ok(registeredDisplayPoses({video,pose_samples:[source]})[0].kpts_score.every(v=>v===0))
  delete source.joint_eligibility
  assert.ok(registeredDisplayPoses({video,pose_samples:[source]})[0].kpts_score.every(v=>v===0))
})
