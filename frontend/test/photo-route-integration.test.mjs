import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const source = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('正式抱石流程接入应用壳并保留离开前保存保护', async () => {
  const [app, page, viewport] = await Promise.all([
    source('App.vue'),
    source('components/PhotoRouteWorkflowPage.vue'),
    source('components/PhotoReviewViewport.vue'),
  ])
  assert.match(app, /import PhotoRouteWorkflowPage from/)
  assert.match(app, /activePage === 'photo-routes'/)
  assert.match(app, /photoPage\.value\?\.beforeLeave\(\)/)
  assert.match(app, /pushState/)
  assert.match(page, /parsePhotoWorkflowHash/)
  assert.match(page, /photoWorkflowHash/)
  assert.match(page, /visibleProcessingSteps/)
  assert.match(page, /v-for="step in visibleProcessingSteps"/)
  assert.doesNotMatch(page, /<li :class="\{'is-done':session\.progress>=20\}">上传照片<\/li>/)
  assert.match(page, /<p v-if="surfaceState === 'awaiting_color'">点一个岩点，整理出一条线路。<\/p>/)
  assert.match(page, /先点击照片中的一个岩点/)
  assert.match(page, /黄线是识别到的岩点边缘/)
  assert.match(page, /保存修改/)
  assert.match(page, /photo-work__save-bar/)
  assert.match(page, /photo-work__mobile-command/)
  assert.match(page, /photoObjectLabel/)
  assert.match(page, /@keydown\.space\.prevent/)
  assert.match(page, /:disabled="!editable"/)
  assert.match(page, /workflow\.discardPending/)
  assert.match(page, />返回</)
  assert.doesNotMatch(page, /电子岩板|确认位置|点位校准|PhotoRouteBoardCanvas|孔位辅助网格/)
  assert.match(page, /删除只移出当前线路/)
  assert.doesNotMatch(page, /线路至少需要一个起点和一个终点/)
  assert.match(viewport, /:class="\{ 'is-zoomed': zoom > 1 \}"/)
  assert.match(viewport, /touch-action:pan-y/)
  assert.match(viewport, /\.photo-review-viewer__viewport\.is-zoomed \{ touch-action:none; \}/)
})

test('桌面保留抱石线路入口，移动端并入五项定线导航', async () => {
  const shell = await source('components/AppShell.vue')
  assert.match(shell, /key: 'photo-routes', label: '抱石线路'/)
  assert.match(shell, /\['boards', 'library'\]\.includes/)
  assert.match(shell, /\['studio', 'photo-routes'\]\.includes/)
  assert.match(shell, /class="mobile-route-switch"/)
  assert.match(shell, />岩板定线</)
  assert.match(shell, />照片线路</)
  assert.match(shell, /const mobileItems = \[[\s\S]*?\n\]/)
  assert.equal((shell.match(/short:/g) || []).length, 5)
  const mobileItems = shell.match(/const mobileItems = \[([\s\S]*?)\n\]/)?.[1] || ''
  assert.doesNotMatch(mobileItems, /photo-routes/)
})

test('抱石线路使用黄色设计变量与中性技术岩板，不再使用木纹或青绿色基调', async () => {
  const [page, board] = await Promise.all([
    source('components/PhotoRoutesV2Page.vue'),
    source('components/PhotoRouteBoardCanvas.vue'),
  ])
  const combined = `${page}\n${board}`
  assert.match(combined, /var\(--ui-brand\)/)
  assert.match(combined, /var\(--ui-board-face\)/)
  assert.doesNotMatch(combined, /photo-wall-birch|--wood|#195f70|#0d7184/i)
})
