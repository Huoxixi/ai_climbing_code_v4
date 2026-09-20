import apiClient from './apiClient'

const climbReplayService = {
  list: () => apiClient.get('/api/climb-replay/jobs').then((response) => response.data),
  get: (id) => apiClient.get(`/api/climb-replay/jobs/${id}`).then((response) => response.data),
  create: ({ video, routeColor }, onProgress) => {
    const body = new FormData()
    body.append('video', video)
    body.append('route_color', routeColor)
    return apiClient.post('/api/climb-replay/jobs', body, {
      timeout: 120000,
      onUploadProgress: (event) => {
        if (event.total && onProgress) onProgress(Math.round((event.loaded / event.total) * 100))
      },
    }).then((response) => response.data)
  },
  cancel: (id) => apiClient.post(`/api/climb-replay/jobs/${id}/cancel`).then((response) => response.data),
  retry: (id) => apiClient.post(`/api/climb-replay/jobs/${id}/retry`).then((response) => response.data),
}

export default climbReplayService
