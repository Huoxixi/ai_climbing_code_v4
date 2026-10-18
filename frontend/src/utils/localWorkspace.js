export function isLocalWorkspace(windowLike) {
  return Boolean(windowLike.__AI_CLIMBING_DESKTOP__) || ['localhost','127.0.0.1','[::1]'].includes(windowLike.location.hostname)
}

export function localWorkspaceHash(hash) {
  const page=String(hash || '').replace(/^#\/?/,'').split('/')[0]
  if(page==='account')return '#/settings'
  return ['photo-routes','my-records','climb-replay','settings'].includes(page) ? hash : '#/photo-routes'
}
