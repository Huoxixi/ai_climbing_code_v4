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
  setTrajectoryStart: (id, startSeconds) => apiClient.put(`/api/climb-replay/jobs/${encodeURIComponent(id)}/actions/trajectory-start`, { start_seconds: startSeconds }).then(r => r.data),
  actions: (id) => apiClient.get(`/api/climb-replay/jobs/${encodeURIComponent(id)}/actions`).then(r => r.data),
  generateActions: (id, payload) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/actions`, payload).then(r => r.data),
  cancelActions: (id) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/actions/cancel`).then(r => r.data),
  reviewAction: (id, payload) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/actions/review`, payload).then(r => r.data),
  undoActionReview: (id, payload) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/actions/review/undo`, payload).then(r => r.data),
  exportActions: (id, payload) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/actions/export`, payload).then(r => r.data),
  prepareReplayBackground: id => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/actions/background`).then(r=>r.data),
  replayBackgroundUrl: (id, version) => `${String(API_BASE_URL || '').replace(/\/$/, '')}/api/climb-replay/jobs/${encodeURIComponent(id)}/actions/background?${new URLSearchParams({version})}`,
  cancelActionExport: (id) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/actions/export/cancel`).then(r => r.data),
  actionMediaUrl: (id, version, exported = false, download = false) => `${String(API_BASE_URL || '').replace(/\/$/, '')}/api/climb-replay/jobs/${encodeURIComponent(id)}/actions/media?${new URLSearchParams({ version: version || '', exported: String(exported), download: String(download) })}`,
  actionPackageUrl: (id, version, exported = false, dataOnly = false, exportId = '') => `${String(API_BASE_URL || '').replace(/\/$/, '')}/api/climb-replay/jobs/${encodeURIComponent(id)}/actions/package?${new URLSearchParams({ version: version || '', exported: String(exported), data_only: String(dataOnly), ...(exportId ? {export_id:exportId} : {}) })}`,
  consentPolicy: () => apiClient.get('/api/climb-replay/consent-policy').then((response) => response.data),
  async prepareVideoPreview(file, signal) {
    if(!['127.0.0.1','localhost','[::1]','::1'].includes(window.location.hostname))throw new Error('兼容预览仅可在本机生成。')
    const {data:capability}=await apiClient.get('/api/climb-replay/preview-capability',{signal})
    if(capability?.local_conversion!==true)throw new Error('当前程序未启用本机兼容预览，请重开最新本地 App。')
    const body=new FormData();body.append('video',file)
    try {
      const response=await apiClient.post('/api/climb-replay/preview-video',body,{signal,responseType:'blob',timeout:0})
      return {blob:response.data,sourceDuration:Number(response.headers['x-source-duration']),preparedId:response.headers['x-prepared-video-id'] || ''}
    } catch(error) {
      if(error?.response?.data instanceof Blob){
        try { error.response.data=JSON.parse(await error.response.data.text()) } catch { /* Keep a generic local error. */ }
      }
      if(error?.code==='ERR_CANCELED')throw error
      throw new Error(error?.response?.data?.detail || '本机未能准备视频，请重新选择后重试。')
    }
  },
  discardVideoPreview: key => apiClient.delete(`/api/climb-replay/preview-video/${encodeURIComponent(key)}`),
  coachingPolicy: (signal) => apiClient.get('/api/climb-replay/coaching-policy', { signal }).then((response) => response.data),
  coachingPreflight: (id, signal) => apiClient.get(`/api/climb-replay/jobs/${encodeURIComponent(id)}/coaching/preflight`, { signal }).then((response) => response.data),
  coaching: (id, signal) => apiClient.get(`/api/climb-replay/jobs/${encodeURIComponent(id)}/coaching`, { signal }).then((response) => response.data),
  generateCoaching: (id, payload, signal) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/coaching`, payload, { signal }).then((response) => response.data),
  cancelCoaching: (id, signal) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/coaching/cancel`, null, { signal }).then((response) => response.data),
  withdrawCoachingConsent: (id, signal) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/coaching/consent/withdraw`, null, { signal }).then((response) => response.data),
  coachingFeedback: (id, payload, signal) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/coaching/feedback`, payload, { signal }).then((response) => response.data),
  templateVideo: (id, signal) => apiClient.get(`/api/climb-replay/jobs/${encodeURIComponent(id)}/template-video`, { signal }).then((response) => response.data),
  generateTemplateVideo: (id, payload, signal) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/template-video`, payload, { signal }).then((response) => response.data),
  cancelTemplateVideo: (id, signal) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/template-video/cancel`, null, { signal }).then((response) => response.data),
  templateVideoMediaUrl: (id, download = false, version = '') => {
    const query = new URLSearchParams()
    if (download) query.set('download', 'true')
    if (version) query.set('version', version)
    return `${String(API_BASE_URL || '').replace(/\/$/, '')}/api/climb-replay/jobs/${encodeURIComponent(id)}/template-video/media${query.size ? `?${query}` : ''}`
  },
  testVideos: () => apiClient.get('/api/climb-replay/test-videos').then((response) => response.data),
  testVideo: (caseId) => apiClient.get(`/api/climb-replay/test-videos/${encodeURIComponent(caseId)}`, {
    responseType:'blob',
  }).then((response) => response.data),
  comparisonVideoUrl,
  list: () => apiClient.get('/api/climb-replay/jobs').then((response) => response.data),
  get: (id) => apiClient.get(`/api/climb-replay/jobs/${id}`).then((response) => response.data),
  confirmAllHolds: (id, revision) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/holds/confirm-all`, { revision }, { timeout:180000 }).then(r => r.data),
  refreshRouteMap: (id) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/route-map/refresh`, {}, { timeout:180000 }).then(r => r.data),
  startAnalysis: (id, consentVersion, sampling = {}) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/analysis/start`, {
    consent_version:consentVersion, consent_granted:true, ...sampling,
  }).then(r => r.data),
  removeHold: (id, holdId) => apiClient.delete(`/api/climb-replay/jobs/${encodeURIComponent(id)}/holds/${encodeURIComponent(holdId)}`, { timeout:180000 }).then(r => r.data),
  compare: (firstJobId, secondJobId, sameClimberConfirmed) => apiClient.post('/api/climb-replay/comparisons', {
    first_job_id:firstJobId, second_job_id:secondJobId,
    same_climber_confirmed:sameClimberConfirmed,
  }).then((response) => response.data),
  reviewSegment: (jobId, segmentId, review) => apiClient.put(`/api/climb-replay/jobs/${encodeURIComponent(jobId)}/segments/${encodeURIComponent(segmentId)}/review`, review).then((response) => response.data),
  revertSegmentReview: (jobId, segmentId) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(jobId)}/segments/${encodeURIComponent(segmentId)}/review/revert`).then((response) => response.data),
  editorFrame: (id, payload, signal) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/holds/editor/frame`, payload, { signal }).then(response => response.data),
  editorPreview: (id, payload, signal) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/holds/editor/preview`, payload, { signal, timeout:120000 }).then(response => response.data),
  editorConfirm: (id, proposalId) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/holds/editor/confirm`, { proposal_id:proposalId }).then(response => response.data),
  editorCancel: (id, requestId) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/holds/editor/cancel`, { request_id:requestId }).then(response => response.data),
  addHoldAtPoint: (jobId, pointXy, timeSeconds, regionXyxy = null, proposalId = null) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(jobId)}/holds/point`, {
    point_xy:pointXy, time_seconds:timeSeconds, ...(regionXyxy ? { region_xyxy:regionXyxy } : {}), ...(proposalId ? { proposal_id:proposalId } : {}),
  }, { timeout:180000 }).then((response) => response.data),
  previewHoldAtPoint: (jobId, pointXy, timeSeconds, regionXyxy = null) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(jobId)}/holds/point/preview`, {
    point_xy:pointXy, time_seconds:timeSeconds, ...(regionXyxy ? { region_xyxy:regionXyxy } : {}),
  }).then((response) => response.data),
  undoClickedHold: (jobId, reviewVersion) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(jobId)}/holds/point/${encodeURIComponent(reviewVersion)}/undo`, null, { timeout:180000 }).then((response) => response.data),
  refineSampledHolds: (jobId) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(jobId)}/holds/refine-sampled-route`, null, { timeout:180000 }).then((response) => response.data),
  create: ({ video, preparedId = '', skipHolds = false, routeColor, routeColorSample = null, routeId = '', consentVersion, consentGranted, retentionMode, trimStartSeconds = 0, trimEndSeconds = null }, onProgress) => {
    const payload={filename:video.name,content_type:video.type || 'application/octet-stream',size_bytes:video.size,
      skip_holds:skipHolds,route_id:skipHolds?'':routeId,route_color:skipHolds?'':routeColor,route_color_sample:skipHolds?null:routeColorSample,
      consent_version:consentVersion,consent_granted:consentGranted,retention_mode:'keep_private_original',trim_start_seconds:trimStartSeconds,trim_end_seconds:trimEndSeconds}
    if(preparedId)return apiClient.post(`/api/climb-replay/prepared-videos/${encodeURIComponent(preparedId)}/start`,payload,{timeout:120000}).then(response=>{onProgress?.(100);return response.data})
    return uploadInChunks({
    file: video,
    create: () => apiClient.post('/api/climb-replay/uploads', {
      filename:video.name, content_type:video.type || 'application/octet-stream', size_bytes:video.size,
      skip_holds:skipHolds, route_id:skipHolds ? "" : routeId, route_color:skipHolds ? "" : routeColor,
      route_color_sample:skipHolds ? null : routeColorSample,
      consent_version:consentVersion, consent_granted:consentGranted,
      retention_mode:'keep_private_original',
      trim_start_seconds:trimStartSeconds,
      trim_end_seconds:trimEndSeconds,
    }).then(response => response.data),
    append: (uploadId, offset, chunk) => apiClient.put(`/api/climb-replay/uploads/${uploadId}`, chunk, {
      timeout:120000, headers:{ 'Content-Type':'application/octet-stream', 'X-Upload-Offset':String(offset) },
    }).then(response => response.data),
    complete: (uploadId) => apiClient.post(`/api/climb-replay/uploads/${uploadId}/complete`).then(response => response.data),
    onProgress,
  })},
  cancel: (id) => apiClient.post(`/api/climb-replay/jobs/${id}/cancel`).then((response) => response.data),
  retryVisualReplay: (id) => apiClient.post(`/api/climb-replay/jobs/${encodeURIComponent(id)}/visual-replay/retry`).then((response) => response.data),
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
