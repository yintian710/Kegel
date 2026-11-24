import { defineStore } from 'pinia'
import { loginUrl, status, type StatusData, type User } from '../api'

export const useIdentityStore = defineStore('identity', () => {
  const user = ref<User | null>(null)
  const oauthReady = ref(false)
  const loaded = ref(false)
  const loading = ref(false)
  let pending: Promise<StatusData> | null = null

  async function refresh(): Promise<StatusData> {
    if (pending) return pending
    loading.value = true
    pending = status()
    try {
      const data = await pending
      user.value = data.user
      oauthReady.value = data.oauth_ready
      loaded.value = true
      return data
    } finally {
      loading.value = false
      pending = null
    }
  }

  async function requireLogin(next: '/' | '/practice' | '/shop' | '/titles' | '/donate' | '/admin' | string): Promise<boolean> {
    if (!loaded.value) await refresh()
    if (oauthReady.value && !user.value) {
      window.location.assign(loginUrl(next))
      return false
    }
    return true
  }

  return { user, oauthReady, loaded, loading, refresh, requireLogin }
})
