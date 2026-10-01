import test from 'node:test'
import assert from 'node:assert/strict'
import { currentCaptions, shortActionLabel } from '../src/services/replayPresentation.js'

const observed = { id:'pose', limb:'left_hand', action:'move', start_seconds:1, end_seconds:3,
  evidence_status:'trajectory_observed', event_status:'trajectory_observed',
  caption_parts:[{start_seconds:1,text:'墙面参考中向左上方移位；相对肩部向上抬手（二维骨架观察）'}],
  trajectory_details:{status:'observed', phases:[
    {start_seconds:1,end_seconds:2,text:'向左上方抬手，手臂伸展'},
    {start_seconds:2,end_seconds:3,text:'末端位置趋于稳定，接触仍未确认'}]}}

test('reliable pose phases use a short movement name without adding contact claims', () => {
  assert.equal(shortActionLabel(observed,1.5),'向左上方抬手，手臂伸展')
  assert.equal(shortActionLabel(observed,2.5),'肢体趋稳')
  assert.equal(shortActionLabel({...observed,trajectory_details:{status:'observed'}},1.5),'向左上方移手')
  assert.equal(shortActionLabel({...observed,caption_parts:[{start_seconds:1,text:'扣除躯干共同旋转后，相对肩部向下抬手（二维骨架观察）'}],trajectory_details:{status:'observed'}},1.5),'向下抬手')
})

test('wall motion wins when torso-relative movement points in a different direction', () => {
  const foot = {...observed,limb:'left_foot',caption_parts:[{start_seconds:1,text:'墙面参考中向左上方移位；相对髋部向下移脚（二维骨架观察）'}],
    trajectory_details:{status:'observed',direction:'down',wall_direction:'up_left',
      summary:'墙面参考中向左上方移位；相对髋部向下移脚（二维骨架观察）',
      phases:[{start_seconds:1,end_seconds:3,text:'向下移脚，屈膝'}]}}
  assert.equal(shortActionLabel(foot,1.5),'向左上方移脚，屈膝')
  assert.equal(shortActionLabel({...foot,trajectory_details:{...foot.trajectory_details,phases:[]}},1.5),'向左上方移脚')
  assert.equal(shortActionLabel({...foot,trajectory_details:{status:'observed',summary:foot.trajectory_details.summary}},1.5),'向左上方移脚')
  assert.equal(shortActionLabel({...foot,trajectory_details:{...foot.trajectory_details,wall_direction:'right'}},1.5),'动作待复核')
  assert.equal(shortActionLabel({...foot,trajectory_details:{...foot.trajectory_details,wall_direction:null,summary:'相对髋部向下移脚'}},1.5),'动作待复核')
  const verifiedContact = {...foot,action:'contact',evidence_status:'locally_verified',event_status:'locally_verified',
    caption_parts:[{start_seconds:1,text:'接触岩点 2'}]}
  assert.equal(shortActionLabel(verifiedContact,1.5),'接触岩点 2')
  const human = {...foot,event_status:'human_confirmed',caption_parts:[{start_seconds:1,text:'向下移脚'}]}
  assert.equal(shortActionLabel(human,1.5),'向下移脚')
})

test('pose conflicts, insufficient coverage and carried motion remain unresolved', () => {
  for (const status of ['insufficient','conflict','body_carried','stationary',undefined]) {
    assert.equal(shortActionLabel({...observed,trajectory_details:{...observed.trajectory_details,status}},1.5),'动作待复核')
  }
  assert.equal(shortActionLabel({...observed,evidence_status:'needs_review',event_status:'needs_review'},1.5),'动作待复核')
})

test('visual contact and human corrections keep their source-time wording', () => {
  const contact = {...observed,action:'contact',evidence_status:'locally_verified',event_status:'locally_verified',
    caption_parts:[{start_seconds:1,text:'伸手靠近目标'},{start_seconds:2.5,text:'接触岩点 2'}]}
  assert.equal(shortActionLabel(contact,1.5),'伸手靠近目标')
  assert.equal(shortActionLabel(contact,2.5),'接触岩点 2')
  const human = {...contact,event_status:'human_confirmed',trajectory_details:{status:'conflict'},
    caption_parts:[{start_seconds:1,text:'原点重新抓握 2 · 交叉手（人工确认）'}]}
  assert.equal(shortActionLabel(human,1.5),'原点重新抓握 2')
})

test('display shortening leaves evidence, source captions and playback timing unchanged', () => {
  const source = structuredClone(observed), groups = [{id:'g',events:[observed]}]
  const before = currentCaptions(groups,1.5)
  assert.equal(shortActionLabel(before[0],1.5),'向左上方抬手，手臂伸展')
  assert.deepEqual(observed,source)
  assert.deepEqual(currentCaptions(groups,1.5),before)
  assert.deepEqual(currentCaptions(groups,.9),[])
})
