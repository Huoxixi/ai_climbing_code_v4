<template>
  <div v-if="loading" class="pilot-loading" aria-live="polite">
    <div class="pilot-loading-card">
      <span class="pilot-spinner" aria-hidden="true"></span>
      <strong>正在检查登录状态</strong>
      <small>请稍候，不会影响已保存的数据。</small>
    </div>
  </div>
  <WorkspaceChooser
    v-else-if="!activeWorkspace"
    :authenticated="session.authenticated"
    :username="session.username"
    :display-name="session.displayName"
    @select="selectWorkspace"
  />
  <div v-else-if="!session.authenticated && !session.authEnabled" class="pilot-loading">
    <div class="pilot-loading-card"><strong>已退出登录</strong><p>本地账号 owner · 负责人</p><p>照片和线路进度已保留。</p><el-button type="primary" :loading="loginSubmitting" @click="localLogin">登录本地账号</el-button><p v-if="loginError" role="alert">{{loginError}}</p></div>
  </div>
  <PilotLogin
    v-else-if="!session.authenticated"
    :submitting="loginSubmitting"
    :error-message="loginError"
    :registration-enabled="session.registrationEnabled"
    :quick-login-enabled="session.quickLoginEnabled"
    :default-username="session.defaultUsername"
    :default-display-name="session.defaultDisplayName"
    :workspace="activeWorkspace"
    @login="login"
    @register="register"
    @clear-error="loginError = ''"
    @quick-login="quickLogin"
    @change-workspace="openWorkspaceChooser"
  />
  <App v-else :key="`${session.username}:${activeWorkspace}`" :workspace="activeWorkspace" @change-workspace="openWorkspaceChooser" />
</template>

