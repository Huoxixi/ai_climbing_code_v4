import { ref } from 'vue'
import authService from '../services/authService'

const currentUser = ref(authService.getCurrentUser())

export function useAuth() {
  const login = async (payload) => {
    currentUser.value = await authService.login(payload)
    return currentUser.value
  }

  const logout = async () => {
    await authService.logout()
    currentUser.value = null
  }

  return {
    currentUser,
    login,
    logout,
  }
}