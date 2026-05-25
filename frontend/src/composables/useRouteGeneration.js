import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import apiClient from '../services/apiClient'

export function useRouteGeneration() {
  const loading = ref(false)
  const taskId = ref(null)
  const result = ref(null)
  const error = ref('')
  const pollingTimer = ref(null)

  async function generateRoute(payload) {
    loading.value = true
    error.value = ''
    result.value = null
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
        const status = response.data?.status
        if (status === 'completed') {
          result.value = response.data?.result || null
          loading.value = false
          clearInterval(pollingTimer.value)
          ElMessage.success('AI 实验结果已返回')
          return
        }
        if (status === 'failed' || status === 'cancelled') {
          throw new Error(response.data?.error || '任务失败')
        }
      } catch (err) {
        error.value = err.response?.data?.detail || err.message
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
    generateRoute,
    cancelGeneration,
  }
}
