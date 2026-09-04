import apiClient, { API_BASE_URL } from './apiClient'
export const photoAssetUrl = (asset) => asset ? `${API_BASE_URL}/photo-route-assets/${asset.filename}` : ''
export default {
  list: () => apiClient.get('/api/photo-routes/drafts').then(r => r.data),
  extractions: () => apiClient.get('/api/photo-routes/extractions').then(r => r.data),
  get: (id) => apiClient.get(`/api/photo-routes/drafts/${id}`).then(r => r.data),
  import: (extraction_id) => apiClient.post('/api/photo-routes/drafts/import', { extraction_id }).then(r => r.data),
  save: (draft, expected_version) => apiClient.put(`/api/photo-routes/drafts/${draft.id}`, {
    expected_version, name: draft.name, color: draft.color, original_grade: draft.original_grade, notes: draft.notes, objects: draft.objects,
  }).then(r => r.data),
}
