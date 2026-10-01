import test from 'node:test'
import assert from 'node:assert/strict'
import { currentExplanation, currentCaptions, summarySeconds, summaryMetrics, routeMetrics, routeSeconds, rhythmStart, metricValue } from '../src/services/replayPresentation.js'
test('pose-only observations keep their evidence identity and do not imply a contact', () => {
  const observed = { id:'pose', limb:'left_hand', action:'reach', start_seconds:1, end_seconds:2,
    evidence_status:'trajectory_observed', event_status:'trajectory_observed', facts:[], technique_tags:[],
    caption_parts:[{start_seconds:1,text:'向左上方抬手，手臂伸展'}],
    trajectory_details:{status:'observed',summary:'相对躯干向左上方移位，接触未确认'} }
  const groups = [{id:'g',events:[observed,{...observed,id:'unknown',limb:'right_foot',evidence_status:'needs_review'}]}]
  const explanation = currentExplanation(groups,1.5)
  assert.equal(explanation.entries.length,1)
  assert.equal(explanation.entries[0].evidence_status,'trajectory_observed')
  assert.equal(explanation.entries[0].limbCode,'left_hand')
  assert.deepEqual(explanation.entries[0].facts,[])
  assert.match(explanation.entries[0].trajectory_details.summary,/接触未确认/)
  assert.equal(currentExplanation(groups,.9),null)
})
test('contact phases do not backdate a landing; candidates never become subtitles', () => {
  const groups = [{id:'a',events:[{id:'e',limb:'right_hand',action:'contact',start_seconds:0,end_seconds:2,evidence_status:'locally_verified',
    caption_parts:[{start_seconds:0,text:'伸手靠近目标'},{start_seconds:1.5,text:'接触岩点 2'}],
    technique_tags:[{code:'CROSS',name:'交叉手',status:'candidate'}],
    relations:[{code:'BUMP',name:'连续换点',status:'candidate',start_seconds:0,end_seconds:2}]}]}]
  assert.equal(currentExplanation(groups,1).text,'伸手靠近目标')
  assert.equal(currentExplanation(groups,1.5).text,'接触岩点 2')
  assert.equal(currentExplanation(groups,.5).text.includes('交叉手'),false)
})
test('overlapping limbs remain visible only for their actual overlap', () => {
  const groups = [{id:'a',events:[{limb:'left_hand',action:'move',start_seconds:0,end_seconds:2,evidence_status:'locally_verified'},
    {limb:'right_foot',action:'move_up',start_seconds:.5,end_seconds:1.5,evidence_status:'human_confirmed'}]}]
  assert.equal(currentCaptions(groups,1).length,2)
  assert.equal(currentCaptions(groups,2).length,1)
  assert.equal(currentCaptions(groups,2)[0].limb,'左手')
})
test('captions follow verified event windows, including continuous playback', () => {
  const groups = [{id:'a',events:[{limb:'left_foot',action:'move_up',start_seconds:9.8,end_seconds:10.5,evidence_status:'locally_verified'},
    {limb:'right_hand',action:'move',start_seconds:10.6,end_seconds:11,evidence_status:'locally_verified'},
    {limb:'right_foot',action:'move',start_seconds:12,end_seconds:13,evidence_status:'needs_review'}]}]
  assert.equal(currentExplanation(groups,9.7),null)
  assert.equal(currentExplanation(groups,10.2).limb,'左脚')
  assert.equal(currentExplanation(groups,10.7).limb,'右手')
  assert.equal(currentExplanation(groups,12.5),null)
})
test('rhythm chapter replaces duplicate moving/still rows and keeps unknown distinct', () => {
  const metrics = [{key:'duration'},{key:'moving'},{key:'relative_still'},{key:'longest_still',value:null,display_value:'未见 ≥1 秒'}]
  assert.equal(summarySeconds(metrics,{}),10.4)
  assert.deepEqual(summaryMetrics(metrics,{}).map(m=>m.key),['duration','longest_still'])
  assert.equal(metricValue(metrics.at(-1)),'未见 ≥1 秒')
})
test('sequential data gets time for each row plus a final reading hold', () => {
  assert.equal(summarySeconds([]),0)
  assert.equal(summarySeconds([{}]),3.6)
  assert.ok(Math.abs(summarySeconds(Array(5).fill({}))-6.8)<1e-9)
})
test('route usage appears first and gives the remaining data its own chapter', () => {
  const metrics = [{key:'route_total'},{key:'route_used'},{key:'route_usage'}, {key:'duration'},{key:'longest_still'}]
  assert.equal(routeMetrics(metrics).length,3)
  assert.equal(routeSeconds(metrics),5.2)
  assert.equal(summaryMetrics(metrics,{}).length,2)
  assert.ok(Math.abs(rhythmStart(metrics,{})-9.6)<1e-9)
  assert.ok(Math.abs(summarySeconds(metrics,{})-15.6)<1e-9)
})
