import { storeToRefs } from 'pinia'
import { useIdentityStore } from '../stores/identity'

export function useIdentity() {
  const store = useIdentityStore()
  return {
    ...storeToRefs(store),
    refresh: store.refresh,
    requireLogin: store.requireLogin,
    setWallet: store.setWallet,
    setBalance: store.setBalance,
    setStreak: store.setStreak,
  }
}
