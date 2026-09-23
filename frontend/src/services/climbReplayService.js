import apiClient, { API_BASE_URL } from './apiClient'
import { uploadInChunks } from './chunkUpload'

const replayMediaUrl = (id, kind, download = false) => {
  const base = String(API_BASE_URL || '').replace(/\/$/, '')
  const query = download ? '?download=true' : ''
  return `${base}/api/climb-replay/jobs/${encodeURIComponent(id)}/media/${kind}${query}`
}

const comparisonVideoUrl = (caseId, download = false) => {
  const base = String(API_BASE_URL || '').replace(/\/$/, '')
  const query = download ? '?download=true' : ''
  return `${base}/api/climb-replay/test-videos/${encodeURIComponent(caseId)}/comparison${query}`
}

const climbReplayService = {
  consentPolicy: () => apiClient.get('/api/climb-replay/consent-policy').then((response) => response.data),
  testVideos: () => apiClient.get('/api/climb-replay/test-videos').then((response) => response.data),
  testVideo: (caseId) => apiClient.get(`/api/climb-replay/test-videos/${encodeURIComponent(caseId)}`, {
    responseType:'blob',
  }).then((response) => response.data),
  comparisonVideoUrl,
  list: () => apiClient.get('/api/climb-replay/jobs').then((response) => response.data),
  get: (id) => apiClient.get(`/api/climb-replay/jobs/${id}`).then((response) => response.data),
  create: ({ video, routeColor, routeId = '', consentVersion, consentGranted, retentionMode, trimStartSeconds = 0, trimEndSeconds = null }, onProgress) => uploadInChunks({
    file: video,
    create: () => apiClient.post('/api/climb-replay/uploads', {
      filename:video.name, content_type:video.type || 'application/octet-stream', size_bytes:video.size,
      route_id:routeId, route_color:routeColor,
      consent_version:consentVersion, consent_granted:consentGranted,
      retention_mode:retentionMode,
      trim_start_seconds:trimStartSeconds,
      trim_end_seconds:trimEndSeconds,
    }).then(response => response.data),
    append: (uploadId, offset, chunk) => apiClient.put(`/api/climb-replay/uploads/${uploadId}`, chunk, {
      timeout:120000, headers:{ 'Content-Type':'application/octet-stream', 'X-Upload-Offset':String(offset) },
    }).then(response => response.data),
    complete: (uploadId) => apiClient.post(`/api/climb-replay/uploads/${uploadId}/complete`).then(response => response.data),
    onProgress,
  }),
  cancel: (id) => apiClient.post(`/api/climb-replay/jobs/${id}/cancel`).then((response) => response.data),
  retry: (id, consentVersion) => apiClient.post(`/api/climb-replay/jobs/${id}/retry`, {
    consent_version:consentVersion, consent_granted:true,
  }).then((response) => response.data),
  withdrawConsent: (id) => apiClient.post(`/api/climb-replay/jobs/${id}/consent/withdraw`).then((response) => response.data),
  deleteSource: (id) => apiClient.delete(`/api/climb-replay/jobs/${id}/media/source-video`).then((response) => response.data),
  deleteOverlay: (id) => apiClient.delete(`/api/climb-replay/jobs/${id}/media/overlay-video`).then((response) => response.data),
  deleteJob: (id) => apiClient.delete(`/api/climb-replay/jobs/${id}`).then((response) => response.data),
  deletion: (id) => apiClient.get(`/api/climb-replay/deletions/${id}`).then((response) => response.data),
  mediaUrl: (id, kind, download = false) => replayMediaUrl(id, kind, download),
}

export default climbReplayService
