import { defineStore } from 'pinia'
import { apiGet, apiPost } from '../api/client'
import type { Me } from '../api/types'

export const useAuthStore = defineStore('auth', {
  state: () => ({ me: null as Me | null, loaded: false }),
  getters: {
    isAdmin: (s) => s.me?.role === 'admin',
  },
  actions: {
    async load() {
      try {
        this.me = await apiGet<Me>('/me')
      } catch {
        this.me = null
      } finally {
        this.loaded = true
      }
    },
    async login(email: string, password: string) {
      this.me = await apiPost<Me>('/login', { email, password })
      this.loaded = true
    },
    async logout() {
      await apiPost('/logout')
      this.me = null
    },
  },
})
