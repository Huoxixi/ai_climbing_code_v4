<template>
  <section class="settings-page">
    <h1>设置</h1>
    <p class="settings-hint">{{localVersion.status}} · {{localVersion.version}}</p>
    <section class="settings-section" aria-labelledby="account-title">
      <h2 id="account-title">账号</h2>
      <p class="settings-username">{{access.session.username || '未登录'}} <span v-if="access.session.displayName">{{access.session.displayName}}</span></p>
      <p class="settings-hint">{{access.session.authEnabled ? '当前已登录，可退出后使用其他账号登录。' : '当前使用本地账号，无需密码。'}}</p>
      <button type="button" :disabled="leaving" @click="leave">{{leaving?'正在退出…':'退出登录'}}</button>
      <p v-if="accountError" role="alert">{{accountError}}</p>
    </section>
    <section class="settings-section" aria-labelledby="api-title">
      <h2 id="api-title">DeepSeek API</h2>
      <p class="settings-hint">用于抱石照片的 AI 复核。密钥只保存在服务端，不会回显。</p>
      <label for="vision-key">API 密钥 <span>{{loaded ? (configured?'已配置':'未配置') : '正在读取…'}}</span></label>
      <input id="vision-key" v-model="apiKey" type="password" autocomplete="new-password" spellcheck="false" maxlength="512" :placeholder="configured?'输入新密钥可替换已保存的密钥':'输入 DeepSeek API 密钥'" :disabled="busy || !loaded" @input="message=''" />
      <div class="settings-buttons"><button class="settings-primary" :disabled="busy || !loaded || !apiKey.trim()" @click="save">{{operation==='save'?'正在保存…':'保存密钥'}}</button><button :disabled="busy || !loaded || (!configured && !apiKey.trim())" @click="test">{{operation==='test'?'正在测试…':'测试连接'}}</button><button v-if="!loaded && message" @click="load">重新读取</button></div>
      <p class="settings-hint">测试会发送一张系统测试图片，可能产生少量 API 用量。输入新密钥时测试当前输入，未输入时测试已保存密钥。</p>
      <p v-if="message" class="settings-message" :class="{ 'is-error':failed }" role="status">{{message}}</p>
    </section>
  </section>
</template>

<script setup>
import {computed,inject,onMounted,ref} from 'vue'
import api from '../services/apiClient'
import localVersion from '../../../LOCAL_VERSION.json'
const access=inject('pilotAccess'), apiKey=ref(''), configured=ref(false),loaded=ref(false),operation=ref(''),message=ref(''),failed=ref(false),leaving=ref(false),accountError=ref('')
const busy=computed(()=>!!operation.value)
async function load(){try{const {data}=await api.get('/api/settings/vision');configured.value=data.configured;loaded.value=true;message.value=''}catch{failed.value=true;message.value='无法读取配置，请检查连接后重试。'}}
async function save(){operation.value='save';message.value='';try{const {data}=await api.put('/api/settings/vision',{api_key:apiKey.value.trim()});configured.value=data.configured;apiKey.value='';failed.value=false;message.value='密钥已保存，下次 AI 复核将使用此配置。'}catch{failed.value=true;message.value='密钥未保存，请检查输入和网络后重试。'}finally{operation.value=''}}
async function test(){operation.value='test';message.value='';try{const {data}=await api.post('/api/settings/vision/test',{api_key:apiKey.value.trim()},{timeout:40000});failed.value=!data.connected;message.value=data.message+(data.connected && apiKey.value.trim()?' 新密钥尚未保存。':'')}catch{failed.value=true;message.value='测试未完成，请检查网络或稍后重试。'}finally{operation.value=''}}
async function leave(){leaving.value=true;accountError.value='';try{await access.logout()}catch{accountError.value='退出未完成，请检查网络后重试。'}finally{leaving.value=false}}
onMounted(load)
</script>

<style scoped>
.settings-page{max-width:720px;margin:0 auto;padding:32px 24px 100px;color:var(--ink)}.settings-page h1{font-size:28px;margin:0 0 30px}.settings-section{padding:0 0 30px;margin-bottom:30px;border-bottom:1px solid var(--line)}.settings-section h2{font-size:19px;margin:0 0 16px}.settings-username{font-size:20px;overflow-wrap:anywhere}.settings-username span{font-size:14px;margin-left:12px;color:var(--ink-soft)}.settings-hint{color:var(--ink-soft);font-size:14px;line-height:1.7;max-width:65ch}.settings-section label{display:block;margin:22px 0 8px;font-weight:600}.settings-section label span{font-size:13px;font-weight:400;color:var(--ink-soft);margin-left:12px}.settings-section input{width:100%;box-sizing:border-box;border:1px solid var(--line);border-radius:8px;padding:12px;font:inherit;background:white;color:var(--ink)}.settings-buttons{display:flex;flex-wrap:wrap;gap:12px;margin-top:16px}.settings-section button{min-height:44px;padding:10px 18px;border:1px solid var(--line);border-radius:8px;background:white;color:var(--ink);font:inherit;cursor:pointer}.settings-section .settings-primary{background:var(--brand);color:var(--brand-ink);border-color:var(--brand)}.settings-section button:hover{background:var(--brand-soft)}.settings-section button:disabled{opacity:.5;cursor:default}.settings-section :is(button,input):focus-visible{outline:3px solid var(--brand);outline-offset:2px}.settings-message{padding:12px;background:var(--brand-soft);line-height:1.6}.settings-message.is-error{color:#92392d;background:#fff0ed}@media(max-width:600px){.settings-page{padding:24px 18px 100px}}
</style>
