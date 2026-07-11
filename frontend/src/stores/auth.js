import { defineStore } from 'pinia'

import { ApiError, apiFetch, getStoredToken, removeStoredToken, storeToken } from '../services/api'

const ROLE_LABELS = {
  highschool: '高校生',
  parent: '保護者',
  other: 'その他',
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getStoredToken(),
    user: null,
    isChecking: false,
  }),
  getters: {
    roleLabel: (state) => (state.user ? ROLE_LABELS[state.user.role] : ''),
  },
  actions: {
    async register(name, role) {
      const response = await apiFetch('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({ name, role }),
      })
      const payload = await response.json()
      this.setSession(payload.token, payload.user)
      return payload.user
    },
    async login(name) {
      const response = await apiFetch('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ name }),
      })
      const payload = await response.json()
      this.setSession(payload.token, payload.user)
      return payload.user
    },
    async ensureSession() {
      if (!this.token) {
        throw new ApiError('ログインが必要です。', 401)
      }
      if (this.user) {
        return this.user
      }
      this.isChecking = true
      try {
        const response = await apiFetch('/api/auth/me')
        const payload = await response.json()
        this.user = payload.user
        return this.user
      } finally {
        this.isChecking = false
      }
    },
    setSession(token, user) {
      this.token = token
      this.user = user
      storeToken(token)
    },
    clearSession() {
      this.token = null
      this.user = null
      removeStoredToken()
    },
  },
})
