<template>
  <section class="settings-page">
    <header class="settings-heading">
      <div><h1>设置</h1><p>账号、隐私与 AI 服务</p></div>
      <span class="settings-status"><i />{{ localVersion.status }} · {{ localVersion.version }}</span>
    </header>
    <nav v-if="workspace==='boulder'" class="work-tabs settings-tabs" aria-label="设置分类"><button type="button" :aria-pressed="settingsTab==='account'" @click="settingsTab='account'">账号</button><button type="button" :aria-pressed="settingsTab==='service'" @click="settingsTab='service'">AI 服务</button></nav>
    <div class="settings-grid">
      <ReplayVisionSettings v-show="workspace!=='boulder' || settingsTab==='service'" />
      <section v-show="workspace!=='boulder' || settingsTab==='account'" class="settings-card account-card" aria-labelledby="account-title">
        <div class="settings-card-heading"><h2 id="account-title">账号</h2><span class="settings-status"><i />{{ access.session.authEnabled ? '当前已登录' : '本地账号' }}</span></div>
        <div class="account-identity"><span class="account-avatar">{{ accountInitial }}</span><span><strong>{{ access.session.username || '未登录' }}</strong><small>{{ access.session.displayName || (access.session.authEnabled ? '当前账号' : '本地使用者') }}</small></span></div>
        <dl class="account-facts"><div><dt>登录状态</dt><dd>{{ access.session.authEnabled ? '当前设备已登录' : '本地账号已启用' }}</dd></div><div><dt>记录归属</dt><dd>仅当前账号</dd></div><div><dt>默认可见范围</dt><dd>仅自己可见</dd></div></dl>
        <p class="settings-copy">{{ isDesktop ? '当前 Windows 用户使用独立的本地账号与数据目录，关闭程序不会删除已保存内容。' : '你的岩板、照片与线路按账号隔离。退出不会删除本机已保存内容。' }}</p>
        <details class="account-note"><summary>数据与隐私</summary><p>新建的照片、线路和备注不会自动公开。公开版本与私人原记录分开保存。</p></details>
        <details class="account-note"><summary>本机草稿</summary><p>尚未上传的照片只保存在当前设备。退出登录不会删除已保存记录；本机草稿不会自动出现在其他设备。</p></details>
        <button class="settings-danger" type="button" :disabled="leaving" @click="leave">{{ leaving ? '正在退出…' : '退出当前账号' }}</button>
        <p v-if="accountError" class="settings-message is-error" role="alert">{{ accountError }}</p>
      </section>

      <DesktopSettings v-if="isDesktop" v-show="workspace!=='boulder' || settingsTab==='account'" />

      <section v-if="!isDesktop" v-show="workspace!=='boulder' || settingsTab==='service'" class="settings-card api-card" aria-labelledby="api-title">
        <div class="settings-card-heading"><h2 id="api-title">DeepSeek API</h2><span class="settings-status"><i />{{ loaded ? (configured ? '已配置' : '未配置') : (message ? '读取失败' : '读取中') }}</span></div>
        <p class="settings-copy">{{ workspace==='boulder' ? '可选服务配置，不参与默认照片识别。密钥只保存在服务端，不会回显。' : '用于抱石照片的 AI 复核。密钥只保存在服务端，不会回显。' }}</p>
        <label class="settings-label" for="vision-key"><span>API 密钥</span><small>{{ configured ? '输入新密钥替换现有配置' : '填写服务密钥' }}</small></label>
        <div class="settings-input-wrap">
          <input id="vision-key" v-model="apiKey" :type="showKey ? 'text' : 'password'" autocomplete="new-password" spellcheck="false" maxlength="512" :placeholder="configured ? '••••••••••••••••' : '输入 DeepSeek API 密钥'" :disabled="busy || !loaded" @input="message = ''" />
          <button type="button" :disabled="busy || !loaded" :aria-label="showKey ? '隐藏密钥' : '显示密钥'" @click="showKey = !showKey">{{ showKey ? '隐藏' : '显示' }}</button>
        </div>
        <div class="settings-buttons">
          <button class="settings-primary" type="button" :disabled="busy || !loaded || !apiKey.trim()" @click="save">{{ operation === 'save' ? '正在保存…' : '保存密钥' }}</button>
          <button type="button" :disabled="busy || !loaded || (!configured && !apiKey.trim())" @click="test">{{ operation === 'test' ? '正在测试…' : '测试连接' }}</button>
          <button v-if="!loaded && message" type="button" @click="load">重新读取</button>
        </div>
        <aside class="settings-notice"><strong>测试前请注意</strong><span>会发送一张系统测试图片，可能产生少量 API 用量。新密钥测试通过后仍需单独保存。</span></aside>
        <p v-if="message" class="settings-message" :class="{ 'is-error': failed }" role="status">{{ message }}</p>
      </section>
    </div>
  </section>
