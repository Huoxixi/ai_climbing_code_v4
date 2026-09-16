const PHOTO_ROOT = '#/photo-routes'
const FLOW_SCREENS = new Set(['select-color', 'processing', 'recovery', 'review'])

export function appPageFromHash(hash, allowedPages, fallback = 'dashboard') {
  const page = String(hash || '').replace(/^#\/?/, '').split('/')[0]
  return allowedPages.includes(page) ? page : fallback
}

export function parsePhotoWorkflowHash(hash) {
  const value = String(hash || '')
  if (value === PHOTO_ROOT || value === `${PHOTO_ROOT}/`) return { screen: 'home' }
  if (!value.startsWith(`${PHOTO_ROOT}/`)) return { screen: 'outside' }
  const [screen, rawId] = value.slice(PHOTO_ROOT.length + 1).split('/')
  if (screen === 'route' && rawId) return { screen, routeId: decodeURIComponent(rawId) }
  if (['confirm', 'library', ...FLOW_SCREENS].includes(screen)) return { screen }
  return { screen: 'home' }
}

export function photoWorkflowHash(screen = 'home', routeId = '') {
  if (screen === 'home') return PHOTO_ROOT
  if (screen === 'route') return `${PHOTO_ROOT}/route/${encodeURIComponent(routeId)}`
  return `${PHOTO_ROOT}/${screen}`
}

export function photoWorkflowScreen(state) {
  if (state.pending) return 'confirm'
  return ({
    awaiting_color: 'select-color',
    processing: 'processing',
    failed: 'recovery',
    ready: 'review',
  })[state.session?.status] || 'home'
}

export function isPhotoFlowScreen(screen) {
  return FLOW_SCREENS.has(screen)
}
