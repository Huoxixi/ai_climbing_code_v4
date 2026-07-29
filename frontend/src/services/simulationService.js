import apiClient from './apiClient'
import { DEFAULT_FONT_GRADE } from '../constants/gradeSystem'

export const simulationService = {
  listProfiles(abilityGrade = DEFAULT_FONT_GRADE) {
    return apiClient.get('/api/simulation/climber-profiles', { params: { ability_grade: abilityGrade } })
  },
  listHoldProfiles() {
    return apiClient.get('/api/simulation/hold-profiles')
  },
  saveHoldProfile(profile) {
    return apiClient.put(`/api/simulation/hold-profiles/${encodeURIComponent(profile.variant_id)}`, profile)
  },
  startRoute(sourceId, payload = {}) {
    return apiClient.post(`/api/standard-board/routes/${sourceId}/simulation`, payload)
  },
  latest(sourceId) {
    return apiClient.get(`/api/standard-board/routes/${sourceId}/simulation/latest`)
  },
  startBatch(payload = {}) {
    return apiClient.post('/api/standard-board/simulations/batch', payload)
  },
  task(taskId) {
    return apiClient.get(`/api/result/${taskId}`)
  },
  cancel(taskId) {
    return apiClient.post(`/api/cancel/${taskId}`)
  },
  repairCandidates(reportId) {
    return apiClient.post(`/api/simulation/reports/${reportId}/repair-candidates`)
  },
  feedback(reportId, payload) {
    return apiClient.post(`/api/simulation/reports/${reportId}/feedback`, payload)
  },
}

export default simulationService
