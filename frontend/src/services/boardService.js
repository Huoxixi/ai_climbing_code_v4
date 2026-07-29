import apiClient from './apiClient'

export const boardService = {
  listBoards(includeArchived = false) {
    return apiClient.get('/api/my-boards', { params: { include_archived: includeArchived } })
  },

  createBoard(board) {
    return apiClient.post('/api/save-board', board)
  },

  updateBoard(savedId, board) {
    return apiClient.put(`/api/my-boards/${savedId}`, board)
  },

  deleteBoard(savedId) {
    return apiClient.delete(`/api/my-boards/${savedId}`)
  },

  restoreBoard(savedId) {
    return apiClient.post(`/api/my-boards/${savedId}/restore`)
  },
}

export default boardService
