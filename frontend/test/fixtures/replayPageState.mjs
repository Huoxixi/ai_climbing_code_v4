import { ref } from 'vue'
import { useReplayJobState, useReplayPlaybackState } from '../../src/composables/useReplayPageState.js'

export function replayPageState(job = null, overrides = {}) {
  const calls = []
  const inputs = {
    activeJob: ref(job), deletionReceipt: ref(null), uploadProgress: ref(0),
    limbNames: { left_hand: '左手', right_hand: '右手', left_foot: '左脚', right_foot: '右脚' },
    previewUrl: ref(''), preferredPlaybackKind: ref('overlay'), testVideoCases: ref([]), actionEvents: ref([]),
    ...overrides,
  }
  const service = {
    mediaUrl(id, kind, download = false) { calls.push([id, kind, download]); return `${id}/${kind}${download ? '?download' : ''}` },
    comparisonVideoUrl(id, download = false) { calls.push([id, 'comparison', download]); return `${id}/comparison${download ? '?download' : ''}` },
  }
  const state = useReplayJobState(inputs)
  return { ...inputs, calls, state: { ...state, ...useReplayPlaybackState(inputs, state, service) } }
}
