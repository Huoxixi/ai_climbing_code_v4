// Shared replay page wording. Preserve saved-record labels and formatting behavior.
export function errorText(error) {
  if (error?.response?.status === 404) return '本地复盘服务尚未启用，请重新启动本地服务。'
  return error?.response?.data?.detail || error?.message || '操作失败，请稍后重试。'
}

export function poseVersionLabel(value) {
  const spec = value?.models?.pose || value?.analysis?.models?.pose?.name || ''
  const model = typeof spec === 'string' ? spec : spec?.name || ''
  if (model.startsWith('rtmw-l-384x288')) return 'RTMW-L · 本地骨架'
  if (model.startsWith('aliyun-viapi')) return '阿里云骨架 · 历史版本'
  return model ? '历史骨架版本' : '待使用 RTMW-L 分析'
}

export function formatClock(value) {
  const seconds = Math.max(0, Number(value || 0))
  const minutes = Math.floor(seconds / 60)
  return `${minutes}:${String(Math.floor(seconds % 60)).padStart(2, '0')}.${Math.floor((seconds % 1) * 10)}`
}

export function jobStatusLabel(job) {
  if (job.deletion?.state === 'queued') return '删除中'
  return ({ queued: '排队中', running: '处理中', awaiting_hold_review: '待确认岩点', succeeded: '已完成', failed: '失败', cancelled: '已取消' })[job.status] || job.status
}

export function dateLabel(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}