</template>

<script setup>
import { computed, inject, onMounted, ref } from 'vue'
import api from '../services/apiClient'
import localVersion from '../../../LOCAL_VERSION.json'
import DesktopSettings from './DesktopSettings.vue'
import ReplayVisionSettings from './ReplayVisionSettings.vue'
defineProps({workspace:{type:String,default:'setter'}})
const settingsTab=ref('account')
const isDesktop = Boolean(window.__AI_CLIMBING_DESKTOP__)

const access = inject('pilotAccess')
const apiKey = ref(''), configured = ref(false), loaded = ref(false), operation = ref(''), message = ref(''), failed = ref(false), leaving = ref(false), accountError = ref(''), showKey = ref(false)
const busy = computed(() => Boolean(operation.value))
const accountInitial = computed(() => (access.session.username || 'O').trim().charAt(0).toUpperCase())

async function load(){try{const {data}=await api.get('/api/settings/vision');configured.value=data.configured;loaded.value=true;failed.value=false;message.value=''}catch{failed.value=true;message.value='无法读取配置，请检查连接后重试。'}}
async function save(){operation.value='save';message.value='';try{const {data}=await api.put('/api/settings/vision',{api_key:apiKey.value.trim()});configured.value=data.configured;apiKey.value='';showKey.value=false;failed.value=false;message.value='密钥已保存，下次 AI 复核将使用此配置。'}catch{failed.value=true;message.value='密钥未保存，请检查输入和网络后重试。'}finally{operation.value=''}}
async function test(){operation.value='test';message.value='';try{const {data}=await api.post('/api/settings/vision/test',{api_key:apiKey.value.trim()},{timeout:40000});failed.value=!data.connected;message.value=data.message+(data.connected&&apiKey.value.trim()?' 新密钥尚未保存。':'')}catch{failed.value=true;message.value='测试未完成，请检查网络或稍后重试。'}finally{operation.value=''}}
async function leave(){leaving.value=true;accountError.value='';try{await access.logout()}catch{accountError.value='退出未完成，请检查网络后重试。'}finally{leaving.value=false}}
onMounted(() => { if (!isDesktop) load() })
</script>

