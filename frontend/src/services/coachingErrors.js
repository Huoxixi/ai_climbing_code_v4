const genericDetails = new Set(['not found', 'unauthorized', 'forbidden', 'internal server error', 'bad gateway', 'service unavailable', 'gateway timeout'])

export function coachingErrorMessage(failure, fallback, resource = 'report') {
  const status = failure?.response?.status
  if (status === 401) return '登录状态已失效，请重新登录后读取个性化复盘。'
  if (status === 404) {
    return ['policy', 'preflight'].includes(resource)
      ? '个性化复盘服务尚未加载。请更新或重启本地服务后重新读取。'
      : '当前复盘记录不可用，可能已删除或无法访问。请刷新复盘列表后重新选择。'
  }
  if (['ECONNABORTED', 'ETIMEDOUT'].includes(failure?.code)) return '请求超时，请重新读取报告状态后再决定是否重试。已发送的请求可能计费，重试可能追加费用。'
  if (!failure?.response && (failure?.code === 'ERR_NETWORK' || failure?.request)) return '暂时无法连接个性化复盘服务，请确认网络和本地服务正常后重新读取。'

  const detail = failure?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim() && !genericDetails.has(detail.trim().toLowerCase())) return detail
  if (status === 403) return '暂时无法访问这份复盘，请重新登录后重试。'
  if (status === 429) return '请求次数已达到限制，请稍后重新查询任务状态，避免重复生成。'
  if (status >= 500) return '个性化复盘服务暂时不可用，请稍后重试。'
  return fallback
}
