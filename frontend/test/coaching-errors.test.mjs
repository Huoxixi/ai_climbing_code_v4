import test from 'node:test'
import assert from 'node:assert/strict'
import { coachingErrorMessage } from '../src/services/coachingErrors.js'

const response = (status, detail) => ({ response: { status, data: { detail } } })
const fallback = '操作暂未完成，请重试。'

test('功能接口缺失与复盘记录不可用的 404 给出不同处理方式', () => {
  const failure = response(404, 'Not Found')
  assert.match(coachingErrorMessage(failure, fallback, 'policy'), /更新或重启本地服务/)
  assert.match(coachingErrorMessage(failure, fallback, 'report'), /刷新复盘列表/)
  assert.doesNotMatch(coachingErrorMessage(failure, fallback), /Not Found|尚无报告/)
})

test('登录失效不显示成记录缺失或未配置', () => {
  assert.equal(coachingErrorMessage(response(401, 'Unauthorized'), fallback, 'policy'), '登录状态已失效，请重新登录后读取个性化复盘。')
})

test('网络中断和请求超时提示核对服务与报告状态，不声称生成失败', () => {
  assert.match(coachingErrorMessage({ code: 'ERR_NETWORK', request: {} }, fallback), /无法连接/)
  assert.match(coachingErrorMessage({ code: 'ECONNABORTED', request: {} }, fallback), /读取报告状态/)
  assert.match(coachingErrorMessage({ code: 'ETIMEDOUT' }, fallback), /请求超时/)
})

test('保留中文业务错误并翻译通用服务器错误', () => {
  for (const [status, detail] of [[409, '已有报告正在生成，请等待完成或先停止。'], [503, '个性化复盘服务尚未配置，请联系服务管理员。']]) {
    assert.equal(coachingErrorMessage(response(status, detail), fallback), detail)
  }
  assert.equal(coachingErrorMessage(response(502, 'Bad Gateway'), fallback), '个性化复盘服务暂时不可用，请稍后重试。')
  assert.equal(coachingErrorMessage(response(422, [{ msg: 'validation error' }]), fallback), fallback)
  assert.equal(coachingErrorMessage(new Error('internal error'), fallback), fallback)
})
