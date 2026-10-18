import { onBeforeUnmount, ref, watch } from 'vue'

// Retarget from the visible value so rapid zoom reversals stay continuous.
export function useSmoothNumber(target, duration = 220) {
  const visible = ref(target.value), animating = ref(false)
  let request = 0
  function stop() { cancelAnimationFrame(request); request = 0; animating.value = false }
  function reset(value = target.value) { stop(); visible.value = value }
  watch(target, value => {
    stop()
    if (value === visible.value || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      visible.value = value
      return
    }
    const from = visible.value, started = performance.now()
    animating.value = true
    const step = now => {
      const progress = Math.min(1, (now - started) / duration)
      visible.value = from + (value - from) * (1 - (1 - progress) ** 3)
      if (progress < 1) request = requestAnimationFrame(step)
      else { visible.value = value; request = 0; animating.value = false }
    }
    request = requestAnimationFrame(step)
  })
  onBeforeUnmount(stop)
  return { visible, animating, reset }
}
