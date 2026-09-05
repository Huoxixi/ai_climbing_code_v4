<template>
  <main class="pilot-login-page">
    <section class="pilot-login-shell member-login" aria-labelledby="login-title">
      <div class="pilot-login-form-panel">
        <h1 id="login-title">{{ registering ? '创建账号' : '登录定线助手' }}</h1>
        <p>{{ registering ? '使用负责人提供的邀请码，创建自己的定线空间。' : '登录后继续你的岩板和照片线路。' }}</p>
        <el-alert v-if="localError || errorMessage" :title="localError || errorMessage" type="error" :closable="false" show-icon role="alert" />
        <el-form label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名"><el-input v-model="form.username" autocomplete="username" maxlength="32" placeholder="3–32位字母、数字或下划线" :disabled="submitting" /></el-form-item>
          <el-form-item v-if="registering" label="昵称"><el-input v-model="form.display_name" autocomplete="nickname" maxlength="40" placeholder="其他页面显示的名字" :disabled="submitting" /></el-form-item>
          <el-form-item label="密码"><el-input v-model="form.password" type="password" show-password :autocomplete="registering ? 'new-password' : 'current-password'" :placeholder="registering ? '至少10个字符' : '输入密码'" :disabled="submitting" /></el-form-item>
          <el-form-item v-if="registering" label="确认密码"><el-input v-model="confirmation" type="password" show-password autocomplete="new-password" :disabled="submitting" /></el-form-item>
          <el-form-item v-if="registering" label="邀请码"><el-input v-model="form.invite_code" autocomplete="off" maxlength="128" placeholder="每个邀请码只能使用一次" :disabled="submitting" /></el-form-item>
          <el-button class="pilot-login-submit" type="primary" native-type="submit" :loading="submitting">{{ registering ? '注册并登录' : '登录' }}</el-button>
          <el-button v-if="registrationEnabled" class="member-switch" text :disabled="submitting" @click="switchMode">{{ registering ? '已有账号？返回登录' : '有邀请码？创建账号' }}</el-button>
          <el-button v-if="quickLoginEnabled && !registering" text :disabled="submitting" @click="emit('quick-login')">进入本地账号</el-button>
        </el-form>
        <p class="member-note">{{ registering ? '邀请码有效期7天，请向负责人获取。' : '忘记密码请联系网站负责人。' }}</p>
      </div>
      <aside class="pilot-account-panel"><h2>公共资源，个人创作</h2><p>已有岩板和岩点作为公共资源，可查看、引用，或另存为自己的副本。</p><p>你新建的岩板、上传的照片和保存的线路仅自己可见。</p></aside>
    </section>
  </main>
</template>
<script setup>
import { reactive, ref } from 'vue'
defineProps({ submitting: Boolean, errorMessage: { type: String, default: '' }, registrationEnabled: Boolean, quickLoginEnabled: Boolean, defaultUsername: String, defaultDisplayName: String })
const emit = defineEmits(['login', 'register', 'quick-login', 'clear-error'])
const registering = ref(false)
const confirmation = ref('')
const localError = ref('')
const form = reactive({ username: '', display_name: '', password: '', invite_code: '' })
function switchMode() {
  registering.value = !registering.value
  form.password = ''; confirmation.value = ''; form.invite_code = ''; localError.value = ''
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
.member-login { max-width: 860px; }
h1 { margin: 0 0 12px; font-size: 28px; }
.el-form { margin-top: 24px; }
.member-switch { display: flex; margin: 12px auto 0; }
.member-note { font-size: 13px; color: #5b6068; }
.pilot-account-panel p { line-height: 1.8; overflow-wrap: anywhere; }
@media (max-width: 640px) { .member-login { display: block; } .pilot-account-panel { display: none; } }
</style>
