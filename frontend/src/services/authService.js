const SESSION_KEY = 'zxt_supabase_session'
const DEMO_TOKEN = 'mock-token-local-demo'

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || ''
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY || import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || ''

function requireSupabaseConfig() {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
    throw new Error('Supabase Auth is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.')
  }
}

function saveSession(session) {
  window.localStorage.setItem(SESSION_KEY, JSON.stringify(session))
  window.localStorage.setItem('zxt_auth_token', session.access_token)
}

function clearSession() {
  window.localStorage.removeItem(SESSION_KEY)
  window.localStorage.removeItem('zxt_auth_token')
}

async function authRequest(path, options = {}) {
  requireSupabaseConfig()
  const response = await fetch(`${SUPABASE_URL.replace(/\/$/, '')}/auth/v1${path}`, {
    ...options,
    headers: {
      apikey: SUPABASE_ANON_KEY,
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(body.error_description || body.msg || body.message || 'Supabase Auth request failed')
  }
  return body
}

function sessionToUser(session) {
  const user = session?.user
  if (!user) return null
  return {
    id: user.id,
    name: user.user_metadata?.name || user.email?.split('@')[0] || 'Route Setter',
    email: user.email,
    role: user.user_metadata?.role || 'route-setter',
    provider: session.provider || 'supabase',
  }
}

export const authService = {
  getCurrentUser() {
    const raw = window.localStorage.getItem(SESSION_KEY)
    if (!raw) return null
    try {
      return sessionToUser(JSON.parse(raw))
    } catch {
      clearSession()
      return null
    }
  },

  async login({ email, password }) {
    const session = await authRequest('/token?grant_type=password', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
    saveSession(session)
    return sessionToUser(session)
  },

  async register({ email, password, name }) {
    const session = await authRequest('/signup', {
      method: 'POST',
      body: JSON.stringify({
        email,
        password,
        data: { name: name || email?.split('@')[0], role: 'route-setter' },
      }),
    })
    if (session.access_token) saveSession(session)
    return sessionToUser(session)
  },

  async skipLogin() {
    const session = {
      provider: 'local-demo',
      access_token: DEMO_TOKEN,
      user: {
        id: 'local-demo-user',
        email: 'demo@local.dev',
        user_metadata: {
          name: '本地体验用户',
          role: 'route-setter',
        },
      },
    }
    saveSession(session)
    return sessionToUser(session)
  },

  async logout() {
    const token = window.localStorage.getItem('zxt_auth_token')
    if (token && SUPABASE_URL && SUPABASE_ANON_KEY) {
      await authRequest('/logout', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => {})
    }
    clearSession()
  },
}

export default authService
