<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { API_BASE, loginUrl, logoutUrl } from '../api'
import { applyTheme, ft, preferenceQuery, preferences, triggerHaptic, updatePreferences } from '../composables/usePreferences'
import { useIdentity } from '../composables/useIdentity'

const route = useRoute()
const { user, wallet, streakDays, oauthReady, loaded, loading, refresh } = useIdentity()
const loadFailed = ref(false)
const userMenuOpen = ref(false)
const menuRef = ref<HTMLElement | null>(null)

const pages = [
  { path: '/', label: '首页', icon: '🏠' },
  { path: '/practice', label: '练习', icon: '⚡' },
  { path: '/shop', label: '商城', icon: '🛍️' },
  { path: '/titles', label: '称号', icon: '👑' },
  { path: '/leaderboard', label: '排行榜', icon: '🏆' },
] as const

const carriedQuery = computed(() => preferenceQuery())

function toggleUserMenu(): void {
  userMenuOpen.value = !userMenuOpen.value
}

function closeUserMenu(e: MouseEvent): void {
  if (menuRef.value && !menuRef.value.contains(e.target as Node)) {
    userMenuOpen.value = false
  }
}

function handleAccount(): void {
  if (user.value) {
    toggleUserMenu()
  } else if (oauthReady.value) {
    window.location.assign(loginUrl(route.path))
  }
}

function handleLogout(): void {
  window.location.assign(logoutUrl())
}

function cycleTheme(): void {
  const current = preferences.theme || 'system'
  const next = current === 'dark' ? 'light' : current === 'light' ? 'system' : 'dark'
  updatePreferences({ theme: next })
  applyTheme()
  triggerHaptic()
}

function openSettings(): void {
  userMenuOpen.value = false
  const el = document.getElementById('practicePreferences') as HTMLDetailsElement | null
  if (el) {
    el.open = !el.open
  }
}

