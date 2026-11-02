<script setup lang="ts">
import { loginUrl, logoutUrl } from '../api'
import { ft, preferenceQuery } from '../composables/usePreferences'
import { useIdentity } from '../composables/useIdentity'

const route = useRoute()
const { user, oauthReady, loaded, loading, refresh } = useIdentity()
const loadFailed = ref(false)
const pages = [
  { path: '/', label: '首页' },
  { path: '/practice', label: '提肛练习' },
  { path: '/shop', label: '商店' },
  { path: '/donate', label: '赞助' },
  { path: '/admin', label: '管理' },
] as const
const carriedQuery = computed(() => preferenceQuery())
const accountLabel = computed(() => {
  if (loadFailed.value) return '账户加载失败'
  if (!loaded.value || loading.value) return '正在加载账户…'
  if (user.value) return `@${user.value.username} · 退出`
  return oauthReady.value ? 'LINUX DO 登录' : '登录暂未配置'
})
const accountDisabled = computed(() => loadFailed.value || !loaded.value || loading.value || (!user.value && !oauthReady.value))

function handleAccount(): void {
  if (user.value) window.location.assign(logoutUrl())
  else if (oauthReady.value) window.location.assign(loginUrl(route.path))
}

onMounted(async () => {
  try {
    await refresh()
  } catch {
    loadFailed.value = true
  }
})
</script>

<template>
  <header class="site-header" data-site-navigation>
    <RouterLink class="site-brand" :to="{ path: '/', query: carriedQuery }" data-interactive>
      <img class="brand-logo" :src="'/api/icon?size=48'" :alt="ft('提肛打卡 Logo')" />
      <span>{{ ft('提肛打卡') }}</span><span class="brand-badge">DAILY</span>
    </RouterLink>
    <nav class="site-nav" aria-label="主导航" data-interactive>
      <RouterLink
        v-for="page in pages"
        :key="page.path"
        class="nav-link"
        :class="{ active: route.path === page.path }"
        :aria-current="route.path === page.path ? 'page' : undefined"
        :to="{ path: page.path, query: carriedQuery }"
      >
        {{ ft(page.label) }}
      </RouterLink>
      <button id="accountButton" class="user-btn" type="button" :disabled="accountDisabled" @click="handleAccount">
        {{ accountLabel }}
      </button>
    </nav>
  </header>
</template>
