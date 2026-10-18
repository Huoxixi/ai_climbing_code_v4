<template>
  <section class="account-page">
    <header class="account-heading">
      <div><h1>我的账号</h1><p>身份、隐私和当前设备</p></div>
      <span class="account-private"><Lock />默认私密</span>
    </header>

    <div class="account-layout">
      <section class="account-profile" aria-labelledby="profile-title">
        <div class="account-identity">
          <span class="account-avatar" aria-hidden="true">{{ accountInitial }}</span>
          <div><h2 id="profile-title">{{ access.session.displayName || '当前使用者' }}</h2><p>{{ access.session.username || '本地账号' }}</p></div>
        </div>
        <dl>
          <div><dt>登录状态</dt><dd>{{ access.session.authEnabled ? '当前设备已登录' : '本地账号已启用' }}</dd></div>
          <div><dt>记录归属</dt><dd>仅当前账号</dd></div>
          <div><dt>默认可见范围</dt><dd>仅自己可见</dd></div>
        </dl>
      </section>

      <div v-if="workspace==='boulder'" class="account-compact">
        <details><summary>数据与隐私<ArrowRight aria-hidden="true" /></summary><p>新建的照片、线路和备注不会自动公开。公开版本与私人原记录分开保存。</p></details>
        <details><summary>本机草稿<ArrowRight aria-hidden="true" /></summary><p>尚未上传的照片只保存在当前设备。退出登录不会删除已保存记录；本机草稿不会自动出现在其他设备。</p></details>
        <section class="account-session"><button type="button" :disabled="leaving" @click="leave">{{ leaving ? '正在退出…' : '退出当前账号' }}</button><p v-if="accountError" class="account-error" role="alert">{{ accountError }}</p></section>
      </div>
      <div v-else class="account-details">
        <section aria-labelledby="privacy-title">
          <div class="account-section-heading"><CircleCheck /><div><h2 id="privacy-title">记录默认私密</h2><p>新建的照片、线路和备注不会自动公开。</p></div></div>
          <p>未来发布到社区时，会先单独预览公开内容。公开版本与私人原记录分开保存。</p>
        </section>
        <section aria-labelledby="device-title">
          <div class="account-section-heading"><Cellphone /><div><h2 id="device-title">本机草稿</h2><p>尚未上传的照片只保存在当前设备。</p></div></div>
          <p>退出登录不会删除已经保存的记录。仅保存在本机的草稿不会自动出现在其他设备。</p>
        </section>
        <section class="account-session" aria-labelledby="session-title">
          <div class="account-section-heading"><SwitchButton /><div><h2 id="session-title">当前会话</h2><p>退出后可使用本人账号重新登录。</p></div></div>
          <button type="button" :disabled="leaving" @click="leave">{{ leaving ? '正在退出…' : '退出当前账号' }}</button>
          <p v-if="accountError" class="account-error" role="alert">{{ accountError }}</p>
        </section>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, inject, ref } from 'vue'
import { ArrowRight, Cellphone, CircleCheck, Lock, SwitchButton } from '@element-plus/icons-vue'

defineProps({workspace:{type:String,default:'setter'}})
const access = inject('pilotAccess')
const leaving = ref(false)
const accountError = ref('')
const accountInitial = computed(() => (access.session.displayName || access.session.username || '我').trim().charAt(0).toUpperCase())

async function leave() {
  leaving.value = true
  accountError.value = ''
  try {
    await access.logout()
  } catch {
    accountError.value = '退出未完成，请检查网络后重试。'
  } finally {
    leaving.value = false
  }
}
</script>

<style scoped>
.account-page{box-sizing:border-box;width:min(1080px,calc(100% - 64px));margin:0 auto;padding:48px 0 96px;color:var(--ui-ink)}
.account-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:24px}.account-heading h1{margin:0;font-size:28px;line-height:1.35}.account-heading p{margin:4px 0 0;color:var(--ui-ink-muted)}
.account-private{min-height:34px;padding:6px 10px;border-radius:var(--ui-radius-small);background:var(--ui-brand-soft);color:var(--ui-brand-ink);display:inline-flex;align-items:center;gap:7px;font-size:12px;font-weight:600;white-space:nowrap}.account-private svg{width:16px;height:16px}
.account-layout{margin-top:32px;display:grid;grid-template-columns:minmax(280px,360px) minmax(0,1fr);gap:28px;align-items:start}.account-profile{padding:26px;border:1px solid var(--ui-line);border-radius:var(--ui-radius-card);background:var(--ui-surface)}
.account-identity{display:flex;align-items:center;gap:14px}.account-avatar{width:52px;height:52px;flex:none;border-radius:14px;background:var(--ui-brand);color:var(--ui-brand-ink);display:grid;place-items:center;font-size:21px;font-weight:700}.account-identity h2{margin:0;font-size:20px}.account-identity p{margin:3px 0 0;color:var(--ui-ink-muted);overflow-wrap:anywhere}
.account-profile dl{margin:28px 0 0}.account-profile dl div{min-height:52px;border-top:1px solid var(--ui-line);display:grid;grid-template-columns:96px minmax(0,1fr);align-items:center;gap:12px}.account-profile dt{color:var(--ui-ink-muted);font-size:12px}.account-profile dd{margin:0;text-align:right;font-size:13px;font-weight:500}
.account-details{display:grid;gap:0}.account-details>section{padding:24px 0;border-bottom:1px solid var(--ui-line)}.account-details>section:first-child{padding-top:0}.account-section-heading{display:grid;grid-template-columns:24px minmax(0,1fr);gap:12px;align-items:start}.account-section-heading>svg{width:22px;height:22px;margin-top:1px;color:#725315}.account-section-heading h2{margin:0;font-size:18px}.account-section-heading p,.account-details>section>p{margin:4px 0 0;color:var(--ui-ink-muted);line-height:1.65}.account-details>section>p{max-width:68ch;margin-left:36px}
.account-session button{min-height:44px;margin:18px 0 0 36px;padding:0 18px;border:1px solid var(--ui-danger);border-radius:var(--ui-radius-control);background:var(--ui-surface);color:var(--ui-danger);font:inherit;font-weight:600;cursor:pointer}.account-session button:hover:not(:disabled){background:#fff0ed}.account-session button:focus-visible{outline:3px solid var(--ui-focus);outline-offset:2px}.account-session button:disabled{opacity:.55;cursor:default}.account-error{margin-left:36px!important;color:var(--ui-danger)!important}
@media(max-width:860px){.account-page{width:100%;padding:18px 18px calc(36px + env(safe-area-inset-bottom))}.account-heading h1{display:none}.account-heading p{margin:0;font-size:12px}.account-private{display:none}.account-layout{margin-top:16px;grid-template-columns:1fr;gap:8px}.account-profile{padding:18px 16px;box-shadow:none}.account-avatar{width:46px;height:46px;border-radius:12px}.account-profile dl{margin-top:20px}.account-details>section{padding:20px 2px}.account-details>section:first-child{padding-top:20px}.account-details>section>p,.account-session button,.account-error{margin-left:36px!important}}
</style>
