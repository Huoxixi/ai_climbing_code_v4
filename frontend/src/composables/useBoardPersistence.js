import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import boardService from '../services/boardService'

export function useBoardPersistence() {
  const savedBoards = ref([])
  const loading = ref(false)

  async function fetchMyBoards() {
    loading.value = true
    try {
      const response = await boardService.listBoards()
      savedBoards.value = Array.isArray(response.data) ? response.data : []
    } catch (error) {
      ElMessage.error(`岩板资产加载失败：${error.response?.data?.detail || error.message}`)
    } finally {
      loading.value = false
    }
  }

  async function saveBoard(board) {
    loading.value = true
    try {
      const payload = {
        ...board,
        updated_at: new Date().toISOString(),
      }
      const response = payload.saved_id
        ? await boardService.updateBoard(payload.saved_id, payload)
        : await boardService.createBoard(payload)
      ElMessage.success(payload.saved_id ? '岩板已更新' : '岩板已保存')
      await fetchMyBoards()
      return response.data
    } catch (error) {
      ElMessage.error(`保存失败：${error.response?.data?.detail || error.message}`)
      return null
    } finally {
      loading.value = false
    }
  }

  async function renameSavedBoard(board) {
    if (!board.saved_id) {
      ElMessage.warning('该岩板缺少 saved_id，无法重命名')
      return null
    }

    try {
      const { value } = await ElMessageBox.prompt('请输入新的岩板名称', '重命名岩板', {
        inputValue: board.route_name || '',
        confirmButtonText: '保存',
        cancelButtonText: '取消',
        inputValidator: (text) => Boolean(text && text.trim()) || '名称不能为空',
      })
      const renamed = { ...board, route_name: value.trim(), updated_at: new Date().toISOString() }
      await boardService.updateBoard(board.saved_id, renamed)
      ElMessage.success('岩板已重命名')
      await fetchMyBoards()
      return renamed
    } catch (error) {
      if (error === 'cancel' || error === 'close') return null
      ElMessage.error(`重命名失败：${error.response?.data?.detail || error.message}`)
      return null
    }
  }

  async function deleteSavedBoard(board) {
    if (!board.saved_id) {
      ElMessage.warning('该岩板缺少 saved_id，无法删除')
      return false
    }

    try {
      await ElMessageBox.confirm(`确定删除岩板“${board.route_name || board.saved_id}”？此操作会归档该资产。`, '删除岩板资产', {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      })
      await boardService.deleteBoard(board.saved_id)
      ElMessage.success('岩板已删除')
      await fetchMyBoards()
      return true
    } catch (error) {
      if (error === 'cancel' || error === 'close') return false
      ElMessage.error(`删除失败：${error.response?.data?.detail || error.message}`)
      return false
    }
  }

  return {
    savedBoards,
    loading,
    fetchMyBoards,
    saveBoard,
    renameSavedBoard,
    deleteSavedBoard,
  }
}
