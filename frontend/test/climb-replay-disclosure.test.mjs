import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { parse, compileTemplate } from 'vue/compiler-sfc'

const source = readFileSync(new URL('../src/components/ClimbReplayPage.vue', import.meta.url), 'utf8')
const { descriptor, errors } = parse(source)
const root = descriptor.template.ast
const elements = []
function visit(node, ancestors = []) {
  if (node.type === 1) elements.push({ node, ancestors })
  for (const child of node.children || []) visit(child, node.type === 1 ? [...ancestors, node] : ancestors)
}
visit(root)
const attribute = (node, name) => node.props.find(prop => prop.type === 6 && prop.name === name)?.value?.content
const directive = (node, name, arg) => node.props.find(prop => prop.type === 7 && prop.name === name && (!arg || prop.arg?.content === arg))?.exp?.content
const hasClass = (node, name) => (attribute(node, 'class') || '').split(/\s+/).includes(name)
const findClass = name => elements.find(({ node }) => hasClass(node, name))

test('精简后的复盘模板可以编译，低频内容使用默认关闭的原生折叠', () => {
  assert.deepEqual(errors, [])
  assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename: 'ClimbReplayPage.vue', id: 'replay-test' }).errors, [])
  for (const name of ['result-details', 'media-retention']) {
    const { node } = findClass(name)
    assert.equal(node.tag, 'details', name)
    assert.equal(node.props.some(prop => (prop.type === 6 && prop.name === 'open') || (prop.type === 7 && prop.arg?.content === 'open')), false, name)
    assert.equal(node.children.find(child => child.type === 1)?.tag, 'summary', name)
  }
  assert.equal(findClass('analysis-evidence'), undefined)
})

test('视频、当前动作、动作顺序、状态和上传入口不会被折叠隐藏', () => {
  for (const name of ['video-stage', 'action-focus', 'event-timeline', 'analysis-state', 'primary-action']) {
    const match = elements.find(({ node, ancestors }) => hasClass(node, name) && !ancestors.some(parent => parent.tag === 'details'))
    assert.ok(match, name)
    assert.equal(match.ancestors.some(node => node.tag === 'details'), false, name)
  }
  const consent = elements.find(({ node }) => directive(node, 'model') === 'sampleConsent')
  assert.equal(consent, undefined)
  assert.equal(findClass('shooting-guide'), undefined)
  assert.equal(findClass('retention-options'), undefined)
})

test('统一复盘保留文件管理，旧手动动作编辑退出主流程', () => {
  const expected = {
    'deleteSourceVideo': 'media-retention',
    'deleteOverlayVideo': 'media-retention',
    'deleteEntireReplay': 'replay-record-toolbar',
  }
  for (const [handler, parent] of Object.entries(expected)) {
    const match = elements.find(({ node }) => directive(node, 'on', 'click') === handler)
    assert.ok(match, handler)
    assert.ok(match.ancestors.some(node => hasClass(node, parent)), handler)
  }
  const exportLink = findClass('export-action')
  assert.equal(exportLink.ancestors.some(node => node.tag === 'details'), false)
  assert.equal(findClass('segment-review'), undefined)
  assert.match(source, /<UnifiedReplayPlayer/)
})

test('历史以常驻入口打开分页面板，不挤走当前视频', () => {
  const entry = elements.find(({ node, ancestors }) => directive(node, 'on', 'click') === 'historyOpen=true' && ancestors.some(parent => hasClass(parent, 'replay-heading-actions')))
  assert.ok(entry)
  const history = elements.find(({ node }) => node.tag === 'WorkspaceSheet' && directive(node, 'if') === 'historyOpen')
  assert.ok(history)
  assert.match(source, /v-for="job in pageJobs"/)
  assert.equal(directive(findClass('replay-detail-sections').node, 'bind', 'key'), 'activeJob.id')
  assert.equal(directive(findClass('result-details').node, 'bind', 'key'), 'activeJob.id')
  const row = elements.find(({ node, ancestors }) => directive(node, 'for') === 'job in pageJobs' && ancestors.includes(history.node))
  assert.ok(row)
  assert.equal(directive(row.node, 'bind', 'key'), 'job.id')
  assert.equal(directive(row.node, 'on', 'click'), 'selectJob(job);historyOpen=false')
  const pagination = elements.find(({ node, ancestors }) => attribute(node, 'aria-label') === '分析历史分页' && ancestors.includes(history.node))
  assert.ok(pagination)
  assert.ok(elements.some(({ node, ancestors }) => directive(node, 'on', 'click') === 'historyPage--' && directive(node, 'bind', 'disabled') === 'historyPage===0' && ancestors.includes(pagination.node)))
  assert.ok(elements.some(({ node, ancestors }) => directive(node, 'on', 'click') === 'historyPage++' && directive(node, 'bind', 'disabled') === '(historyPage+1)*5>=recentJobs.length' && ancestors.includes(pagination.node)))
})

test('处理诊断退出用户页面，保留折叠标题的键盘焦点与移动端换行', () => {
  assert.equal(findClass('run-summary'), undefined)
  assert.equal(findClass('analysis-evidence'), undefined)
  assert.match(source, /:is\(button,input,select,a,summary\):focus-visible/)
  assert.match(source, /\.disclosure-meta\{[^}]*overflow-wrap:anywhere/)
  assert.match(source, /@media\(max-width:520px\).*\.replay-disclosure>summary/)
  assert.match(source, /prefers-reduced-motion:reduce.*\.disclosure-chevron\{transition:none/)
  assert.equal(elements.filter(({ node, ancestors }) => node.tag === 'details' && hasClass(node, 'replay-disclosure') && ancestors.some(parent => hasClass(parent, 'replay-disclosure'))).length, 0)
})
