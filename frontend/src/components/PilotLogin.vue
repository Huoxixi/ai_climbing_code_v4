<template>
  <main class="pilot-login-page">
    <section class="pilot-login-shell" aria-labelledby="pilot-login-title">
      <div class="pilot-login-form-panel">
        <div class="pilot-login-brand">
          <div class="pilot-login-mark" aria-hidden="true">攀</div>
          <div>
            <h1 id="pilot-login-title">定线助手</h1>
            <p>攀岩线路工作台</p>
          </div>
        </div>
        <p class="pilot-login-intro">
          默认账号已经准备好，进入后即可查看岩板资源并继续定线工作。
        </p>

        <el-alert
          v-if="errorMessage"
          :title="errorMessage"
          type="error"
          :closable="false"
          show-icon
        />

        <section v-if="quickLoginEnabled && !showPasswordLogin" class="pilot-quick-login">
          <div class="pilot-default-account" aria-label="默认登录账号">
            <span class="pilot-account-avatar" aria-hidden="true">{{ defaultInitial }}</span>
            <span class="pilot-default-account-copy">
              <small>默认账号</small>
              <strong>{{ defaultDisplayName || defaultUsername }}</strong>
              <code>{{ defaultUsername }}</code>
            </span>
            <span class="pilot-account-ready">已就绪</span>
          </div>
          <el-button
            class="pilot-login-submit"
            type="primary"
            :loading="submitting"
            :disabled="!defaultUsername"
            @click="emit('quick-login')"
          >
            以{{ defaultDisplayName || defaultUsername }}身份进入
          </el-button>
          <button class="pilot-login-alternate" type="button" @click="openPasswordLogin">
            使用其他账号
          </button>
        </section>

        <el-form v-else class="pilot-login-form" label-position="top" @submit.prevent="submit">
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
          <button
            v-if="quickLoginEnabled"
            class="pilot-login-alternate"
            type="button"
            @click="returnToQuickLogin"
          >
            返回默认账号
          </button>
        </el-form>
        <p class="pilot-login-footnote">账号会话仅保存在当前浏览器，请勿共享试用凭据。</p>
      </div>

      <aside class="pilot-account-panel" aria-label="试用账号">
        <div>
          <h2>需要切换账号？</h2>
          <p>选择对应账号后输入负责人提供的密码。页面不会显示或保存密码。</p>
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

const props = defineProps({
  submitting: { type: Boolean, default: false },
  errorMessage: { type: String, default: '' },
  quickLoginEnabled: { type: Boolean, default: false },
  defaultUsername: { type: String, default: '' },
  defaultDisplayName: { type: String, default: '' },
})

const emit = defineEmits(['login', 'quick-login'])
const usernameInput = ref(null)
const passwordInput = ref(null)
const copiedUsername = ref('')
const form = reactive({ username: '', password: '' })
const showPasswordLogin = ref(!props.quickLoginEnabled)
const defaultInitial = props.defaultDisplayName?.trim().charAt(0) || '马'
const accounts = [
  { label: '马老师试用账号', username: 'ma-trial', initial: '马' },
  { label: '邓老师试用账号', username: 'deng-trial', initial: '邓' },
]

function focusPassword() {
  passwordInput.value?.focus()
}

async function selectAccount(username) {
  showPasswordLogin.value = true
  form.username = username
  form.password = ''
  await nextTick()
  focusPassword()
}

async function openPasswordLogin() {
  showPasswordLogin.value = true
  form.username = ''
  form.password = ''
  await nextTick()
  usernameInput.value?.focus()
}

function returnToQuickLogin() {
  showPasswordLogin.value = false
  form.password = ''
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
