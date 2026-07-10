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

  getActivity(sourceId) {
    return apiClient.get(`/api/standard-board/routes/${sourceId}/activity`)
  },

  favoriteRoute(sourceId) {
    return apiClient.post(`/api/standard-board/routes/${sourceId}/favorite`)
  },

  unfavoriteRoute(sourceId) {
    return apiClient.delete(`/api/standard-board/routes/${sourceId}/favorite`)
  },

  rateRoute(sourceId, rating) {
    return apiClient.post(`/api/standard-board/routes/${sourceId}/rating`, { rating })
  },

  logAscent(sourceId, payload) {
    return apiClient.post(`/api/standard-board/routes/${sourceId}/ascent-log`, payload)
  },

  listRepairs(params) {
    return apiClient.get('/api/standard-board/repairs', { params })
  },

  getRepair(sourceId) {
    return apiClient.get(`/api/standard-board/repairs/${sourceId}`)
  },

  compareRepair(sourceId) {
    return apiClient.get(`/api/standard-board/repairs/${sourceId}/comparison`)
  },

  previewRepair(sourceId) {
    return apiClient.get(`/api/standard-board/repairs/${sourceId}/preview`)
  },

  publishRepairs(sourceIds) {
    return apiClient.post('/api/standard-board/repairs/publish', { source_ids: sourceIds })
  },
}

export default standardBoardService
