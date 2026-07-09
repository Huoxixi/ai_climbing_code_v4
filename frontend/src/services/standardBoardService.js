import apiClient from './apiClient'

export const standardBoardService = {
  listRoutes(params) {
    return apiClient.get('/api/standard-board/routes', { params })
  },

  getRoute(sourceId) {
    return apiClient.get(`/api/standard-board/routes/${sourceId}`)
  },

  generateRoute(payload) {
    return apiClient.post('/api/standard-board/generate', payload)
  },
}

export default standardBoardService
