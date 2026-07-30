<template>
  <div v-if="loading" class="pilot-loading" aria-live="polite">
    <div class="pilot-loading-card">
      <span class="pilot-spinner" aria-hidden="true"></span>
      <strong>正在检查登录状态</strong>
      <small>请稍候，不会影响已保存的数据。</small>
    </div>
  </div>
  <PilotLogin
    v-else-if="!session.authenticated"
    :submitting="loginSubmitting"
    :error-message="loginError"
    @login="login"
  />
  <App v-else />
</template>

<script setup>
import { onBeforeUnmount, onMounted, provide, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import App from './App.vue'
import PilotLogin from './components/PilotLogin.vue'
import apiClient from './services/apiClient'

const loading = ref(true)
const loginSubmitting = ref(false)
const loginError = ref('')
const session = reactive({
  authenticated: false,
  username: '',
  displayName: '',
  authEnabled: true,
})
const lease = reactive({
  active: false,
  ownedByMe: false,
  holderDisplayName: '',
  expiresAt: null,
  loading: false,
})

let heartbeatTimer = null
let statusTimer = null
let responseInterceptor = null

function applySession(payload) {
  session.authenticated = Boolean(payload?.authenticated)
  session.username = payload?.username || ''
  session.displayName = payload?.display_name || ''
  session.authEnabled = payload?.auth_enabled !== false
}

function applyLease(payload) {
  lease.active = Boolean(payload?.active)
  lease.ownedByMe = Boolean(payload?.owned_by_me)
  lease.holderDisplayName = payload?.holder_display_name || ''
  lease.expiresAt = payload?.expires_at || null
}

async function loadSession() {
  try {
    const response = await apiClient.get('/api/auth/session')
    applySession(response.data)
    await refreshLease()
  } catch (error) {
    if (error?.response?.status !== 401) {
      loginError.value = '暂时无法连接服务器，请稍后刷新页面。'
    }
    applySession({ authenticated: false })
  } finally {
    loading.value = false
  }
}

async function login(credentials) {
  loginSubmitting.value = true
  loginError.value = ''
  try {
    const response = await apiClient.post('/api/auth/login', credentials)
    applySession(response.data)
    await refreshLease()
  } catch (error) {
    loginError.value = error?.response?.data?.detail || '登录失败，请检查网络后重试。'
  } finally {
    loginSubmitting.value = false
  }
}

async function logout() {
  try {
    await apiClient.post('/api/auth/logout')
  } finally {
    applyLease({})
    applySession({ authenticated: false })
  }
}

async function refreshLease() {
  if (!session.authenticated) return
  try {
    const response = await apiClient.get('/api/pilot/edit-lease')
    applyLease(response.data)
  } catch (error) {
    if (error?.response?.status !== 401) {
      console.warn('Unable to refresh edit lease', error)
    }
  }
}

async function acquireLease() {
  lease.loading = true
  try {
    const response = await apiClient.post('/api/pilot/edit-lease/acquire')
    applyLease(response.data)
    ElMessage.success('已取得15分钟编辑权')
  } catch (error) {
    ElMessage.warning(error?.response?.data?.detail || '暂时无法取得编辑权')
    await refreshLease()
  } finally {
    lease.loading = false
  }
}

async function releaseLease() {
  lease.loading = true
  try {
    const response = await apiClient.delete('/api/pilot/edit-lease')
    applyLease(response.data)
    ElMessage.success('编辑权已释放')
  } finally {
    lease.loading = false
  }
}

async function heartbeat() {
  if (!lease.ownedByMe) return
  try {
    const response = await apiClient.post('/api/pilot/edit-lease/heartbeat')
    applyLease(response.data)
  } catch (error) {
    applyLease({})
    ElMessage.warning(error?.response?.data?.detail || '编辑权已失效')
  }
}

provide('pilotAccess', {
  session,
  lease,
  acquireLease,
  releaseLease,
  logout,
})

onMounted(() => {
  responseInterceptor = apiClient.interceptors.response.use(
    (response) => response,
    (error) => {
      const path = error?.config?.url || ''
      if (error?.response?.status === 401 && !path.includes('/api/auth/login')) {
        applyLease({})
        applySession({ authenticated: false })
      }
      if (error?.response?.status === 423 && !path.includes('/api/pilot/edit-lease')) {
        ElMessage.warning(error?.response?.data?.detail || '当前处于浏览模式，请先取得编辑权。')
        refreshLease()
      }
      return Promise.reject(error)
    },
  )
  loadSession()
  heartbeatTimer = window.setInterval(heartbeat, 30_000)
  statusTimer = window.setInterval(refreshLease, 10_000)
})

onBeforeUnmount(() => {
  window.clearInterval(heartbeatTimer)
  window.clearInterval(statusTimer)
  if (responseInterceptor !== null) {
    apiClient.interceptors.response.eject(responseInterceptor)
  }
})
</script>
