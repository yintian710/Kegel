import { storeToRefs } from 'pinia'
import { useIdentityStore } from '../stores/identity'

export function useIdentity() {
  const store = useIdentityStore()
  return { ...storeToRefs(store), refresh: store.refresh, requireLogin: store.requireLogin }
}
