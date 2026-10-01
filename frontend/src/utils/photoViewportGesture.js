export function photoWheelGesture(event, zoom, viewportHeight = 0) {
  if (event.ctrlKey) {
    const delta = Math.max(-100, Math.min(100, event.deltaY))
    return { type: 'zoom', factor: Math.exp(-delta * 0.002) }
  }
  if (zoom <= 1) return { type: 'page' }
  const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? Math.max(1, viewportHeight) : 1
  return {
    type: 'pan',
    x: event.deltaX ? -event.deltaX * unit : 0,
    y: event.deltaY ? -event.deltaY * unit : 0,
  }
}
