import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const source = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

test('照片线路 V2 接入正式应用壳并保留离开前保存保护', async () => {
  const app = await source('App.vue')
  assert.match(app, /import PhotoRoutesV2Page from/)
  assert.match(app, /activePage === 'photo-routes'/)
  assert.match(app, /photoPage\.value\?\.beforeLeave\(\)/)
})

test('桌面提供照片线路主入口，移动端仍保持五项底栏并归入资产', async () => {
  const shell = await source('components/AppShell.vue')
  assert.match(shell, /key: 'photo-routes', label: '照片线路'/)
  assert.match(shell, /\['boards', 'library', 'photo-routes'\]\.includes/)
  assert.match(shell, /const mobileItems = \[[\s\S]*?\n\]/)
  assert.equal((shell.match(/short:/g) || []).length, 5)
})

test('照片线路使用黄色设计变量与中性技术岩板，不再使用木纹或青绿色基调', async () => {
  const [page, board] = await Promise.all([
    source('components/PhotoRoutesV2Page.vue'),
    source('components/PhotoRouteBoardCanvas.vue'),
  ])
  const combined = `${page}\n${board}`
  assert.match(combined, /var\(--ui-brand\)/)
  assert.match(combined, /var\(--ui-board-face\)/)
  assert.doesNotMatch(combined, /photo-wall-birch|--wood|#195f70|#0d7184/i)
})
