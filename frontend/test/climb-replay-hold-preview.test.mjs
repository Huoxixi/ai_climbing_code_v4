import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const page = readFileSync(new URL('../src/components/ClimbReplayPage.vue', import.meta.url), 'utf8')
const service = readFileSync(new URL('../src/services/climbReplayService.js', import.meta.url), 'utf8')

test('拖框补点先预览轮廓，逐点确认保存草稿，全部确认后再分析', () => {
  assert.match(service, /previewHoldAtPoint:.*holds\/point\/preview/)
  assert.match(service, /region_xyxy:regionXyxy/)
  assert.match(page, /@pointerdown="startHoldDraw"/)
  assert.match(page, /@pointermove="moveHoldDraw"/)
  assert.match(page, /@pointerup="finishHoldDraw"/)
  assert.match(page, /<polygon :points="holdPreviewPoints"/)
  assert.match(page, /@click="confirmHoldPreview"/)
  assert.match(page, /aria-label="取消候选岩点"[^>]*@click="holdPreview=null">取消/)
  const previewHandler = page.split('async function previewHoldRegion(region) {')[1]
    .split('async function confirmHoldPreview() {')[0]
  assert.match(previewHandler, /climbReplayService\.previewHoldAtPoint/)
  assert.doesNotMatch(previewHandler, /climbReplayService\.addHoldAtPoint/)
  assert.match(page, /async function confirmHoldPreview\(\) {[\s\S]*?climbReplayService\.addHoldAtPoint\(jobId, point, previousTime, region, proposalId\)/)
})
