import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { isHeifPhoto } from '../src/utils/mediaNormalize.js'

const source = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('正式抱石流程接入应用壳并保留离开前保存保护', async () => {
  const [app, page, viewport] = await Promise.all([
    source('App.vue'),
    source('components/PhotoRouteWorkflowPage.vue'),
    source('components/PhotoReviewViewport.vue'),
  ])
  assert.match(app, /import PhotoRouteWorkflowPage from/)
  assert.match(app, /v-else-if="isPhotoPage"/)
  assert.match(app, /photoPage\.value\?\.beforeLeave\(\)/)
  assert.match(app, /pushState/)
  assert.match(page, /parsePhotoWorkflowHash/)
  assert.match(page, /photoWorkflowHash/)
  assert.match(page, /visibleProcessingSteps/)
  assert.match(page, /v-for="step in visibleProcessingSteps"/)
  assert.doesNotMatch(page, /<li :class="\{'is-done':session\.progress>=20\}">上传照片<\/li>/)
  assert.doesNotMatch(page, /点一个岩点，整理出一条线路。/)
  // 2026-10-09《整图选线与可选岩点复盘》：旧取色草稿迁移到整图识别，识别后逐点选线。
  assert.match(page, /请先点击一个岩点/)
  assert.match(page, /v-else-if="session\.status==='awaiting_color'"/)
  assert.match(page, /识别照片中的全部岩点/)
  assert.match(page, /v-if="session\.flow_version<2"[^>]*>\{\{adding\?'请点击照片中的遗漏岩点':'添加遗漏岩点'/)
  assert.match(page, /act\('recognize-all'\)/)
  assert.match(page, /运行岩点专项模型/)
  assert.match(page, /全部完成后才会进入点击选线/)
  assert.match(page, /点按选择或取消路线岩点/)
  assert.match(page, /members\.includes\(selected\)\?'移出当前线路':'加入线路'/)
  assert.match(page, /显示荧光轮廓/)
  assert.match(page, /保存修改/)
  assert.match(page, /photo-work__save-bar/)
  assert.match(page, /photo-work__mobile-command/)
  assert.match(page, /photoObjectLabel/)
  assert.match(page, /@keydown\.space\.prevent/)
  assert.match(page, /:disabled="!editable"/)
  assert.match(page, /workflow\.discardPending/)
  assert.match(page, />返回</)
  assert.doesNotMatch(page, /电子岩板|确认位置|点位校准|PhotoRouteBoardCanvas|孔位辅助网格/)
  assert.match(page, /alt="已保存线路原图"/)
  assert.doesNotMatch(page, /完整线路照片始终保留/)
  assert.doesNotMatch(page, /线路至少需要一个起点和一个终点/)
  assert.match(viewport, /:class="\{ 'is-zoomed': zoom > 1 \}"/)
  assert.match(viewport, /touch-action:pan-y/)
  assert.match(viewport, /\.photo-review-viewer__viewport\.is-zoomed \{ touch-action:none; \}/)
})

test('抱石与原定线项目使用互相隔离的导航', async () => {
  const [shell, app, page] = await Promise.all([source('components/AppShell.vue'), source('App.vue'), source('components/PhotoRouteWorkflowPage.vue')])
  assert.match(shell, /props\.workspace === 'boulder'/)
  assert.match(shell, /key: 'photo-routes', label: '拍照定线'/)
  assert.match(shell, /key: 'my-records', label: '我的记录'/)
  assert.doesNotMatch(shell, /key: 'account'/)
  assert.match(shell, /v-if="!localWorkspaceOnly"/)
  assert.doesNotMatch(shell, /抱石社区|communityEnabled|ChatDotRound/)
  assert.doesNotMatch(shell, /释放编辑权/)
  assert.match(shell, /const boulderItems/)
  assert.match(shell, /const setterDesktopItems/)
  assert.doesNotMatch(shell.match(/const setterDesktopItems = \[([\s\S]*?)\n\]/)?.[1] || '', /photo-routes/)
  assert.match(shell, /\['boards', 'library'\]\.includes/)
  assert.match(app, /boulder: \['photo-routes', 'my-records'/)
  assert.doesNotMatch(app, /VITE_ENABLE_BOULDER_COMMUNITY|BoulderCommunityPage/)
  assert.doesNotMatch(app, /<AccountPage/)
  assert.match(app, /<SettingsPage/)
  assert.match(app, /setter: \['dashboard', 'studio', 'library', 'boards', 'standard-board', 'simulation', 'ai-lab', 'settings'\]/)
  assert.match(app, /workspacePages\[props\.workspace\]\.includes/)
  assert.match(app, /nextPage === 'my-records'/)
  assert.match(page, /emit\('navigate','my-records'/)
  assert.match(page, />我的记录</)
  assert.match(page, /defineExpose\(\{beforeLeave,openCurrent,returnCurrent,openLibrary\}\)/)
})

test('线路记录使用完整线路列表并支持多照片和多视频', async () => {
  const page = await source('components/PhotoRouteWorkflowPage.vue')
  assert.match(page, /class="photo-work__library-grid"/)
  assert.match(page, /photoV2AssetUrl\(libraryBoard\(route\)\.original_asset\)/)
  assert.match(page, /v-for="obj in libraryRouteObjects\(route\)"/)
  assert.match(page, /route\.updated_at \|\| route\.created_at/)
  assert.match(page, /class="record-media__grid"/)
  assert.match(page, /multiple accept="video\/mp4,video\/quicktime,video\/webm"/)
  assert.match(page, /image\/heic,image\/heif/)
  assert.match(page, /系统会转换 HEIC\/HEIF/)
  assert.match(page, /照片最多 8 张，视频最多 2 个/)
  assert.match(page, /此资料入口暂不自动转码/)
  assert.match(page, /@error="mediaPlaybackErrors\[item\.id\] = true"/)
  assert.match(page, /grid-template-columns:118px minmax\(0,1fr\) 18px/)
  assert.match(page, /stroke:#fff;stroke-width:1\.4/)
  assert.match(page, /drop-shadow\(0 0 4px rgba\(255,255,255,\.8\)\)/)
})

test('手机与本机HEIC原图保持不变，后台转换请求留出处理时间', async () => {
  const [page, service, workflow] = await Promise.all([
    source('components/PhotoRouteWorkflowPage.vue'),
    source('services/photoRouteService.js'),
    source('composables/usePhotoWorkflow.js'),
  ])
  assert.match(page, /本机选择的原图不会修改/)
  assert.match(page, /手机里的原图不会修改/)
  assert.match(page, /JPG、PNG、WebP 或 HEIC/)
  assert.equal(isHeifPhoto({ name: 'wall.HEIC', type: '' }), true)
  assert.equal(isHeifPhoto({ name: 'wall', type: 'image/heif' }), true)
  assert.equal(isHeifPhoto({ name: 'wall.jpg', type: 'image/jpeg' }), false)
  assert.match(service, /boards\/upload', body, \{ timeout: 120000 \}/)
  assert.match(service, /\/complete`, null, \{ timeout: 120000 \}/)
  assert.match(workflow, /root\+'\/upload',body,\{timeout:120000/)
})

test('当前照片流程使用黄色设计变量与中性表面，不再使用木纹或青绿色基调', async () => {
  const page = await source('components/PhotoRouteWorkflowPage.vue')
  assert.match(page, /var\(--ui-brand\)/)
  assert.match(page, /var\(--ui-surface\)/)
  assert.doesNotMatch(page, /photo-wall-birch|--wood|#195f70|#0d7184/i)
})
