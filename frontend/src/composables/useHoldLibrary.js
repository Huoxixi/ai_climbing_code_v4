import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import apiClient from '../services/apiClient'

export const HOLD_TYPES = ['Jug', 'Crimp', 'Sloper', 'Pinch', 'Pocket', 'Foot']

export function useHoldLibrary() {
  const holdImageMap = reactive({})
  const holdVectorMap = reactive({})
  const loading = ref(false)
  const uploadInfo = reactive({ hold_type: 'Jug', variant: '', file: null })
  const search = ref('')
  const typeFilter = ref('All')
  const previewMode = ref('vector')

  const managedHolds = computed(() => {
    const holds = []
    const allTypes = new Set([...Object.keys(holdImageMap), ...Object.keys(holdVectorMap)])
    allTypes.forEach((hold_type) => {
      const variants = new Set([
        ...Object.keys(holdImageMap[hold_type] || {}),
        ...Object.keys(holdVectorMap[hold_type] || {}),
      ])
      variants.forEach((variant) => {
        if (variant === 'default') return
        holds.push({
          key: `${hold_type}-${variant}`,
          hold_type,
          type: hold_type,
          variant,
          imageUrl: holdImageMap[hold_type]?.[variant] || holdImageMap[hold_type]?.default,
          svgPath: holdVectorMap[hold_type]?.[variant] || holdVectorMap[hold_type]?.default,
        })
      })
    })
    return holds.sort((a, b) => `${a.hold_type}-${a.variant}`.localeCompare(`${b.hold_type}-${b.variant}`))
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
      await Promise.all([fetchHoldMapping(), fetchHoldVectors()])
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
      await apiClient.post('/api/holds/upload', formData)
      ElMessage.success('岩点上传成功')
      uploadInfo.variant = ''
      uploadInfo.file = null
      await fetchAllHoldData()
    } catch (error) {
      ElMessage.error(`上传失败：${error.response?.data?.detail || error.message}`)
    } finally {
      loading.value = false
    }
  }

  async function deleteHold(hold_type, variant) {
    try {
      await ElMessageBox.confirm(`确定删除岩点 ${hold_type} / ${variant}？此操作不可撤销。`, '删除岩点', {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      })
      await apiClient.delete(`/api/holds/${hold_type}/${variant}`)
      ElMessage.success('岩点已删除')
      await fetchAllHoldData()
    } catch (error) {
      if (error === 'cancel' || error === 'close') return
      ElMessage.error(`删除失败：${error.response?.data?.detail || error.message}`)
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
    holdTypes: HOLD_TYPES,
    loading,
    uploadInfo,
    search,
    typeFilter,
    previewMode,
    managedHolds,
    filteredHolds,
    fetchAllHoldData,
    uploadImage,
    deleteHold,
    resolveHoldVisual,
  }
}
