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
  assert.match(page, /session\.status==='awaiting_color' && session\.flow_version<2/)
  assert.match(page, /使用专项模型重新识别/)
  assert.match(page, /v-if="session\.flow_version<2"[^>]*>\{\{adding\?'请点击照片中的遗漏岩点':'添加遗漏岩点'/)
  assert.match(page, /act\('reprocess'\)/)
  assert.match(page, /运行岩点专项模型/)
  assert.match(page, /全部完成后才会进入点击选线/)
  assert.match(page, /确认\{\{previewColor/)
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

test('抱石与原定线项目使用互相隔离的导航', async () => {
  const [shell, app, page] = await Promise.all([source('components/AppShell.vue'), source('App.vue'), source('components/PhotoRouteWorkflowPage.vue')])
  assert.match(shell, /props\.workspace === 'boulder'/)
  assert.match(shell, /key: 'photo-routes', label: '照片线路'/)
  assert.match(shell, /key: 'photo-routes', short: '添加线路'/)
  assert.match(shell, /key: 'photo-library', short: '线路库'/)
  assert.match(shell, /props\.photoSection === 'library'/)
  assert.match(shell, /const setterDesktopItems/)
  assert.doesNotMatch(shell.match(/const setterDesktopItems = \[([\s\S]*?)\n\]/)?.[1] || '', /photo-routes/)
  assert.match(shell, /\['boards', 'library'\]\.includes/)
  assert.match(app, /boulder: \['photo-routes', 'settings'\]/)
  assert.match(app, /setter: \['dashboard', 'studio', 'library', 'boards', 'standard-board', 'simulation', 'ai-lab', 'settings'\]/)
  assert.match(app, /workspacePages\[props\.workspace\]\.includes/)
  assert.match(app, /nextPage === 'photo-library'/)
  assert.match(page, /defineExpose\(\{beforeLeave,openCurrent,returnCurrent,openLibrary\}\)/)
})

test('手机线路库使用双列照片画廊并以白色细荧光描出线路岩点', async () => {
  const page = await source('components/PhotoRouteWorkflowPage.vue')
  assert.match(page, /class="photo-work__library-grid"/)
  assert.match(page, /photoV2AssetUrl\(libraryBoard\(route\)\.original_asset\)/)
  assert.match(page, /v-for="obj in libraryRouteObjects\(route\)"/)
  assert.match(page, /route\.updated_at \|\| route\.created_at/)
  assert.match(page, /grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/)
  assert.match(page, /stroke:#fff;stroke-width:1\.4/)
  assert.match(page, /drop-shadow\(0 0 4px rgba\(255,255,255,\.8\)\)/)
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
