import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import apiClient from '../services/apiClient'

export const HOLD_TYPES = ['Jug', 'Crimp', 'Sloper', 'Pinch', 'Pocket', 'Foot']

export function useHoldLibrary() {
  const holdImageMap = reactive({})
  const holdVectorMap = reactive({})
  const holdAssets = ref([])
  const loading = ref(false)
  const uploadInfo = reactive({ hold_type: 'Jug', variant: '', file: null })
  const search = ref('')
  const typeFilter = ref('All')
  const previewMode = ref('vector')
  const showArchived = ref(false)

  const managedHolds = computed(() => {
    return holdAssets.value
      .filter((hold) => Boolean(hold.archived_at) === showArchived.value)
      .map((hold) => ({ ...hold, type: hold.hold_type }))
      .sort((a, b) => `${a.hold_type}-${a.variant}`.localeCompare(`${b.hold_type}-${b.variant}`))
  })

  const filteredHolds = computed(() => {
    const needle = search.value.trim().toLowerCase()
    return managedHolds.value.filter((hold) => {
      const matchesType = typeFilter.value === 'All' || hold.hold_type === typeFilter.value
      const matchesSearch = !needle || `${hold.hold_type} ${hold.variant}`.toLowerCase().includes(needle)
      return matchesType && matchesSearch
    })
  })

  async function fetchHoldMapping() {
    const response = await apiClient.get('/api/holds/mapping')
    Object.keys(holdImageMap).forEach((key) => delete holdImageMap[key])
    Object.assign(holdImageMap, response.data || {})
  }

  async function fetchHoldVectors() {
    const response = await apiClient.get('/api/holds/vectors')
    Object.keys(holdVectorMap).forEach((key) => delete holdVectorMap[key])
    Object.assign(holdVectorMap, response.data || {})
  }

  async function fetchAllHoldData() {
    loading.value = true
    try {
      const [, , assetsResponse] = await Promise.all([
        fetchHoldMapping(),
        fetchHoldVectors(),
        apiClient.get('/api/holds/assets', { params: { include_archived: true } }),
      ])
      holdAssets.value = Array.isArray(assetsResponse.data) ? assetsResponse.data : []
    } catch (error) {
      ElMessage.error(`岩点库刷新失败：${error.response?.data?.detail || error.message}`)
    } finally {
      loading.value = false
    }
  }

  async function uploadImage() {
    if (!uploadInfo.file || !uploadInfo.variant.trim()) {
      ElMessage.warning('请选择文件并填写变体名称')
      return
    }

    const formData = new FormData()
    formData.append('file', uploadInfo.file)
    formData.append('hold_type', uploadInfo.hold_type)
    formData.append('variant', uploadInfo.variant.trim())

    loading.value = true
    try {
      const response = await apiClient.post('/api/holds/upload', formData)
      ElMessage.success(response.data?.background_removed ? '岩点上传成功，白色背景已自动去除' : '岩点上传成功')
      uploadInfo.variant = ''
      uploadInfo.file = null
      await fetchAllHoldData()
    } catch (error) {
      ElMessage.error(`上传失败：${error.response?.data?.detail || error.message}`)
    } finally {
      loading.value = false
    }
  }

  async function archiveHold(hold_type, variant) {
    try {
      await ElMessageBox.confirm(`确定归档岩点 ${hold_type} / ${variant}？历史线路仍可继续显示。`, '归档岩点', {
        confirmButtonText: '归档岩点',
        cancelButtonText: '取消',
        type: 'warning',
      })
      await apiClient.delete(`/api/holds/${hold_type}/${variant}`)
      ElMessage.success('岩点已归档')
      await fetchAllHoldData()
    } catch (error) {
      if (error === 'cancel' || error === 'close') return
      ElMessage.error(`归档失败：${error.response?.data?.detail || error.message}`)
    }
  }

  async function restoreHold(hold_type, variant) {
    try {
      await apiClient.post(`/api/holds/${hold_type}/${variant}/restore`)
      ElMessage.success('岩点已恢复')
      await fetchAllHoldData()
    } catch (error) {
      ElMessage.error(`恢复失败：${error.response?.data?.detail || error.message}`)
    }
  }

  function resolveHoldVisual(hold) {
    const type = hold.hold_type || hold.type
    const variant = hold.variant || 'default'
    return {
      svgPath: holdVectorMap[type]?.[variant] || holdVectorMap[type]?.default,
      imageUrl: holdImageMap[type]?.[variant] || holdImageMap[type]?.default,
    }
  }

  return {
    holdImageMap,
    holdVectorMap,
    holdAssets,
    holdTypes: HOLD_TYPES,
    loading,
    uploadInfo,
    search,
    typeFilter,
    previewMode,
    showArchived,
    managedHolds,
    filteredHolds,
    fetchAllHoldData,
    uploadImage,
    archiveHold,
    restoreHold,
    resolveHoldVisual,
  }
}