<script setup>
import { onBeforeUnmount, onMounted, provide, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import App from './App.vue'
import PilotLogin from './components/PilotLogin.vue'
import WorkspaceChooser from './components/WorkspaceChooser.vue'
import apiClient from './services/apiClient'
import { isLocalWorkspace, localWorkspaceHash } from './utils/localWorkspace.js'

const workspaceStorageKey = 'climbing-active-workspace'
const localWorkspaceOnly = isLocalWorkspace(window)
provide('localWorkspaceOnly',localWorkspaceOnly)
if(localWorkspaceOnly){
  const hash=localWorkspaceHash(location.hash)
  if(hash!==location.hash)history.replaceState(null,'',hash)
  sessionStorage.setItem(workspaceStorageKey,'boulder')
}else if(location.hash==='#/account'){
  sessionStorage.setItem(workspaceStorageKey,'boulder')
  history.replaceState(null,'','#/settings')
}
const workspaceChooserHash = '#/projects'
const boulderPageKeys = ['photo-routes', 'my-records', 'climb-replay', 'account']
const setterPageKeys = ['dashboard', 'studio', 'library', 'boards', 'standard-board', 'simulation', 'ai-lab']
const storedWorkspace = sessionStorage.getItem(workspaceStorageKey)
const initialPage = String(location.hash || '').replace(/^#\/?/, '').split('/')[0]
const inferredWorkspace = boulderPageKeys.includes(initialPage) ? 'boulder' : (setterPageKeys.includes(initialPage) ? 'setter' : '')
const activeWorkspace = ref(location.hash === workspaceChooserHash ? '' : (inferredWorkspace || (['boulder', 'setter'].includes(storedWorkspace) ? storedWorkspace : '')))
const loading = ref(true)
const loginSubmitting = ref(false)
const loginError = ref('')
const session = reactive({
  authenticated: false,
  username: '',
  displayName: '',
  authEnabled: true,
  registrationEnabled: false,
  quickLoginEnabled: false,
  defaultUsername: '',
  defaultDisplayName: '',
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
  if (Object.hasOwn(payload || {}, 'registration_enabled')) session.registrationEnabled = Boolean(payload.registration_enabled)
  if (Object.hasOwn(payload || {}, 'quick_login_enabled')) {
    session.quickLoginEnabled = Boolean(payload.quick_login_enabled)
    session.defaultUsername = payload.default_username || ''
    session.defaultDisplayName = payload.default_display_name || ''
  }
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
    if (!session.authEnabled && sessionStorage.getItem('local-account-signed-out') === 'true') session.authenticated = false
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

async function register(credentials) {
  loginSubmitting.value = true
  loginError.value = ''
  try {
    const response = await apiClient.post('/api/auth/register', credentials)
    applySession(response.data)
    await refreshLease()
  } catch (error) {
    loginError.value = error?.response?.data?.detail || '注册失败，请检查网络后重试。'
  } finally { loginSubmitting.value = false }
}

async function quickLogin() {
  loginSubmitting.value = true
  loginError.value = ''
  try {
    const response = await apiClient.post('/api/auth/quick-login')
    applySession(response.data)
    await refreshLease()
  } catch (error) {
    loginError.value = error?.response?.data?.detail || '快速登录失败，请使用其他账号登录。'
  } finally {
    loginSubmitting.value = false
  }
}

async function logout() {
  await apiClient.post('/api/auth/logout')
  const authEnabled = session.authEnabled
  if (!authEnabled) sessionStorage.setItem('local-account-signed-out','true')
  applyLease({})
  applySession({ authenticated: false, auth_enabled: authEnabled })
  resetWorkspace()
}

function selectWorkspace(workspace) {
  if(localWorkspaceOnly && workspace!=='boulder')return
  if (!['boulder', 'setter'].includes(workspace)) return
  activeWorkspace.value = workspace
  sessionStorage.setItem(workspaceStorageKey, workspace)
  const targetHash = workspace === 'boulder' ? '#/photo-routes' : '#/dashboard'
  if (location.hash !== targetHash) history.pushState(null, '', targetHash)
}

function openWorkspaceChooser() {
  if(localWorkspaceOnly)return
  activeWorkspace.value = ''
  if (location.hash !== workspaceChooserHash) history.pushState(null, '', workspaceChooserHash)
}

function resetWorkspace() {
  if(localWorkspaceOnly){
    activeWorkspace.value='boulder'
    sessionStorage.setItem(workspaceStorageKey,'boulder')
    history.replaceState(null,'','#/photo-routes')
    return
  }
  activeWorkspace.value = ''
  sessionStorage.removeItem(workspaceStorageKey)
  history.replaceState(null, '', workspaceChooserHash)
}

function handleRootHashChange() {
  if(localWorkspaceOnly){
    const hash=localWorkspaceHash(location.hash)
    if(hash!==location.hash)history.replaceState(null,'',hash)
    activeWorkspace.value='boulder'
    sessionStorage.setItem(workspaceStorageKey,'boulder')
    return
  }
  if (location.hash === workspaceChooserHash) {
    activeWorkspace.value = ''
    return
  }
  const savedWorkspace = sessionStorage.getItem(workspaceStorageKey)
  if (!['boulder', 'setter'].includes(savedWorkspace)) return
  const requestedPage = String(location.hash || '').replace(/^#\/?/, '').split('/')[0]
  const restoredWorkspace = boulderPageKeys.includes(requestedPage) ? 'boulder' : (setterPageKeys.includes(requestedPage) ? 'setter' : savedWorkspace)
  activeWorkspace.value = restoredWorkspace
  sessionStorage.setItem(workspaceStorageKey, restoredWorkspace)
}

async function localLogin() {
  loginSubmitting.value = true
  loginError.value = ''
  try {
    sessionStorage.removeItem('local-account-signed-out')
    await loadSession()
  } finally { loginSubmitting.value = false }
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
      if (
        error?.response?.status === 401
        && !path.includes('/api/auth/login')
        && !path.includes('/api/auth/quick-login')
      ) {
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
  window.addEventListener('hashchange', handleRootHashChange)
  heartbeatTimer = window.setInterval(heartbeat, 30_000)
  statusTimer = window.setInterval(refreshLease, 10_000)
})

onBeforeUnmount(() => {
  window.clearInterval(heartbeatTimer)
  window.clearInterval(statusTimer)
  window.removeEventListener('hashchange', handleRootHashChange)
  if (responseInterceptor !== null) {
    apiClient.interceptors.response.eject(responseInterceptor)
  }
})
</script>
