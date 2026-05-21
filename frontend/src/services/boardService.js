import apiClient from './apiClient'

export const boardService = {
  listBoards() {
    return apiClient.get('/api/my-boards')
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
}

export default boardService