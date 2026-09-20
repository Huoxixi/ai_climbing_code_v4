import apiClient from './apiClient'
import { uploadInChunks } from './chunkUpload'

const climbReplayService = {
  list: () => apiClient.get('/api/climb-replay/jobs').then((response) => response.data),
  get: (id) => apiClient.get(`/api/climb-replay/jobs/${id}`).then((response) => response.data),
  create: ({ video, routeColor, routeId = '' }, onProgress) => uploadInChunks({
    file: video,
    create: () => apiClient.post('/api/climb-replay/uploads', {
      filename:video.name, content_type:video.type, size_bytes:video.size,
      route_id:routeId, route_color:routeColor,
    }).then(response => response.data),
    append: (uploadId, offset, chunk) => apiClient.put(`/api/climb-replay/uploads/${uploadId}`, chunk, {
      timeout:120000, headers:{ 'Content-Type':'application/octet-stream', 'X-Upload-Offset':String(offset) },
    }).then(response => response.data),
    complete: (uploadId) => apiClient.post(`/api/climb-replay/uploads/${uploadId}/complete`).then(response => response.data),
    onProgress,
  }),
  cancel: (id) => apiClient.post(`/api/climb-replay/jobs/${id}/cancel`).then((response) => response.data),
  retry: (id) => apiClient.post(`/api/climb-replay/jobs/${id}/retry`).then((response) => response.data),
}

export default climbReplayService
