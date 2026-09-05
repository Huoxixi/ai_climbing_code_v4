import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import boardService from '../services/boardService'

export function useBoardPersistence() {
  const savedBoards = ref([])
  const archivedBoards = ref([])
  const loading = ref(false)

  async function fetchMyBoards() {
    loading.value = true
    try {
      const response = await boardService.listBoards(true)
      const allBoards = Array.isArray(response.data) ? response.data : []
      savedBoards.value = allBoards.filter((board) => !board.archived_at)
      archivedBoards.value = allBoards.filter((board) => board.archived_at)
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
      if (payload.visibility === 'public') { delete payload.saved_id; payload.visibility = 'private' }
      const response = payload.saved_id
        ? await boardService.updateBoard(payload.saved_id, payload)
        : await boardService.createBoard(payload)
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

  async function archiveSavedBoard(board) {
    if (!board.saved_id) {
      ElMessage.warning('该岩板缺少 saved_id，无法归档')
      return false
    }

    try {
      await ElMessageBox.confirm(`确定归档岩板“${board.route_name || board.saved_id}”？之后可以从归档箱恢复。`, '归档岩板资产', {
        confirmButtonText: '归档岩板',
        cancelButtonText: '取消',
        type: 'warning',
      })
      await boardService.deleteBoard(board.saved_id)
      ElMessage.success('岩板已归档')
      await fetchMyBoards()
      return true
    } catch (error) {
      if (error === 'cancel' || error === 'close') return false
      ElMessage.error(`归档失败：${error.response?.data?.detail || error.message}`)
      return false
    }
  }

  async function restoreSavedBoard(board) {
    if (!board.saved_id) return false
    loading.value = true
    try {
      await boardService.restoreBoard(board.saved_id)
      ElMessage.success('岩板已恢复')
      await fetchMyBoards()
      return true
    } catch (error) {
      ElMessage.error(`恢复失败：${error.response?.data?.detail || error.message}`)
      return false
    } finally {
      loading.value = false
    }
  }

  return {
    savedBoards,
    archivedBoards,
    loading,
    fetchMyBoards,
    saveBoard,
    renameSavedBoard,
    archiveSavedBoard,
    restoreSavedBoard,
  }
}