<style scoped>
.account-facts{margin:0}.account-facts>div{display:flex;justify-content:space-between;gap:16px;padding:12px 0;border-top:1px solid var(--ui-line);font-size:13px}.account-facts dt{color:var(--ui-ink-muted)}.account-facts dd{margin:0;text-align:right}.account-note{border-bottom:1px solid var(--ui-line);font-size:13px}.account-note summary{min-height:44px;align-content:center;cursor:pointer;font-weight:500}.account-note summary:focus-visible{outline:2px solid var(--ui-focus);outline-offset:2px}.account-note p{margin:0 0 12px;color:var(--ui-ink-muted);line-height:1.65;max-width:65ch}
.settings-page{box-sizing:border-box;width:min(1200px,calc(100% - 64px));margin:0 auto;padding:48px 0 96px;color:var(--ui-ink)}.settings-heading{min-height:54px;display:flex;align-items:center;justify-content:space-between;gap:24px}.settings-heading h1{font-size:28px}.settings-heading p{margin-top:4px;color:var(--ui-ink-muted)}
.settings-status{width:fit-content;min-height:32px;padding:6px 10px;border-radius:var(--ui-radius-small);background:var(--ui-brand-soft);color:var(--ui-brand-ink);display:inline-flex;align-items:center;gap:7px;font-size:12px;white-space:nowrap}.settings-status i{width:7px;height:7px;border-radius:50%;background:var(--ui-success)}
.settings-grid{grid-auto-rows:max-content;margin-top:28px;display:grid;grid-template-columns:420px minmax(0,1fr);gap:24px;align-items:start}.settings-card{padding:28px;border-radius:var(--ui-radius-card);background:var(--ui-surface);box-shadow:var(--ui-shadow-float)}.settings-card-heading{min-height:38px;display:flex;align-items:center;justify-content:space-between;gap:16px}.settings-card h2{font-size:20px}
.account-card{min-height:420px;display:flex;flex-direction:column;gap:18px}.account-identity{display:flex;align-items:center;gap:14px}.account-avatar{width:48px;height:48px;flex:none;border-radius:var(--ui-radius-card);background:var(--ui-brand-soft);color:var(--ui-brand-ink);display:grid;place-items:center;font-size:20px;font-weight:600}.account-identity>span:last-child{min-width:0;display:grid;gap:2px}.account-identity strong{overflow-wrap:anywhere;font-size:20px}.account-identity small{color:var(--ui-ink-muted)}.settings-copy{max-width:65ch;color:var(--ui-ink-muted);line-height:1.65}
.settings-danger{width:100%;min-height:46px;margin-top:auto;border:1px solid var(--ui-danger);border-radius:var(--ui-radius-control);background:var(--ui-surface);color:var(--ui-danger);font-weight:500;cursor:pointer}.api-card{min-height:520px;display:flex;flex-direction:column;gap:16px}.settings-label{margin-top:2px;display:flex;align-items:center;justify-content:space-between;gap:16px;font-size:13px;font-weight:500}.settings-label small{color:var(--ui-ink-muted);font-weight:400}
.settings-input-wrap{min-height:48px;border:1px solid var(--ui-line-strong);border-radius:var(--ui-radius-control);background:var(--ui-surface);display:flex;align-items:center;overflow:hidden}.settings-input-wrap:focus-within{outline:3px solid var(--ui-focus);outline-offset:2px}.settings-input-wrap input{min-width:0;height:46px;padding:0 14px;border:0;outline:0;background:transparent;color:var(--ui-ink);flex:1}.settings-input-wrap input::placeholder{color:var(--ui-ink-faint)}.settings-input-wrap button{min-width:64px;height:44px;border:0;background:transparent;color:var(--ui-ink-muted);cursor:pointer}
.settings-buttons{display:flex;flex-wrap:wrap;gap:12px}.settings-buttons button{min-width:150px;min-height:46px;padding:0 18px;border:1px solid var(--ui-line-strong);border-radius:var(--ui-radius-control);background:var(--ui-surface);color:var(--ui-ink);font-weight:500;cursor:pointer}.settings-buttons .settings-primary{border-color:var(--ui-brand);background:var(--ui-brand);color:var(--ui-brand-ink)}.settings-notice{margin-top:auto;padding:14px;border-radius:var(--ui-radius-small);background:var(--ui-surface-subtle);display:grid;gap:4px}.settings-notice strong{font-size:13px}.settings-notice span{color:var(--ui-ink-muted);font-size:12px}
.settings-message{padding:12px;border-radius:var(--ui-radius-small);background:var(--ui-brand-soft);line-height:1.6}.settings-message.is-error{color:#92392d;background:#fff0ed}.settings-card button:hover:not(:disabled){background:var(--ui-brand-soft)}.settings-card .settings-primary:hover:not(:disabled){background:var(--ui-brand-hover)}.settings-card button:disabled,.settings-card input:disabled{opacity:.5;cursor:default}.settings-card button:focus-visible{outline:3px solid var(--ui-focus);outline-offset:2px}
@media(max-width:860px){.settings-page{width:100%;padding:16px 18px calc(34px + env(safe-area-inset-bottom));overflow:hidden}.settings-heading{min-height:auto;align-items:flex-start}.settings-heading h1{display:none}.settings-heading p{font-size:12px}.settings-heading .settings-status{display:none}.settings-grid{min-width:0;margin-top:14px;grid-template-columns:minmax(0,1fr);gap:14px}.settings-card{box-sizing:border-box;min-width:0;min-height:0;padding:18px 16px;box-shadow:none}.account-card{gap:12px}.account-identity{display:block}.account-avatar{display:none}.account-identity strong{font-size:20px}.settings-copy{overflow-wrap:anywhere}.settings-danger{min-height:46px;margin-top:0}.api-card{gap:12px}.settings-label{margin-top:4px}.settings-label small{display:none}.settings-buttons{display:grid}.settings-buttons button{box-sizing:border-box;width:100%;min-width:0}.settings-notice{margin-top:2px;padding:0;background:transparent}.settings-notice strong{display:none}}
</style>
