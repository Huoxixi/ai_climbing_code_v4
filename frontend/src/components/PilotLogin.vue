<template>
  <main class="pilot-login-page member-login-page">
    <div class="login-photo" aria-hidden="true"><img :src="loginBackdrop" alt="" /></div>
    <div class="login-photo-fade" aria-hidden="true" />
    <section class="member-login" aria-labelledby="login-title">
      <div class="login-brand" aria-label="攀岩助手">
        <span class="login-brand-mark"><Grid /></span>
        <span><strong>攀岩助手</strong><small>CLIMB SETTER</small></span>
      </div>
      <button class="login-workspace-back" type="button" :disabled="submitting" @click="emit('change-workspace')">
        <ArrowLeft />
        <span><small>当前进入</small><strong>{{ workspaceLabel }}</strong></span>
        <em>更换项目</em>
      </button>
      <header class="login-heading">
        <h1 id="login-title">{{ registering ? '创建账号' : '登录攀岩助手' }}</h1>
        <p>{{ registering ? '使用负责人提供的邀请码，创建自己的攀岩记录空间。' : '登录后继续你的岩板和照片线路。' }}</p>
      </header>
      <el-alert v-if="localError || errorMessage" class="login-alert" :title="localError || errorMessage" type="error" :closable="false" show-icon role="alert" />
      <el-form class="member-login-form" label-position="top" @submit.prevent="submit">
        <el-form-item label="用户名"><el-input v-model="form.username" autocomplete="username" maxlength="32" :placeholder="registering ? '3–32位字母、数字或下划线' : '输入用户名'" :disabled="submitting" /></el-form-item>
        <el-form-item v-if="registering" label="昵称"><el-input v-model="form.display_name" autocomplete="nickname" maxlength="40" placeholder="其他页面显示的名字" :disabled="submitting" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password :autocomplete="registering ? 'new-password' : 'current-password'" :placeholder="registering ? '至少10个字符' : '输入密码'" :disabled="submitting" /></el-form-item>
        <el-form-item v-if="registering" label="确认密码"><el-input v-model="confirmation" type="password" show-password autocomplete="new-password" placeholder="再次输入密码" :disabled="submitting" /></el-form-item>
        <el-form-item v-if="registering" label="邀请码"><el-input v-model="form.invite_code" autocomplete="off" maxlength="128" placeholder="每个邀请码只能使用一次" :disabled="submitting" /></el-form-item>
        <el-button class="pilot-login-submit" type="primary" native-type="submit" :loading="submitting">{{ registering ? `注册并进入${workspaceLabel}` : `登录并进入${workspaceLabel}` }}</el-button>
        <div class="login-secondary-actions">
          <button v-if="registrationEnabled" type="button" :disabled="submitting" @click="switchMode">{{ registering ? '已有账号？返回登录' : '有邀请码？创建账号' }}</button>
          <button v-if="quickLoginEnabled && !registering" type="button" :disabled="submitting" @click="emit('quick-login')">进入本地账号</button>
        </div>
        <p class="member-note">{{ registering ? '邀请码有效期7天，请向负责人获取。' : '忘记密码请联系网站负责人。' }}</p>
      </el-form>
    </section>
    <aside class="login-privacy-note"><strong>你的照片与线路仅自己可见</strong><span>公共岩板可引用；个人上传和保存内容按账号隔离。</span></aside>
  </main>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ArrowLeft, Grid } from '@element-plus/icons-vue'
import loginBackdrop from '../assets/login-climber-pexels-5916407.jpg'
const props = defineProps({
  submitting: Boolean,
  errorMessage: { type: String, default: '' },
  registrationEnabled: Boolean,
  quickLoginEnabled: Boolean,
  defaultUsername: { type: String, default: '' },
  defaultDisplayName: { type: String, default: '' },
  workspace: { type: String, required: true },
})
const emit = defineEmits(['login', 'register', 'quick-login', 'clear-error', 'change-workspace'])
const workspaceLabel = computed(() => props.workspace === 'boulder' ? '抱石项目' : '定线项目')
const registering = ref(false)
const confirmation = ref('')
const localError = ref('')
const form = reactive({ username: props.defaultUsername, display_name: props.defaultDisplayName, password: '', invite_code: '' })

watch(() => props.defaultUsername, (value) => { if (!form.username) form.username = value || '' })
watch(() => props.defaultDisplayName, (value) => { if (!form.display_name) form.display_name = value || '' })

function switchMode() {
  registering.value = !registering.value
  form.password = ''
  confirmation.value = ''
  form.invite_code = ''
  localError.value = ''
  emit('clear-error')
}

function submit() {
  localError.value = ''
  if (!form.username.trim() || !form.password) { localError.value = '请填写用户名和密码。'; return }
  if (registering.value) {
    if (!/^[a-z][a-z0-9_]{2,31}$/.test(form.username.trim().toLowerCase())) { localError.value = '用户名需以字母开头，使用3–32位字母、数字或下划线。'; return }
    if (form.password.length < 10 || new TextEncoder().encode(form.password).length > 72) { localError.value = '密码至少10个字符，长度不超过72字节。'; return }
    if (form.password !== confirmation.value) { localError.value = '两次密码不一致。'; return }
    if (!form.display_name.trim() || !form.invite_code.trim()) { localError.value = '请填写昵称和邀请码。'; return }
    emit('register', { ...form, username: form.username.trim() })
  } else emit('login', { username: form.username.trim(), password: form.password })
}
</script>

