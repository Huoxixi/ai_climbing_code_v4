<template>
  <section class="settings-card replay-vision-settings" aria-labelledby="replay-vision-title">
    <h2 id="replay-vision-title">AI 复盘服务</h2>
    <p>配置一次即可用于后续复盘。保存不会调用 AI。</p>
    <form v-if="loaded" @submit.prevent="save">
      <label class="vision-full-width">服务地址<input v-model="form.base_url" type="url" placeholder="https://服务地址/v1" maxlength="512" /></label>
      <label>模型<input v-model="form.model" maxlength="128" autocomplete="off" placeholder="gpt-6-sol" /></label>
      <label>API 密钥<input v-model="key" type="password" autocomplete="new-password" maxlength="512" :placeholder="configured ? '已保存；留空保留现有密钥' : '填写服务密钥'" /></label>
      <p class="vision-full-width vision-key-note">密钥安全保存；留空保留已有密钥。复盘前会确认发送资料与费用。</p>
      <details class="vision-full-width vision-advanced"><summary>高级设置</summary>
        <label class="vision-cost-toggle"><input v-model="form.cost_control_enabled" type="checkbox" />启用费用估算与预算</label>
        <p>可选。关闭时无需填写价格，模型仍可使用；实际费用以服务账单为准。</p>
      <fieldset v-if="form.cost_control_enabled"><legend>服务计费参数</legend>
        <p>启用后按服务价格估算费用，并检查本次预算。</p>
        <label>单次总预算（元）<input v-model.number="form.budget_cny" type="number" min="0.01" max="100" step="0.01" required /></label>
        <div class="vision-price-fields">
          <label>输入 · 元／百万 token<input v-model="inputPrice" type="number" min="0" step="any" /></label>
          <label>输出 · 元／百万 token<input v-model="outputPrice" type="number" min="0" step="any" /></label>
        </div>
        <label>额外图片费用 · 元／张<input v-model.number="form.image_cny_each" type="number" min="0" step="any" required /></label>
      </fieldset>
      </details>
      <div class="vision-full-width vision-actions">
        <button class="settings-primary" type="submit" :disabled="saving">{{ saving ? '正在保存…' : '保存 AI 服务' }}</button>
        <button v-if="configured" type="button" :disabled="saving" @click="save(true)">停用 AI 服务</button>
      </div>
    </form>
    <button v-else type="button" @click="load">重新读取</button>
    <p v-if="notice" role="status">{{ notice }}</p>
  </section>
</template>
<script setup>
import { onMounted, ref } from 'vue'
import api from '../services/apiClient'
const loaded = ref(false), configured = ref(false), saving = ref(false), notice = ref(''), key = ref('')
const inputPrice = ref(''), outputPrice = ref('')
const savedBaseUrl = ref('')
const form = ref({base_url:'',model:'',api_mode:'auto',cost_control_enabled:false,budget_cny:1,image_input_token_reserve:4096,image_cny_each:0})
function accept(data) {
  configured.value = data.configured
  savedBaseUrl.value = data.base_url || ''
  for (const field of Object.keys(form.value)) form.value[field] = data[field] ?? form.value[field]
  inputPrice.value = data.input_cny_per_million ?? ''; outputPrice.value = data.output_cny_per_million ?? ''
  loaded.value = true; key.value = ''
}
async function load() {
  try { accept((await api.get('/api/settings/replay-vision')).data); notice.value = '' }
  catch { notice.value = 'AI 服务设置暂不可用，请重试。' }
}
async function save(disable = false) {
  saving.value = true
  try {
    const data = (await api.put('/api/settings/replay-vision', {...form.value,
      api_mode: form.value.base_url.trim() === savedBaseUrl.value.trim() ? form.value.api_mode : 'auto',
      api_key:disable === true ? '' : key.value.trim() || null,
      input_cny_per_million:inputPrice.value === '' ? null : Number(inputPrice.value),
      output_cny_per_million:outputPrice.value === '' ? null : Number(outputPrice.value)})).data
    accept(data); notice.value = data.ready ? '已保存。开始复盘时确认发送资料与费用。' : data.configured && data.cost_control_enabled ? '已保存。请补充计费参数，或关闭费用估算后使用。' : '已保存。请补充服务地址、模型与密钥。'
  } catch { notice.value = '未能保存，请检查填写内容后重试。' }
  finally { saving.value = false }
}
onMounted(load)
</script>
<style scoped>
.replay-vision-settings{box-sizing:border-box;min-width:0;grid-column:1/-1;padding:28px;border-radius:var(--ui-radius-card);background:var(--ui-surface);box-shadow:var(--ui-shadow-float)}
h2{margin:0 0 8px;font-size:18px;font-weight:600;line-height:1.4}form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;max-width:640px;margin-top:24px}.vision-full-width{grid-column:1/-1}label{display:grid;gap:8px;min-width:0;margin:0;font-size:14px}input{box-sizing:border-box;width:100%;min-width:0;min-height:44px;padding:10px 12px;border:1px solid var(--ui-line-strong);border-radius:var(--ui-radius-control);font:inherit;color:var(--ui-ink);background:var(--ui-surface)}
p{margin:0;line-height:1.6;color:var(--ui-ink-muted);overflow-wrap:anywhere;font-size:13px}.vision-key-note{margin-top:-8px}fieldset{min-width:0;margin:8px 0 0;padding:16px 0 0;border:0;border-top:1px solid var(--ui-line)}legend{padding:0 12px 0 0;font-size:14px;font-weight:500}.vision-price-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:16px 0}details label{margin-top:16px}details p{margin-top:12px}.vision-actions{display:flex;flex-wrap:wrap;gap:12px;margin-top:8px}button{min-height:44px;margin:0;padding:10px 16px;border:1px solid var(--ui-line-strong);border-radius:var(--ui-radius-control);font:inherit;font-size:14px;background:var(--ui-surface);color:var(--ui-ink);cursor:pointer}button:hover:not(:disabled){background:var(--ui-surface-subtle)}.settings-primary{border-color:var(--ui-brand);background:var(--ui-brand);color:var(--ui-brand-ink)}.settings-primary:hover:not(:disabled){background:var(--ui-brand-hover)}button:disabled{opacity:.5;cursor:default}summary{cursor:pointer;min-height:44px;display:flex;align-items:center;font-size:13px;text-decoration:underline;text-underline-offset:4px}input:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid var(--ui-focus);outline-offset:2px}[role=status]{margin-top:16px}
.vision-advanced{min-width:0}.vision-cost-toggle{display:flex;align-items:center;gap:8px;min-height:44px;margin:0}.vision-cost-toggle input{width:18px;min-height:18px;height:18px;margin:0;accent-color:var(--ui-focus)}
select{box-sizing:border-box;width:100%;min-height:44px;padding:10px 12px;border:1px solid var(--ui-line-strong);border-radius:var(--ui-radius-control);font:inherit;color:var(--ui-ink);background:var(--ui-surface)}select:focus-visible{outline:2px solid var(--ui-focus);outline-offset:2px}
@media(max-width:600px){.replay-vision-settings{padding:18px 16px}form,.vision-price-fields{grid-template-columns:minmax(0,1fr)}.vision-actions button{flex:1}}
</style>

