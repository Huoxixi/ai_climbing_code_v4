<template>
  <main class="pilot-login-page">
    <section class="pilot-login-shell" aria-labelledby="pilot-login-title">
      <div class="pilot-login-form-panel">
        <div class="pilot-login-brand">
          <div class="pilot-login-mark" aria-hidden="true">攀</div>
          <div>
            <p class="eyebrow">小范围试用</p>
            <h1 id="pilot-login-title">攀岩定线系统</h1>
          </div>
        </div>
        <p class="pilot-login-intro">
          登录后可以查看完整岩板资源。需要修改内容时，请先在系统顶部取得编辑权。
        </p>

        <el-alert
          v-if="errorMessage"
          :title="errorMessage"
          type="error"
          :closable="false"
          show-icon
        />

        <el-form class="pilot-login-form" label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名">
            <el-input
              ref="usernameInput"
              v-model.trim="form.username"
              autocomplete="username"
              placeholder="请输入试用账号"
              @keyup.enter="focusPassword"
            />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              ref="passwordInput"
              v-model="form.password"
              type="password"
              autocomplete="current-password"
              placeholder="请输入负责人私下发送的密码"
              show-password
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-button
            class="pilot-login-submit"
            type="primary"
            native-type="submit"
            :loading="submitting"
            :disabled="!form.username || !form.password"
          >
            登录系统
          </el-button>
        </el-form>
        <p class="pilot-login-footnote">试用流量会经过 Cloudflare 加密转发，请勿转发临时链接或账号。</p>
      </div>

      <aside class="pilot-account-panel" aria-label="试用账号">
        <div>
          <p class="eyebrow">选择账号</p>
          <h2>两位老师使用各自账号</h2>
          <p>点击卡片会自动填写用户名。密码不在页面显示，请向负责人获取。</p>
        </div>
        <div class="pilot-account-grid">
          <article
            v-for="account in accounts"
            :key="account.username"
            class="pilot-account-card"
            role="button"
            tabindex="0"
            @click="selectAccount(account.username)"
            @keydown.enter="selectAccount(account.username)"
            @keydown.space.prevent="selectAccount(account.username)"
          >
            <span class="pilot-account-avatar" aria-hidden="true">{{ account.initial }}</span>
            <strong>{{ account.label }}</strong>
            <code>{{ account.username }}</code>
            <small>密码请向负责人获取</small>
            <span class="pilot-account-actions">
              <span>填写此用户名</span>
              <button type="button" @click.stop="copyUsername(account.username)">
                {{ copiedUsername === account.username ? '已复制' : '复制用户名' }}
              </button>
            </span>
          </article>
        </div>
      </aside>
    </section>
  </main>
</template>

<script setup>
import { nextTick, reactive, ref } from 'vue'

defineProps({
  submitting: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
})

const emit = defineEmits(['login'])
const usernameInput = ref(null)
const passwordInput = ref(null)
const copiedUsername = ref('')
const form = reactive({ username: '', password: '' })
const accounts = [
  { label: '马老师试用账号', username: 'ma-trial', initial: '马' },
  { label: '邓老师试用账号', username: 'deng-trial', initial: '邓' },
]

function focusPassword() {
  passwordInput.value?.focus()
}

async function selectAccount(username) {
  form.username = username
  form.password = ''
  await nextTick()
  focusPassword()
}

async function copyUsername(username) {
  try {
    await navigator.clipboard.writeText(username)
    copiedUsername.value = username
    window.setTimeout(() => {
      if (copiedUsername.value === username) copiedUsername.value = ''
    }, 1600)
  } catch {
    selectAccount(username)
  }
}

function submit() {
  if (!form.username || !form.password) return
  emit('login', { username: form.username, password: form.password })
}
</script>