onMounted(async () => {
  document.addEventListener('click', closeUserMenu)
  try {
    await refresh()
  } catch {
    loadFailed.value = true
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('click', closeUserMenu)
})
</script>

<template>
  <header class="site-header-container" data-site-navigation>
    <div class="site-header-inner">
      <!-- 品牌 Logo -->
      <RouterLink class="site-brand" :to="{ path: '/', query: carriedQuery }" data-interactive>
        <div class="brand-icon-box">
          <svg class="lotus-svg" viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M16 4C16 4 11 12 11 18C11 21.3137 13.2386 24 16 24C18.7614 24 21 21.3137 21 18C21 12 16 4 16 4Z" fill="url(#lotus-grad)" />
            <path d="M9 13C9 13 4 18 5 23C5.5 25.5 8 26.5 11 25.5C13 24.8 14.5 23 15 21C13 20 10.5 17.5 9 13Z" fill="url(#lotus-grad-left)" opacity="0.85" />
            <path d="M23 13C23 13 28 18 27 23C26.5 25.5 24 26.5 21 25.5C19 24.8 17.5 23 17 21C19 20 21.5 17.5 23 13Z" fill="url(#lotus-grad-right)" opacity="0.85" />
            <path d="M7 23C11 27 21 27 25 23C23 27.5 9 27.5 7 23Z" fill="var(--primary)" opacity="0.9" />
            <defs>
              <linearGradient id="lotus-grad" x1="16" y1="4" x2="16" y2="24" gradientUnits="userSpaceOnUse">
                <stop stop-color="#2dd4bf" />
                <stop offset="1" stop-color="#0d9488" />
              </linearGradient>
              <linearGradient id="lotus-grad-left" x1="5" y1="13" x2="15" y2="25" gradientUnits="userSpaceOnUse">
                <stop stop-color="#5eead4" />
                <stop offset="1" stop-color="#0f766e" />
              </linearGradient>
              <linearGradient id="lotus-grad-right" x1="27" y1="13" x2="17" y2="25" gradientUnits="userSpaceOnUse">
                <stop stop-color="#5eead4" />
                <stop offset="1" stop-color="#0f766e" />
              </linearGradient>
            </defs>
          </svg>
        </div>
        <span class="brand-title">{{ ft('提肛打卡') }}</span>
        <span class="brand-badge">Daily</span>
      </RouterLink>

      <!-- 中间主导航 (带图标) -->
      <nav class="site-nav" aria-label="主导航" data-interactive>
        <RouterLink
          v-for="page in pages"
          :key="page.path"
          class="nav-link"
          :class="{ active: route.path === page.path }"
          :aria-current="route.path === page.path ? 'page' : undefined"
          :to="{ path: page.path, query: carriedQuery }"
        >
          <span class="nav-icon">{{ page.icon }}</span>
          <span class="nav-label">{{ ft(page.label) }}</span>
        </RouterLink>
      </nav>

      <!-- 右侧快捷状态与工具栏 -->
      <div class="header-actions">
        <!-- 连续打卡天数胶囊 (登录后显示) -->
        <RouterLink
          v-if="user"
          class="status-pill streak-pill"
          to="/profile"
          title="点击查看个人打卡概览"
        >
          <span class="pill-fire">🔥</span>
          <span class="pill-text">连续打卡 <strong>{{ streakDays }}</strong> 天</span>
        </RouterLink>

        <!-- 积分资产胶囊 (登录后显示) -->
        <RouterLink
          v-if="user"
          class="status-pill points-pill"
          to="/shop"
          title="点击前往积分商城"
        >
          <span class="pill-coin">🪙</span>
          <span class="pill-text">积分 <strong>{{ (wallet?.balance ?? 0).toLocaleString() }}</strong></span>
        </RouterLink>

        <!-- 主题切换按钮 -->
        <button
          class="icon-btn theme-toggle-btn"
          type="button"
          :title="`当前外观: ${preferences.theme === 'dark' ? '深色' : preferences.theme === 'light' ? '浅色' : '跟随系统'}`"
          aria-label="切换主题外观"
          @click="cycleTheme"
        >
          <span v-if="preferences.theme === 'dark'">🌙</span>
          <span v-else-if="preferences.theme === 'light'">☀️</span>
          <span v-else>💻</span>
        </button>

        <!-- 用户头像或登录按钮 -->
        <div v-if="user" ref="menuRef" class="user-profile-menu-wrap">
          <button
            class="user-avatar-btn"
            type="button"
            :class="{ active: userMenuOpen }"
            aria-label="用户账户菜单"
            @click="handleAccount"
          >
            <div class="user-avatar">
              <span>{{ user.username.slice(0, 1).toUpperCase() }}</span>
            </div>
            <span class="user-name">@{{ user.username }}</span>
            <span class="dropdown-chevron">▾</span>
          </button>

          <!-- 下拉菜单浮层 -->
          <transition name="dropdown-fade">
            <div v-if="userMenuOpen" class="user-dropdown-panel">
              <div class="dropdown-header">
                <div class="dropdown-avatar">{{ user.username.slice(0, 1).toUpperCase() }}</div>
                <div class="dropdown-user-info">
                  <div class="dropdown-name">{{ user.name || user.username }}</div>
                  <div class="dropdown-username">@{{ user.username }}</div>
                </div>
              </div>
              <div class="dropdown-divider" />
              <RouterLink class="dropdown-item" to="/profile" @click="userMenuOpen = false">
                <span>👤</span> 个人中心
              </RouterLink>
              <RouterLink class="dropdown-item" to="/shop" @click="userMenuOpen = false">
                <span>🪙</span> 积分资产 ({{ (wallet?.balance ?? 0).toLocaleString() }} 分)
              </RouterLink>
              <RouterLink class="dropdown-item" to="/titles" @click="userMenuOpen = false">
                <span>👑</span> 称号背包
              </RouterLink>
              <button class="dropdown-item" type="button" @click="openSettings">
                <span>⚙️</span> 偏好设置
              </button>
              <RouterLink class="dropdown-item" to="/admin" @click="userMenuOpen = false">
                <span>🛡️</span> 管理后台
              </RouterLink>
              <div class="dropdown-divider" />
              <button class="dropdown-item text-danger" type="button" @click="handleLogout">
                <span>🚪</span> 退出登录
              </button>
            </div>
          </transition>
        </div>

        <button
          v-else
          class="login-pill-btn"
          type="button"
          :disabled="!loaded || loading || !oauthReady"
          @click="handleAccount"
        >
          {{ !loaded || loading ? '正在加载…' : oauthReady ? 'LINUX DO 登录' : '登录未配置' }}
        </button>
      </div>
    </div>
  </header>
</template>

<style scoped>
.site-header-container {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 60px;
  z-index: 1000;
  width: 100%;
  background: var(--glass-bg);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.04);
  transition: background-color 0.3s ease, border-color 0.3s ease;
}

.site-header-inner {
  max-width: 1360px;
  margin: 0 auto;
  height: 100%;
  padding: 0 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.site-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
  color: var(--text-main);
  flex-shrink: 0;
}

.brand-icon-box {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  background: var(--primary-light);
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--primary-border);
}

