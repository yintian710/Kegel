import { defineStore } from 'pinia'
import { ref } from 'vue'
import { loginUrl, status, type StatusData, type User, type Wallet } from '../api'

export const useIdentityStore = defineStore('identity', () => {
  const user = ref<User | null>(null)
  const wallet = ref<Wallet | null>(null)
  const streakDays = ref<number>(0)
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
      wallet.value = data.wallet
      streakDays.value = data.entry?.streak_days ?? data.streak_days ?? 0
      oauthReady.value = data.oauth_ready
      loaded.value = true
      return data
    } finally {
      loading.value = false
      pending = null
    }
  }

  function setWallet(newWallet: Wallet | null) {
    wallet.value = newWallet
  }

  function setBalance(balance: number) {
    if (wallet.value) {
      wallet.value.balance = balance
    } else {
      wallet.value = { balance }
    }
  }

  function setStreak(streak: number) {
    streakDays.value = streak
  }

  async function requireLogin(next: '/' | '/practice' | '/shop' | '/titles' | '/donate' | '/admin' | '/leaderboard' | '/profile' | string): Promise<boolean> {
    if (!loaded.value) await refresh()
    if (oauthReady.value && !user.value) {
      window.location.assign(loginUrl(next))
      return false
    }
    return true
  }

  return { user, wallet, streakDays, oauthReady, loaded, loading, refresh, setWallet, setBalance, setStreak, requireLogin }
})
