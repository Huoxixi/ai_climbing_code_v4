import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const page = readFileSync(new URL('../src/components/ClimbReplayPage.vue', import.meta.url), 'utf8')
const service = readFileSync(new URL('../src/services/climbReplayService.js', import.meta.url), 'utf8')

test('复盘播放器可以独立开关岩点、采样骨架和接触事件', () => {
  assert.match(page, /v-model="showHolds"/)
  assert.match(page, /v-model="showPose"/)
  assert.match(page, /v-model="showEvents"/)
  assert.match(page, /pose_samples/)
  assert.match(page, /邻近实测采样 · 非插值/)
  assert.match(page, /currentPoseExact/)
})

test('接触事件能定位到原视频时间且复盘视频可导出', () => {
  assert.match(page, /event\.start_time_seconds/)
  assert.match(page, /seekToEvent/)
  assert.match(page, /导出复盘视频/)
  assert.match(service, /mediaUrl/)
  assert.match(service, /download=true/)
})

test('纯中文动作序列在原视频和叠加视频中都能精确跳帧', () => {
  assert.match(page, /v-if="playbackUrl && actionEvents\.length"/)
  assert.match(page, /sourceFrame \/ fps/)
  assert.match(page, /left\.seek_time_seconds - right\.seek_time_seconds/)
  assert.match(page, /videoElement\.value\.pause\(\)/)
  assert.match(page, /aria-current/)
  assert.match(page, /点一下定位/)
  assert.doesNotMatch(page, /<strong>\{\{ limbNames\[event\.limb\] \}\} · 岩点/)
})

test('当前动作控制台提供简单直接的逐步复盘操作并适配手机', () => {
  assert.match(page, /class="action-focus"/)
  assert.match(page, /当前动作/)
  assert.match(page, /@click="stepAction\(-1\)"/)
  assert.match(page, /@click="replayActiveAction"/)
  assert.match(page, /@click="stepAction\(1\)"/)
  assert.match(page, /playback-review\.has-action-focus\{grid-template-columns:minmax\(0,1fr\) 280px/)
  assert.match(page, /@media\(max-width:720px\).*playback-review\.has-action-focus\{grid-template-columns:1fr\}/)
  assert.match(page, /<RefreshRight \/>/)
})

test('保留手脚主标签并在旁边补充可靠的中文动作名称', () => {
  assert.match(page, /<strong>\{\{ limbNames\[event\.limb\] \|\| '手脚' \}\}<\/strong>/)
  assert.match(page, /<small>\{\{ event\.supplementary_name \}\}<\/small>/)
  assert.match(page, /inferSupplementaryActionName/)
  assert.match(page, /起步接触/)
  assert.match(page, /双手/)
  assert.match(page, /原点调整/)
  assert.match(page, /换点/)
})

test('原视频清理后回退到私密叠加视频且支持单独删除', () => {
  assert.match(page, /当前播放：复盘视频/)
  assert.match(page, /deleteOverlayVideo/)
  assert.match(page, /原视频、姿态数据和复盘指标仍会保留/)
  assert.match(service, /deleteOverlay/)
  assert.match(service, /media\/overlay-video/)
})

test('复盘记录默认优先播放复盘视频并保留原视频切换', () => {
  assert.match(page, /const preferredPlaybackKind = ref\('overlay'\)/)
  assert.match(page, /preferredPlaybackKind\.value === 'overlay' && replayVideoAvailable\.value/)
  assert.match(page, /playbackKind\.value === 'overlay'.*replayVideoUrl\.value/)
  assert.match(page, />复盘视频<\/button>/)
  assert.match(page, />原视频<\/button>/)
})

test('只有一种视频时按可用版本播放', () => {
  assert.match(page, /if \(replayVideoAvailable\.value\) return 'overlay'/)
  assert.match(page, /if \(sourceAvailable\.value\) return 'source'/)
  assert.match(page, /:disabled="!replayVideoAvailable"/)
  assert.match(page, /:disabled="!sourceAvailable"/)
})

test('本地案例记录优先使用已生成的最新对照版成片', () => {
  assert.match(page, /item\.comparison_available/)
  assert.match(page, /item\.comparison_route_color === activeJob\.value\?\.route_color/)
  assert.match(page, /Number\(item\.comparison_action_count\) === actionEvents\.value\.length/)
  assert.match(page, /climbReplayService\.comparisonVideoUrl\(comparisonCase\.value\.id\)/)
  assert.match(service, /test-videos\/\$\{encodeURIComponent\(caseId\)\}\/comparison/)
})

test('切换视频保留进度和播放状态且叠加失败自动回退原视频', () => {
  assert.match(page, /pendingPlaybackState\.value = capturePlaybackState\(\)/)
  assert.match(page, /video\.currentTime = Math\.max/)
  assert.match(page, /if \(state\.shouldPlay\) video\.play\(\)\.catch/)
  assert.match(page, /@error="handlePlaybackError"/)
  assert.match(page, /preferredPlaybackKind\.value = 'source'/)
  assert.match(page, /复盘视频暂时无法加载，已自动切换到原视频/)
})

test('切换后动作按钮继续控制同一个播放器', () => {
  assert.match(page, /@click="switchPlayback\('overlay'\)"/)
  assert.match(page, /@click="seekToEvent\(event\)"/)
  assert.match(page, /videoElement\.value\.currentTime = Math\.max/)
})
