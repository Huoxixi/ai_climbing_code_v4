<template>
  <main>
    <header><h1>AI 复盘</h1><nav aria-label="素材切换"><a v-for="(item, key) in cases" :key="key" :href="`/analysis/${key}`" :aria-current="key === id ? 'page' : null">{{ item }}</a></nav></header>
    <p class="intro">保留基础复盘画面 · 动作解析随播放呈现</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="result">
      <ReplayVisualStage ref="stage" :src="`/base/${id}`" :groups="result.groups" :metrics="result.metrics" :motion-summary="result.motion_summary" :time="time" :summary="summary" :pinned="pinned" @reopen="showData(false)" @collapse="hideData"
        @timeupdate="tick" @ended="ended" @seeking="seeking" @play="startFrames" @pause="stopFrames" @loadedmetadata="loaded" @error="error = '视频载入失败，请刷新重试。'" />
      <div class="controls">
        <button @click="full">整段观看</button><button :disabled="selected < 0" @click="select(selected)">重看当前动作</button>
        <label>速度 <select v-model.number="speed" aria-label="播放速度" @change="setSpeed"><option :value="1">1×</option><option :value=".5">0.5×</option></select></label>
        <button @click="showData()">数据回顾</button><a :href="`/video/${id}`" download>下载分析视频</a>
      </div>
      <nav class="groups" aria-label="动作片段"><button v-for="(group, index) in result.groups" :key="group.id" :aria-pressed="selected === index" @click="select(index)"><b>{{ index + 1 }}</b><span>{{ group.start_seconds.toFixed(1) }}–{{ group.end_seconds.toFixed(1) }} 秒</span></button></nav>
      <details><summary>核对记录与基础视频</summary><p>{{ note }}</p><p>字幕只使用当前核对通过的事件；仍有漏识别的片段没有补造动作。岩点计数来自自动候选，不等于人工确认。</p><a :href="`/base/${id}`" target="_blank">查看基础复盘视频</a><p>结尾数据不计入原视频时长。</p></details>
    </template>
  </main>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import ReplayVisualStage from './ReplayVisualStage.vue'
import { summarySeconds } from '../services/replayPresentation.js'
const cases = { current: '素材一', case1: '素材二', case3: '素材三' }
const id = location.pathname.split('/').at(-1) in cases ? location.pathname.split('/').at(-1) : 'case3'
const result = ref(null), note = ref(''), error = ref(''), stage = ref(null), time = ref(0), speed = ref(1), summary = ref(false), selected = ref(-1)
const video = computed(() => stage.value?.video)
const pinned = ref(false)
let timer, frame
function stopFrames() { if (frame != null) video.value?.cancelVideoFrameCallback?.(frame); frame = null }
function startFrames() { hideData(); stopFrames(); const update = () => { tick(); if (video.value && !video.value.paused) frame = video.value.requestVideoFrameCallback(update) }; if (video.value?.requestVideoFrameCallback) frame = video.value.requestVideoFrameCallback(update) }
function hideData() { clearTimeout(timer); summary.value = false }
async function showData(autoClose = true) { hideData(); video.value?.pause(); await nextTick(); pinned.value = !autoClose; summary.value = true; if (autoClose) timer = setTimeout(hideData, summarySeconds(result.value.metrics, result.value.motion_summary)*1000) }
function loaded() { setSpeed() }
function setSpeed() { if (video.value) video.value.playbackRate = speed.value }
function select(i) { selected.value = i; hideData(); const group = result.value.groups[i]; speed.value = .5; setSpeed(); video.value.currentTime = group.start_seconds; video.value.play().catch(()=>{}) }
function full() { selected.value = -1; hideData(); speed.value = 1; setSpeed(); video.value.currentTime = 0; video.value.play().catch(()=>{}) }
function tick() { time.value = video.value?.currentTime || 0; const group = result.value?.groups[selected.value]; if (group && !video.value.seeking && time.value >= group.end_seconds-.015) video.value.pause() }
function seeking() { hideData(); const group = result.value?.groups[selected.value]; if (group && (video.value.currentTime < group.start_seconds-.05 || video.value.currentTime > group.end_seconds+.05)) { selected.value = -1; speed.value = 1; setSpeed() } }
function ended() { if (selected.value < 0) showData() }
onMounted(async () => { try { const response = await fetch(`/analysis-data/${id}`); if (!response.ok) throw Error(); const data = await response.json(); result.value = data.result; note.value = data.note } catch { error.value = '分析记录无法载入，请刷新重试。' } })
onBeforeUnmount(() => { clearTimeout(timer); stopFrames() })
</script>
<style scoped>
main { max-width: 1100px; padding: 24px 24px 96px; margin: 0 auto; color: #f7fafb; font-family: 'Replay Noto', 'Noto Sans SC', sans-serif; }
:global(body:has(.replay-data-orb)) .controls a { margin-right: 80px; }
header { display: flex; align-items: center; justify-content: space-between; gap: 20px; }h1 { font-size: 24px; font-weight: 650; margin: 0; letter-spacing: -.025em; }header nav { display: flex; gap: 20px; font-size: 14px; }a { color: #b7d8df; text-underline-offset: 5px; }a[aria-current] { color: #fff; text-decoration-thickness: 2px; }.intro { margin: 6px 0 24px; color: #b4c8cd; font-size: 13px; }
.controls { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; padding: 18px 0; }.controls a { margin-left: auto; font-size: 14px; }button,select { color: #f7fafb; font: inherit; font-size: 14px; border: 1px solid #435960; background: #18262c; border-radius: 6px; min-height: 42px; padding: 8px 13px; cursor: pointer; }button:hover:not(:disabled),select:hover { background: #293e47; }button:disabled { opacity: .4; cursor: default; }button:focus-visible,select:focus-visible,a:focus-visible,summary:focus-visible { outline: 2px solid #7cdee5; outline-offset: 4px; }.groups { display: flex; gap: 10px; }.groups button { flex: 1; display: flex; align-items: center; gap: 12px; text-align: left; }.groups b { color: #7cdee5; }.groups span { font-size: 12px; color: #b4c8cd; font-variant-numeric: tabular-nums; }.groups button[aria-pressed=true] { border-color: #7cdee5; }details { margin-top: 24px; color: #b4c8cd; font-size: 13px; line-height: 1.8; }summary { cursor: pointer; }p { max-width: 70ch; }::selection { background: #7cdee5; color: #102025; }
@media(max-width:650px) { main { padding: 14px 14px 96px; }header nav { gap: 12px; }.intro { margin-bottom: 16px; }.controls { gap: 8px; }.controls a { margin-left: 0; }.groups button { flex-direction: column; align-items: start; gap: 3px; padding: 8px; }.groups span { font-size: 11px; } }
</style>
