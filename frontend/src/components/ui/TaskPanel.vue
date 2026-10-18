<template>
  <section class="task-panel" :class="{ 'task-panel--paged': desktop }" :aria-label="title">
    <header v-if="title || $slots.header" class="task-panel__heading"><slot name="header"><h2>{{ title }}</h2></slot></header>
    <div ref="viewport" class="task-panel__viewport">
      <div ref="content" class="task-panel__content"><slot /></div>
    </div>
    <nav v-if="desktop && pages.length > 1" class="task-panel__pages" :aria-label="`${title || '工具'}分页`">
      <button type="button" aria-label="上一页" :disabled="page === 0" @click="turn(-1)"><ArrowLeft aria-hidden="true" /><span>上一页</span></button>
      <output aria-live="polite">{{ page + 1 }} / {{ pages.length }}</output>
      <button type="button" aria-label="下一页" :disabled="page >= pages.length - 1" @click="turn(1)"><span>下一页</span><ArrowRight aria-hidden="true" /></button>
    </nav>
    <footer v-if="$slots.footer" class="task-panel__footer"><slot name="footer" /></footer>
  </section>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { ArrowLeft, ArrowRight } from '@element-plus/icons-vue'
const props = defineProps({ title: { type: String, default: '' }, paginate: { type: Boolean, default: true } })
const viewport = ref(null), content = ref(null), page = ref(0), pages = shallowRef([]), desktop = ref(false)
let resize, mutations, media, scheduled
let units = [], splitContainers = []
function apply() {
  const current = new Set(pages.value[page.value] || [])
  for (const child of units) {
    const hidden = desktop.value && !current.has(child)
    child.toggleAttribute('data-panel-hidden', hidden)
    child.inert = hidden
  }
  for (const parent of splitContainers) {
    const hidden = desktop.value && ![...current].some(child => parent.contains(child))
    parent.toggleAttribute('data-panel-hidden', hidden); parent.inert = hidden
  }
}
function measure() {
  if (!content.value || !viewport.value) return
  const anchor = pages.value[page.value]?.[0]
  const children = [...content.value.children]
  for (const child of content.value.querySelectorAll('[data-panel-hidden]')) { child.removeAttribute('data-panel-hidden'); child.inert = false }
  for (const child of [...units, ...splitContainers]) child.inert = false
  if (!desktop.value) { pages.value = []; page.value = 0; return }
  const inset = getComputedStyle(viewport.value)
  const available = Math.max(44, viewport.value.clientHeight - parseFloat(inset.paddingTop) - parseFloat(inset.paddingBottom) - 4)
  units = []; splitContainers = []
  function collect(child) {
    const rect = child.getBoundingClientRect()
    if (getComputedStyle(child).display === 'none' || rect.height === 0) return
    const descendants = [...child.children].filter(element => getComputedStyle(element).display !== 'none' && element.getBoundingClientRect().height > 0)
    if (rect.height > available && descendants.length > 1 && /^(DIV|SECTION|DETAILS|FIELDSET|FORM|DL|UL|OL|NAV)$/.test(child.tagName)) {
      splitContainers.push(child); descendants.forEach(collect)
    } else units.push(child)
  }
  children.forEach(collect)
  const overhead = group => splitContainers.filter(parent => group.some(child => parent.contains(child))).reduce((total,parent) => {
    const style=getComputedStyle(parent)
    return total + ['paddingTop','paddingBottom','borderTopWidth','borderBottomWidth','marginTop','marginBottom'].reduce((sum,key)=>sum+(parseFloat(style[key])||0),0)
  },0)
  const next = []; let batch = [], used = 0
  const visible = units
  for (let index = 0; index < visible.length; index++) {
    const child = visible[index], rect = child.getBoundingClientRect(), style = getComputedStyle(child)
    const height = rect.height + (parseFloat(style.marginTop) || 0) + (parseFloat(style.marginBottom) || 0)
    const following = /^H[1-6]$/.test(child.tagName) ? visible[index + 1]?.getBoundingClientRect().height || 0 : 0
    if (batch.length && used + height + following + overhead([...batch,child]) + 12 > available) { next.push(batch); batch = []; used = 0 }
    batch.push(child); used += height + 12
  }
  if (batch.length) next.push(batch)
  pages.value = next
  const anchored = next.findIndex(group => group.includes(anchor))
  page.value = anchored >= 0 ? anchored : Math.min(page.value, Math.max(0, next.length - 1))
  apply()
}
function queue() { cancelAnimationFrame(scheduled); scheduled = requestAnimationFrame(measure) }
async function turn(direction) {
  page.value = Math.max(0, Math.min(pages.value.length - 1, page.value + direction)); apply()
  await nextTick()
  const first = pages.value[page.value]?.[0]
  first?.querySelector('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled)')?.focus({ preventScroll: true })
}
function changeMode() { desktop.value = props.paginate && media.matches && Boolean(viewport.value?.closest('.workspace-boulder')); queue() }
watch(() => props.paginate, changeMode)
onMounted(() => {
  media = matchMedia('(min-width: 900px)'); changeMode(); media.addEventListener('change', changeMode)
  resize = new ResizeObserver(queue); resize.observe(viewport.value)
  mutations = new MutationObserver(queue); mutations.observe(content.value, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['open', 'style', 'class'] })
  queue()
})
onBeforeUnmount(() => { resize?.disconnect(); mutations?.disconnect(); media?.removeEventListener('change', changeMode); cancelAnimationFrame(scheduled) })
defineExpose({ refresh: queue })
</script>

<style scoped>
.task-panel{min-width:0;min-height:0;display:flex;flex-direction:column;background:var(--ui-surface);border:1px solid var(--ui-line);border-radius:12px;overflow:visible}
.task-panel__heading{flex:none;padding:14px 16px;border-bottom:1px solid var(--ui-line)}
.task-panel__heading h2{margin:0;font-size:16px;line-height:1.4}
.task-panel__viewport{flex:none;min-height:0;padding:16px}
.task-panel--paged>.task-panel__viewport{flex:1;overflow:hidden}
.task-panel__content{display:flex;flex-direction:column;gap:12px;min-width:0}
.task-panel__content :deep([data-panel-hidden]){display:none!important}
.task-panel__pages{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:6px 12px;border-top:1px solid var(--ui-line);flex:none}
.task-panel__pages button{display:inline-flex;align-items:center;gap:4px;min-height:44px;padding:6px 8px;font:inherit;font-size:12px}
.task-panel__pages svg{width:16px;height:16px}.task-panel__pages output{font-size:12px;font-variant-numeric:tabular-nums;color:var(--ui-ink-muted)}
.task-panel__footer{flex:none;display:grid;gap:8px;padding:12px 16px;border-top:1px solid var(--ui-line)}
</style>
