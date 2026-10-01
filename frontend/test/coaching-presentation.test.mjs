import test from 'node:test'
import assert from 'node:assert/strict'
import { reportFocus, reportIsCurrent, noAdviceReasons, costLabel, poseCost, combinedCost, evidenceLabel, readableObservation } from '../src/services/coachingPresentation.js'

test('历史报告的首个动作不冒充重点，多帧核对必须有选择理由', () => {
  const item = { id: 'a', title: '脚部变化', start_seconds: 1, end_seconds: 2, evidence: [{}, {}] }
  const report = { result_status: 'review', observations: [item], next_attempt: { kind: 'review', text: '先看起步' } }
  assert.equal(reportFocus(report), null)
  report.next_attempt = { kind: 'review', observation_id: 'a', reason: '核对衔接', verification: '是否停顿' }
  assert.equal(reportFocus(report).item.id, 'a')
  item.evidence = []
  assert.equal(reportFocus(report), null)
})
test('只有当前合同可显示行动，旧报告、依据失效和媒体丢失都不能作为行动建议', () => {
  const report = { result_status: 'try', improvements: [{ adjustment: '构造方向', verification: '构造验证', independent_review: { status: 'verified' } }, { adjustment: '不应出现的第二项' }] }
  const envelope = { status: 'succeeded', report }
  assert.equal(reportIsCurrent(envelope), true)
  assert.equal(reportIsCurrent({ ...envelope, legacy: true }), false)
  assert.equal(reportIsCurrent({ ...envelope, stale: true }), false)
  assert.equal(reportIsCurrent(envelope, false), false)
  assert.equal(reportIsCurrent({ ...envelope, report: { improvements: report.improvements } }), false)
  assert.equal(reportFocus(report).text, '构造方向')
  assert.equal(reportFocus({ ...report, result_status: 'insufficient' }), null)
})
test('无建议说明具体原因，不用置信度代替证据状态', () => {
  assert.deepEqual(noAdviceReasons({ no_advice_reasons: [{ code: 'hidden_foot', message: '左脚被挡，无法确认落脚过程。' }] }), ['左脚被挡，无法确认落脚过程。'])
  assert.match(noAdviceReasons({ knowledge_status: { eligible_advice_claims: 0 } })[0], /没有通过审核/)
  assert.equal(evidenceLabel({ evidence_status: '鞋部被遮挡，不能判断换脚过程' }), '鞋部被遮挡，不能判断换脚过程')
})
test('费用未知不显示零，历史范围不显示实际账单', () => {
  assert.equal(costLabel(), '暂无法估算')
  assert.equal(costLabel({ status: 'range', amount_min: .068266, amount_max: .102399 }), '¥0.0683–¥0.1024')
  assert.equal(costLabel({ status: 'partial', known_amount: .02 }), '¥0.0200（已知部分）')
  assert.equal(combinedCost({ status: 'partial', known_amount: .02 }, { status: 'estimated', amount_min: .09, amount_max: .09 }), null)
  assert.equal(costLabel({ status: 'estimated', amount_min: null, amount_max: 0 }), '暂无法估算')
  const pose = poseCost({ result: { analysis: { cost: { currency: 'CNY', estimated_amount: .09 } } } })
  assert.equal(costLabel(pose), '¥0.0900')
  assert.equal(costLabel(combinedCost(pose, { status: 'estimated', amount_min: .02, amount_max: .02 })), '¥0.1100')
  assert.equal(combinedCost(pose, null), null)
  assert.equal(poseCost({ result: { analysis: { cost: { estimated_amount: 0 } } } }), null)
})
test('明确标注依赖和单帧限制，并简化过长的秒数', () => {
  assert.match(evidenceLabel({ observation: '骨架显示身体偏左' }), /需重新核对/)
  assert.match(evidenceLabel({ evidence: [{}] }), /单帧/)
  assert.equal(readableObservation('在0.266667秒画面中'), '在0.3 秒画面中')
})
