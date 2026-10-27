import assert from 'node:assert/strict'
import { access, readFile } from 'node:fs/promises'
import test from 'node:test'

const read = (path) => readFile(new URL(path, import.meta.url), 'utf8')

test('本地与完整应用分别加载各自样式入口，真实页面继续接管', async () => {
  const [main, app, localStyle, fullStyle] = await Promise.all([
    read('../src/main.js'),
    read('../src/App.vue'),
    read('../src/styles/local-app.css'),
    read('../src/styles/full-app.css'),
  ])
  assert.match(main, /VITE_LOCAL_BOULDER_ONLY === 'true'/)
  assert.match(main, /import\('\.\/styles\/local-app\.css'\)/)
  assert.match(main, /import\('\.\/styles\/full-app\.css'\)/)
  assert.match(main, /import LocalRoot from '\.\/LocalRoot\.vue'/)
  assert.match(fullStyle, /@import '\.\.\/style\.css'/)
  assert.match(fullStyle, /@import '\.\/redesign\.css'/)
  assert.match(localStyle, /@import '\.\/boulder-workspace\.css'/)
  assert.doesNotMatch(localStyle, /redesign\.css|\.\.\/style\.css/)
  assert.doesNotMatch(main + localStyle + fullStyle, /styles\/skeleton\.css/)
  assert.doesNotMatch(app, /uiSkeletonCheckpoint|UiSkeletonPage/)
  for (const component of ['DashboardPage', 'StudioPage', 'HoldLibraryPage', 'BoardsPage', 'StandardBoardPage', 'AILabPage']) {
    assert.match(app, new RegExp(`import ${component}`))
  }
})

test('界面字体改为官方原始 MiSans WOFF2 并保留来源说明', async () => {
  const [tokens, notice] = await Promise.all([
    read('../src/styles/tokens.css'),
    read('../public/fonts/NOTICE.md'),
  ])
  for (const name of ['Regular', 'Medium', 'Semibold']) {
    assert.match(tokens, new RegExp(`MiSans-${name}\\.woff2`))
    await access(new URL(`../public/fonts/MiSans-${name}.woff2`, import.meta.url))
  }
  assert.match(notice, /hyperos\.mi\.com\/font/)
  assert.doesNotMatch(tokens + notice, /NotoSansSC/)
})

test('生产界面使用不声明实体材质的中性技术画布', async () => {
  const [tokens, board, entry] = await Promise.all([
    read('../src/styles/tokens.css'),
    read('../src/components/BoardCanvas.vue'),
    read('../src/styles/redesign.css'),
  ])
  assert.match(tokens, /--ui-board-face: #e8eaed/)
  assert.match(tokens, /--ui-board-frame: #c9cdd2/)
  assert.match(tokens, /--ui-board-hole: #2b2f33/)
  assert.match(board + entry, /board-frame/)
  assert.doesNotMatch(tokens + board + entry, /plywood|桦木|board-plywood/)
})

test('岩板外框按真实物理尺寸等比缩放而不是按孔阵数量变形', async () => {
  const [editor, entry, thumbnail] = await Promise.all([
    read('../src/composables/useStudioEditor.js'),
    read('../src/styles/redesign.css'),
    read('../src/components/BoardThumbnail.vue'),
  ])
  assert.match(editor, /--board-ratio.*board_width_mm.*board_height_mm/)
  assert.match(entry, /aspect-ratio: var\(--board-ratio, 2440 \/ 3660\)/)
  assert.match(thumbnail, /board-thumbnail-hole/)
  assert.doesNotMatch(thumbnail, /radial-gradient/)
})

test('已确认效果图方向契约随页面源文件交付', async () => {
  const index = await read('../index.html')
  assert.match(index, /DIRECTION CONTRACT: phase2-content-fill/)
  assert.match(index, /2440:3660/)
  assert.match(index, /phase2-dashboard-desktop \/ phase2-studio-mobile/)
})

test('标准线路预览可隐藏非线路岩点且不叠加额外标点', async () => {
  const [canvas, page, style] = await Promise.all([
    read('../src/components/BoardCanvas.vue'),
    read('../src/components/StandardBoardPage.vue'),
    read('../src/style.css'),
  ])
  assert.match(canvas, /showNonRouteHolds: \{ type: Boolean, default: true \}/)
  assert.match(canvas, /visibleBaseHolds/)
  assert.doesNotMatch(canvas, /hold-marker-badge/)
  assert.doesNotMatch(canvas + style, /route-hole-marker|visibleRouteMarkers/)
  assert.match(page, /climb-setter:standard-board:show-non-route-holds/)
  assert.match(page, /v-model="showNonRouteHolds">\u663e\u793a\u5176\u4ed6\u5ca9\u70b9/)
  assert.equal((page.match(/:show-non-route-holds="showNonRouteHolds"/g) || []).length, 3)
})
