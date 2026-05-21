const MOCK_USER_KEY = 'zxt_mock_user'

export const authService = {
  getCurrentUser() {
    const raw = window.localStorage.getItem(MOCK_USER_KEY)
    if (!raw) return null
    try {
      return JSON.parse(raw)
    } catch {
      return null
    }
  },

  async login({ email, name }) {
    const user = {
      id: `local-user-${Date.now()}`,
      name: name || email?.split('@')[0] || '本地定线员',
      email: email || 'local.setter@example.com',
      role: 'route-setter',
      provider: 'mock-local',
    }
    window.localStorage.setItem(MOCK_USER_KEY, JSON.stringify(user))
    window.localStorage.setItem('zxt_auth_token', `mock-token-${user.id}`)
    return user
  },

  async logout() {
    window.localStorage.removeItem(MOCK_USER_KEY)
    window.localStorage.removeItem('zxt_auth_token')
  },
}

export default authService