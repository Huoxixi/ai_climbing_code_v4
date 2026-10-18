import test from 'node:test'
import assert from 'node:assert/strict'
import { actionEventRows } from '../src/services/replayActionEvents.js'

test('important actions alone receive explanation cards while ordinary timeline windows stay silent', () => {
  const groups = [
    { id:'hand',start_seconds:3.2,end_seconds:4.1,action_features:[
      {limb:'left_hand',commentary:'左手向左上移动。',commentary_basis:'vision_evidence'},
      {limb:'body',commentary:'身体向左移动。',commentary_basis:'local_observation'}]},
    { id:'foot',start_seconds:5,end_seconds:6.4,action_features:[
      {limb:'right_foot',commentary:'右脚向上移动。',commentary_basis:'vision_evidence'}]}
  ]
  assert.equal(actionEventRows(groups).length,0)
  groups[1].important_action={title:'高抬腿',limb:'right_foot',quality:{status:'observed'},
    commentary:'右腿屈膝抬高，膝部接近髋部高度，为较高落脚位置做准备。',commentary_basis:'vision_evidence'}
  const rows = actionEventRows(groups)
  assert.equal(rows.length,1)
  assert.equal(rows[0].components.length,1)
  assert.equal(rows[0].title,'高抬腿')
  assert.deepEqual(rows.map(r=>[r.start_seconds,r.end_seconds]),[[5,6.4]])
  assert.equal(rows[0].group_id,'foot')
})
