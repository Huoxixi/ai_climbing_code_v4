import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '../services/apiClient'

export function useRouteGeneration() {
  const loading = ref(false)
  const taskId = ref(null)
  const result = ref(null)
  const error = ref('')
  const pollingTimer = ref(null)
  const status = ref('idle')
  const elapsedSeconds = ref(0)
  const startedAt = ref(0)

  function updateElapsed() {
    if (startedAt.value) elapsedSeconds.value = Math.max(0, Math.round((Date.now() - startedAt.value) / 1000))
  }

  async function generateRoute(payload) {
    loading.value = true
    error.value = ''
    result.value = null
    status.value = 'pending'
    elapsedSeconds.value = 0
    startedAt.value = Date.now()
    try {
      const response = await apiClient.post('/api/generate', payload)
      taskId.value = response.data?.task_id
      if (taskId.value) pollForResult(taskId.value)
    } catch (err) {
      error.value = err.response?.data?.detail || err.message
      ElMessage.error(`AI 生成请求失败：${error.value}`)
      loading.value = false
    }
  }

  function pollForResult(id) {
    clearInterval(pollingTimer.value)
    pollingTimer.value = setInterval(async () => {
      try {
        const response = await apiClient.get(`/api/result/${id}`)
        const taskStatus = response.data?.status
        updateElapsed()
        if (taskStatus) {
          // Preserve the server's real task state. The UI does not invent
          // algorithm stages that the backend cannot report.
          status.value = taskStatus
        }
        if (taskStatus === 'completed') {
          result.value = response.data?.result || null
          loading.value = false
          clearInterval(pollingTimer.value)
          ElMessage.success('AI 实验结果已返回')
          return
        }
        if (taskStatus === 'failed' || taskStatus === 'cancelled') {
          throw new Error(response.data?.error || '任务失败')
        }
      } catch (err) {
        error.value = err.response?.data?.detail || err.message
        if (status.value !== 'cancelled') status.value = 'failed'
        updateElapsed()
        loading.value = false
        clearInterval(pollingTimer.value)
        ElMessage.error(`AI 任务失败：${error.value}`)
      }
    }, 2000)
  }

  async function cancelGeneration() {
    if (!taskId.value) return
    try {
      await apiClient.post(`/api/cancel/${taskId.value}`)
      status.value = 'cancelled'
      updateElapsed()
      ElMessage.success('AI 任务已取消')
    } catch (err) {
      ElMessage.error(`取消失败：${err.response?.data?.detail || err.message}`)
    } finally {
      loading.value = false
      clearInterval(pollingTimer.value)
    }
  }

  return {
    loading,
    taskId,
    result,
    error,
    status,
    elapsedSeconds,
    generateRoute,
    cancelGeneration,
  }
}