<style scoped>
.member-login-page{position:relative;box-sizing:border-box;min-height:100vh;padding:190px 24px 70px;overflow:hidden;background:var(--ui-ground);display:grid;place-items:start center}
.login-photo{position:absolute;inset:0 0 auto;height:390px;overflow:hidden}.login-photo img{width:100%;height:100%;object-fit:cover;object-position:center 38%;display:block}
.login-photo-fade{position:absolute;z-index:1;top:160px;right:0;left:0;height:250px;background:linear-gradient(180deg,rgba(247,245,239,0),rgba(247,245,239,.12) 38%,rgba(247,245,239,.76) 72%,var(--ui-ground))}
.member-login{position:relative;z-index:2;width:min(560px,100%);min-height:640px;padding:48px 56px;border-radius:28px;background:var(--ui-surface);box-shadow:0 16px 40px -8px rgba(10,18,15,.16)}
.login-brand{display:flex;align-items:center;gap:12px}.login-brand-mark{width:48px;height:48px;border-radius:var(--ui-radius-card);background:var(--ui-brand);color:var(--ui-brand-ink);display:grid;place-items:center}.login-brand-mark svg{width:22px;height:22px}.login-brand>span:last-child{display:grid}.login-brand strong{font-size:20px;line-height:1.35}.login-brand small{color:var(--ui-ink-muted);font-size:12px;line-height:1.5}
.login-heading{margin-top:18px}.login-heading h1{font-size:28px}.login-heading p{margin-top:8px;color:var(--ui-ink-muted)}.login-alert{margin-top:18px}.member-login-form{margin-top:18px}
.login-workspace-back{box-sizing:border-box;width:100%;min-height:58px;margin-top:20px;padding:9px 12px;border:1px solid var(--ui-line);border-radius:var(--ui-radius-control);background:var(--ui-surface-raised);display:grid;grid-template-columns:24px minmax(0,1fr) auto;align-items:center;gap:10px;text-align:left;cursor:pointer}.login-workspace-back svg{width:18px}.login-workspace-back>span{display:grid}.login-workspace-back small{color:var(--ui-ink-muted);font-size:10px}.login-workspace-back strong{font-size:14px}.login-workspace-back em{color:var(--ui-ink-muted);font-size:12px;font-style:normal}.login-workspace-back:hover{border-color:var(--ui-brand);background:var(--ui-brand-soft)}
.member-login-form :deep(.el-form-item){margin-bottom:18px}.member-login-form :deep(.el-form-item__label){height:auto;padding-bottom:8px;color:var(--ui-ink);font-size:13px;font-weight:500;line-height:18px}.member-login-form :deep(.el-input__wrapper){min-height:48px;padding-inline:14px;box-shadow:0 0 0 1px var(--ui-line-strong) inset}
.pilot-login-submit{width:100%;min-height:48px;border-radius:var(--ui-radius-control)}.login-secondary-actions{min-height:28px;margin-top:12px;display:flex;align-items:center;justify-content:space-between;gap:14px}.login-secondary-actions button{min-height:36px;padding:4px 0;border:0;background:transparent;color:var(--ui-ink);font-size:13px;font-weight:500;cursor:pointer}.login-secondary-actions button:hover{text-decoration:underline;text-underline-offset:4px}.login-secondary-actions button:disabled{opacity:.5;cursor:default}.member-note{margin-top:12px;color:var(--ui-ink-muted);font-size:12px}.login-privacy-note{display:none}
@media(max-width:640px){.member-login-page{min-height:100dvh;padding:28px 20px 40px;overflow:visible;display:block}.login-photo,.login-photo-fade{display:none}.member-login{box-sizing:border-box;width:100%;min-height:0;padding:0;border-radius:0;background:transparent;box-shadow:none}.login-brand-mark{width:40px;height:40px}.login-brand-mark svg{width:20px;height:20px}.login-heading{margin-top:24px}.login-heading h1{font-size:28px}.login-alert{margin:18px 0 -2px}.member-login-form{box-sizing:border-box;width:100%;margin-top:24px;padding:24px 20px;border-radius:var(--ui-radius-card);background:var(--ui-surface)}.login-secondary-actions{margin-top:18px;display:grid;gap:10px}.login-secondary-actions button{box-sizing:border-box;width:100%;min-height:48px;padding:0 14px;border:1px solid var(--ui-line-strong);border-radius:var(--ui-radius-control)}.login-secondary-actions button:last-child{border-color:transparent}.member-note{margin-top:18px}.login-privacy-note{box-sizing:border-box;width:100%;margin-top:24px;padding:16px;border-radius:var(--ui-radius-card);background:var(--ui-brand-soft);color:var(--ui-brand-ink);display:grid;gap:8px}.login-privacy-note strong{font-size:13px}.login-privacy-note span{font-size:12px}}
</style>