.lotus-svg {
  width: 22px;
  height: 22px;
}

.brand-title {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.brand-badge {
  font-size: 10px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-light);
  border: 1px solid var(--primary-border);
  padding: 1px 6px;
  border-radius: var(--radius-pill);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.site-nav {
  display: flex;
  align-items: center;
  gap: 4px;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: var(--radius-pill);
  font-size: 14px;
  font-weight: 500;
  color: var(--text-muted);
  text-decoration: none;
  transition: all 0.2s ease;
}

.nav-link:hover {
  color: var(--text-main);
  background: var(--bg-subtle);
}

.nav-link.active {
  color: var(--primary);
  background: var(--primary-light);
  font-weight: 600;
}

.nav-icon {
  font-size: 14px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: var(--radius-pill);
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  transition: all 0.2s ease;
}

.streak-pill {
  background: var(--amber-light);
  color: #b45309;
  border: 1px solid var(--amber-border);
}

[data-theme="dark"] .streak-pill {
  color: #fbbf24;
}

.streak-pill:hover {
  transform: translateY(-1px);
  filter: brightness(1.05);
}

.points-pill {
  background: var(--primary-light);
  color: var(--primary);
  border: 1px solid var(--primary-border);
}

.points-pill:hover {
  transform: translateY(-1px);
  filter: brightness(1.05);
}

.pill-text strong {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.user-profile-menu-wrap {
  position: relative;
}

.user-avatar-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 10px 4px 4px;
  border-radius: var(--radius-pill);
  background: var(--bg-card);
  border: 1px solid var(--border);
  color: var(--text-main);
  cursor: pointer;
  transition: all 0.2s ease;
}

.user-avatar-btn:hover, .user-avatar-btn.active {
  border-color: var(--primary-border);
  background: var(--primary-light);
}

.user-avatar {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary) 0%, #065f46 100%);
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
}

.user-name {
  font-size: 13px;
  font-weight: 600;
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dropdown-chevron {
  font-size: 11px;
  color: var(--text-muted);
}

.user-dropdown-panel {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  width: 220px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-hover);
  padding: 6px;
  z-index: 120;
}

.dropdown-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
}

.dropdown-avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary) 0%, #065f46 100%);
  color: #ffffff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
}

.dropdown-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-main);
}

.dropdown-username {
  font-size: 12px;
  color: var(--text-muted);
}

.dropdown-divider {
  height: 1px;
  background: var(--border-light);
  margin: 4px 0;
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 8px 12px;
  font-size: 13px;
  color: var(--text-main);
  border-radius: var(--radius-sm);
  text-decoration: none;
  background: none;
  border: none;
  cursor: pointer;
  transition: all 0.15s ease;
  text-align: left;
}

.dropdown-item:hover {
  background: var(--bg-subtle);
  color: var(--primary);
}

.dropdown-item.text-danger:hover {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.login-pill-btn {
  padding: 6px 16px;
  font-size: 13px;
  font-weight: 600;
  border-radius: var(--radius-pill);
  background: var(--primary);
  color: #ffffff;
  cursor: pointer;
  border: none;
  transition: all 0.2s ease;
}

.login-pill-btn:hover {
  background: var(--primary-hover);
  transform: translateY(-1px);
}

.dropdown-fade-enter-active, .dropdown-fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.dropdown-fade-enter-from, .dropdown-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

@media (max-width: 900px) {
  .nav-label {
    display: none;
  }
  .streak-pill, .points-pill {
    display: none;
  }
}
</style>
