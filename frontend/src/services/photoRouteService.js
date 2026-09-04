import apiClient, { API_BASE_URL } from './apiClient'
export const photoAssetUrl = (asset) => asset ? `${API_BASE_URL}/photo-route-assets/${asset.filename}` : ''
export const photoV2AssetUrl = (asset) => asset ? `${API_BASE_URL}/api/photo-routes/v2/assets/${asset.filename}` : ''
export default {
  list: () => apiClient.get('/api/photo-routes/drafts').then(r => r.data),
  extractions: () => apiClient.get('/api/photo-routes/extractions').then(r => r.data),
  get: (id) => apiClient.get(`/api/photo-routes/drafts/${id}`).then(r => r.data),
  import: (extraction_id) => apiClient.post('/api/photo-routes/drafts/import', { extraction_id }).then(r => r.data),
  save: (draft, expected_version) => apiClient.put(`/api/photo-routes/drafts/${draft.id}`, {
    expected_version, name: draft.name, color: draft.color, original_grade: draft.original_grade, notes: draft.notes, objects: draft.objects,
  }).then(r => r.data),
}

export const photoRouteV2Service = {
  boards: (archived = false) => apiClient.get('/api/photo-routes/v2/boards', { params: { archived } }).then(r => r.data),
  board: (id) => apiClient.get(`/api/photo-routes/v2/boards/${id}`).then(r => r.data),
  upload: (file) => {
    const body = new FormData(); body.append('photo', file)
    return apiClient.post('/api/photo-routes/v2/boards/upload', body).then(r => r.data)
  },
  newBoardVersion: (id) => apiClient.post(`/api/photo-routes/v2/boards/${id}/versions`).then(r => r.data),
  calibrate: (id, payload) => apiClient.put(`/api/photo-routes/v2/boards/${id}/calibration`, payload).then(r => r.data),
  addObject: (boardId, payload) => apiClient.post(`/api/photo-routes/v2/boards/${boardId}/objects`, payload).then(r => r.data),
  splitObject: (boardId, objectId, payload) => apiClient.post(`/api/photo-routes/v2/boards/${boardId}/objects/${objectId}/split`, payload).then(r => r.data),
  mergeObjects: (boardId, payload) => apiClient.post(`/api/photo-routes/v2/boards/${boardId}/objects/merge`, payload).then(r => r.data),
  patchObject: (boardId, objectId, payload) => apiClient.patch(`/api/photo-routes/v2/boards/${boardId}/objects/${objectId}`, payload).then(r => r.data),
  deleteObject: (boardId, objectId, expectedVersion) => apiClient.delete(`/api/photo-routes/v2/boards/${boardId}/objects/${objectId}`, { params: { expected_version: expectedVersion } }).then(r => r.data),
  job: (id) => apiClient.get(`/api/photo-routes/v2/jobs/${id}`).then(r => r.data),
  cancelJob: (id) => apiClient.post(`/api/photo-routes/v2/jobs/${id}/cancel`).then(r => r.data),
  retryJob: (id) => apiClient.post(`/api/photo-routes/v2/jobs/${id}/retry`).then(r => r.data),
  routes: (params = {}) => apiClient.get('/api/photo-routes/v2/routes', { params }).then(r => r.data),
  route: (id) => apiClient.get(`/api/photo-routes/v2/routes/${id}`).then(r => r.data),
  fromColor: (payload) => apiClient.post('/api/photo-routes/v2/routes/from-color', payload).then(r => r.data),
  saveRoute: (route) => apiClient.put(`/api/photo-routes/v2/routes/${route.id}`, {
    expected_version: route.version, name: route.name, difficulty: route.difficulty,
    setter: route.setter, notes: route.notes, members: route.members.map(({ object_id, roles, tags, note }) => ({ object_id, roles, tags, note })),
  }).then(r => r.data),
  completeRoute: (id) => apiClient.post(`/api/photo-routes/v2/routes/${id}/complete`).then(r => r.data),
  revisions: (id) => apiClient.get(`/api/photo-routes/v2/routes/${id}/revisions`).then(r => r.data),
  restoreRevision: (id, version) => apiClient.post(`/api/photo-routes/v2/routes/${id}/revisions/${version}/restore`).then(r => r.data),
  archive: (id) => apiClient.post(`/api/photo-routes/v2/routes/${id}/archive`).then(r => r.data),
  restore: (id) => apiClient.post(`/api/photo-routes/v2/routes/${id}/restore`).then(r => r.data),
  cleanup: (id, payload) => apiClient.post(`/api/photo-routes/v2/routes/${id}/cleanup`, payload).then(r => r.data),
  background: (id) => apiClient.get(`/api/photo-routes/v2/routes/${id}/background`).then(r => r.data),
}
